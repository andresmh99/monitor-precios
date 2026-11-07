import os

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title='Monitor de precios', page_icon='📈', layout='wide')

# Streamlit Cloud expone secretos en st.secrets; db.py lee DATABASE_URL al importarse.
try:
    if 'DATABASE_URL' in st.secrets:
        os.environ['DATABASE_URL'] = st.secrets['DATABASE_URL']
except FileNotFoundError:
    pass

from db import connect, init, run
from comparador import construir_comparaciones

st.title('Monitor de precios · Purity y Disprolim')
st.caption('Precios publicados en CLP · Capturas históricas · Comparaciones orientativas')

if not os.getenv('DATABASE_URL', '').startswith(('postgresql://', 'postgres://')):
    st.error('Falta configurar DATABASE_URL de PostgreSQL en los secretos de Streamlit.')
    st.stop()


def consultar(conn, sql):
    cursor = run(conn, sql)
    columnas = [col.name if hasattr(col, 'name') else col[0] for col in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columnas)


@st.cache_data(ttl=300)
def cargar_datos():
    init()
    with connect() as conn:
        productos = consultar(conn, 'SELECT * FROM products')
        observaciones = consultar(conn, 'SELECT * FROM observations')
        ejecuciones = consultar(conn, 'SELECT * FROM scrape_runs ORDER BY checked_at DESC')
    return productos, observaciones, ejecuciones


try:
    prods, obs, runs = cargar_datos()
except Exception:
    st.error('No se pudo consultar Supabase. Revisa DATABASE_URL y los registros de Streamlit.')
    st.stop()

if prods.empty or obs.empty:
    st.info('Aún no hay productos y observaciones registrados en Supabase.')
    st.stop()

obs['observed_at'] = pd.to_datetime(obs['observed_at'], utc=True)
latest = obs.sort_values(['observed_at', 'id']).drop_duplicates('product_id', keep='last')
view = prods.merge(latest[['product_id', 'price_clp', 'observed_at']], left_on='id', right_on='product_id')

providers = sorted(view['provider'].unique().tolist())
selected = st.sidebar.multiselect('Proveedores', providers, default=providers)
search = st.sidebar.text_input('Buscar producto')
period = st.sidebar.selectbox('Periodo histórico (días)', [7, 30, 90, 180, 365], index=2)
if st.sidebar.button('Actualizar datos'):
    cargar_datos.clear()
    st.rerun()

filtered = view[view['provider'].isin(selected)].copy()
if search:
    filtered = filtered[filtered['name'].str.contains(search, case=False, na=False, regex=False)].copy()

prior = obs.sort_values(['observed_at', 'id']).groupby('product_id').tail(2)
change = prior.groupby('product_id')['price_clp'].agg(['first', 'last', 'count']).reset_index()
change['pct'] = ((change['last'] - change['first']) / change['first'] * 100).where(
    (change['count'] >= 2) & (change['first'] != 0)
)
filtered = filtered.merge(change[['product_id', 'pct']], on='product_id', how='left')

catalogo, comparador, historial, estado = st.tabs([
    '📦 Catálogo', '⚖️ Comparador', '📈 Historial', '🛠️ Ejecuciones'
])

with catalogo:
    a, b, c, d = st.columns(4)
    a.metric('Productos', len(filtered))
    b.metric('Proveedores', filtered['provider'].nunique())
    c.metric('Cambios registrados', int(filtered['pct'].fillna(0).ne(0).sum()))
    d.metric('Consultas fallidas', int((runs['status'] == 'error').sum()) if not runs.empty else 0)
    mostrar = filtered[['provider', 'name', 'price_clp', 'pct', 'observed_at', 'url', 'vat_status']].rename(columns={
        'provider': 'Proveedor', 'name': 'Producto', 'price_clp': 'Precio CLP',
        'pct': 'Cambio %', 'observed_at': 'Última captura', 'url': 'Enlace', 'vat_status': 'IVA'
    })
    st.dataframe(mostrar, use_container_width=True, hide_index=True)
    st.download_button('Exportar catálogo CSV', mostrar.to_csv(index=False).encode('utf-8-sig'),
                       'catalogo_precios.csv', 'text/csv')

