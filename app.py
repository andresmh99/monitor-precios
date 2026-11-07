
import os
import pandas as pd
import streamlit as st
import plotly.express as px

from db import connect, run, init

st.set_page_config(
    page_title="Monitor de precios",
    page_icon="📈",
    layout="wide"
)

st.title("Monitor de precios · Purity y Disprolim")
st.caption(
    "Historial de capturas verificadas · CLP · "
    "Comparar formatos e IVA antes de decidir compras"
)

# Permite usar DATABASE_URL desde Streamlit Cloud
if "DATABASE_URL" in st.secrets:
    os.environ["DATABASE_URL"] = st.secrets["DATABASE_URL"]

# db.py determina el motor al importarse.
# Por eso actualizamos su configuracion.
import db
db.DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
db.PG = db.DATABASE_URL.startswith(
    ("postgres://", "postgresql://")
)

if not db.PG:
    st.error("DATABASE_URL no tiene formato PostgreSQL.")
    st.stop()


def consultar(conn, sql):
    cursor = run(conn, sql)
    columnas = [
        col.name if hasattr(col, "name") else col[0]
        for col in cursor.description
    ]
    return pd.DataFrame(cursor.fetchall(), columns=columnas)


try:
    init()

    with connect() as conn:
        prods = consultar(conn, "SELECT * FROM products")
        obs = consultar(conn, "SELECT * FROM observations")
        runs = consultar(
            conn,
            "SELECT * FROM scrape_runs ORDER BY checked_at DESC"
        )

except Exception:
    st.error(
        "No se pudo conectar a Supabase. "
        "Revisa DATABASE_URL y los permisos de PostgreSQL."
    )
    st.stop()

if prods.empty or obs.empty:
    st.info("Todavia no hay productos o precios registrados.")
    st.stop()

obs["observed_at"] = pd.to_datetime(
    obs["observed_at"],
    utc=True
)

latest = (
    obs.sort_values(["observed_at", "id"])
    .drop_duplicates("product_id", keep="last")
)

view = prods.merge(
    latest[["product_id", "price_clp", "observed_at"]],
    left_on="id",
    right_on="product_id"
)

providers = sorted(view["provider"].unique().tolist())

selected = st.sidebar.multiselect(
    "Proveedores",
    providers,
    default=providers
)

search = st.sidebar.text_input("Buscar producto")

period = st.sidebar.selectbox(
    "Periodo historico (dias)",
    [7, 30, 90, 180, 365],
    index=2
)

view = view[view["provider"].isin(selected)].copy()

if search:
    view = view[
        view["name"].str.contains(
            search,
            case=False,
            na=False,
            regex=False
        )
    ].copy()

now = pd.Timestamp.now(tz="UTC")

prior = (
    obs.sort_values(["observed_at", "id"])
    .groupby("product_id")
    .tail(2)
    .sort_values(["product_id", "observed_at"])
)

change = (
    prior.groupby("product_id")["price_clp"]
    .agg(["first", "last", "count"])
    .reset_index()
)

change["pct"] = (
    (change["last"] - change["first"])
    / change["first"] * 100
).where(
    (change["count"] >= 2) &
    (change["first"] != 0)
)

view = view.merge(
    change[["product_id", "pct"]],
    on="product_id",
    how="left"
)

a, b, c, d = st.columns(4)

a.metric("Productos", len(view))
b.metric("Proveedores", view["provider"].nunique())

c.metric(
    "Cambios registrados",
    int(change["pct"].fillna(0).ne(0).sum())
)

d.metric(
    "Consultas fallidas",
    int((runs["status"] == "error").sum())
    if not runs.empty else 0
)

st.subheader("Catalogo y ultima variacion registrada")

columns = [
    "provider",
    "name",
    "price_clp",
    "pct",
    "observed_at",
    "url",
    "vat_status"
]

display = view[columns].rename(
    columns={
        "provider": "Proveedor",
        "name": "Producto",
        "price_clp": "Precio CLP",
        "pct": "Cambio %",
        "observed_at": "Ultima captura",
        "url": "Enlace",
        "vat_status": "IVA"
    }
)

st.dataframe(
    display,
    use_container_width=True,
    hide_index=True
)

st.subheader("Historial de precios")

if not view.empty:
    options = view.sort_values("name").copy()

    options["label"] = (
        options["provider"] + " · " + options["name"]
    )

    selected_id = st.selectbox(
        "Producto",
        options["id"].tolist(),
        format_func=lambda x: options.loc[
            options["id"] == x, "label"
        ].iloc[0]
    )

    history = obs[
        (obs["product_id"] == selected_id) &
        (
            obs["observed_at"] >=
            now - pd.Timedelta(days=period)
        )
    ].sort_values("observed_at")

    if not history.empty:
        fig = px.line(
            history,
            x="observed_at",
            y="price_clp",
            markers=True,
            labels={
                "observed_at": "Fecha",
                "price_clp": "Precio CLP"
            }
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

        st.caption(
            "El historial comienza con la primera "
            "captura disponible."
        )

st.subheader("Estado de las consultas")

if not runs.empty:
    st.dataframe(
        runs[
            [
                "provider",
                "checked_at",
                "status",
                "products_found",
                "details"
            ]
        ].head(30),
        hide_index=True,
        use_container_width=True
    )

st.warning(
    "Las equivalencias entre proveedores no estan "
    "confirmadas automaticamente. Verificar contenido, "
    "formato, unidades e IVA."
)

st.download_button(
    "Exportar catalogo CSV",
    view.to_csv(index=False).encode("utf-8-sig"),
    "precios_actuales.csv",
    "text/csv"
)