with comparador:
    st.subheader('Comparación de productos similares')
    st.warning('Las coincidencias son candidatas. No se confirma equivalencia técnica ni un proveedor ganador. El IVA de Purity sigue pendiente de validar.')
    # El comparador usa todo el catálogo, independientemente de los filtros de la barra lateral.
    pares = construir_comparaciones(view)
    if pares.empty:
        st.info('No se detectaron candidatos de comparación con las categorías actuales.')
    else:
        categorias = sorted(pares['categoria'].unique().tolist())
        cat = st.selectbox('Categoría', ['Todas'] + categorias)
        solo_formato = st.checkbox('Solo productos con volumen/peso/unidad comparable', value=True)
        candidatos = pares.copy()
        if cat != 'Todas':
            candidatos = candidatos[candidatos['categoria'] == cat]
        if solo_formato:
            candidatos = candidatos[candidatos['unidad'].notna()]
        candidatos = candidatos.sort_values('similitud', ascending=False)
        columnas = [
            'categoria', 'purity_producto', 'purity_precio', 'disprolim_producto',
            'disprolim_precio', 'cantidad_purity', 'cantidad_disprolim', 'unidad',
            'purity_precio_base', 'disprolim_precio_base', 'diferencia_pct',
            'estado', 'observacion', 'purity_url', 'disprolim_url'
        ]
        st.caption('Diferencia % = (precio base Disprolim − precio base Purity) / precio base Disprolim × 100. Un valor positivo indica que Purity tiene menor precio publicado por unidad base, sin ajustar IVA.')
        st.dataframe(candidatos[columnas], use_container_width=True, hide_index=True,
                     column_config={
                         'purity_precio': st.column_config.NumberColumn('Purity CLP', format='$%.0f'),
                         'disprolim_precio': st.column_config.NumberColumn('Disprolim CLP', format='$%.0f'),
                         'purity_precio_base': st.column_config.NumberColumn('Purity / unidad', format='$%.0f'),
                         'disprolim_precio_base': st.column_config.NumberColumn('Disprolim / unidad', format='$%.0f'),
                         'diferencia_pct': st.column_config.NumberColumn('Diferencia %', format='%.1f%%'),
                         'purity_url': st.column_config.LinkColumn('Ver Purity'),
                         'disprolim_url': st.column_config.LinkColumn('Ver Disprolim'),
                     })
        st.download_button('Exportar comparaciones CSV', candidatos.to_csv(index=False).encode('utf-8-sig'),
                           'comparaciones_pendientes.csv', 'text/csv')
        st.caption(f'{len(candidatos)} pares candidatos mostrados. Revisar pack, calidad, concentración e IVA antes de comprar.')

with historial:
    st.subheader('Historial de precios')
    if filtered.empty:
        st.info('Selecciona al menos un proveedor o ajusta la búsqueda.')
    else:
        options = filtered.sort_values('name').copy()
        options['label'] = options['provider'] + ' · ' + options['name']
        selected_id = st.selectbox('Producto', options['id'].tolist(),
                                   format_func=lambda x: options.loc[options['id'] == x, 'label'].iloc[0])
        since = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=period)
        history = obs[(obs['product_id'] == selected_id) & (obs['observed_at'] >= since)].sort_values('observed_at')
        if history.empty:
            st.info('No hay observaciones en el período seleccionado.')
        else:
            fig = px.line(history, x='observed_at', y='price_clp', markers=True,
                          labels={'observed_at': 'Fecha', 'price_clp': 'Precio CLP'})
            st.plotly_chart(fig, use_container_width=True)
            st.caption('El historial empieza en la primera captura registrada; no se reconstruyen precios anteriores.')

with estado:
    st.subheader('Estado de las consultas automáticas')
    if runs.empty:
        st.info('Aún no hay ejecuciones registradas.')
    else:
        st.dataframe(runs[['provider', 'checked_at', 'status', 'products_found', 'details']].head(50),
                     use_container_width=True, hide_index=True)
