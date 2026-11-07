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

st.title('Andigo · Inteligencia comercial y precios')
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

catalogo, comparador, historial, estado, rentabilidad = st.tabs([
    '📦 Catálogo', '⚖️ Comparador', '📈 Historial', '🛠️ Ejecuciones', '💰 Rentabilidad'
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


with rentabilidad:
    st.subheader('Rentabilidad objetivo: margen bruto mínimo 30 %')
    st.caption('Simulación por unidad de venta. Compara únicamente productos equivalentes y el mismo formato de embalaje.')
    comp = view[view['provider'] == 'Disprolim'].sort_values('name')
    wholesale = view[view['provider'] != 'Disprolim'].sort_values(['provider','name'])
    if comp.empty or wholesale.empty:
        st.info('Se requieren productos de Disprolim y al menos un mayorista.')
    else:
        competitor_id = st.selectbox('Producto de Disprolim (referencia de venta)', comp['id'].tolist(),
            format_func=lambda x: comp.loc[comp['id'] == x, 'name'].iloc[0], key='rent_comp')
        supplier_id = st.selectbox('Producto del proveedor (selección manual)', wholesale['id'].tolist(),
            format_func=lambda x: (wholesale.loc[wholesale['id'] == x, 'provider'].iloc[0] + ' · ' +
                                   wholesale.loc[wholesale['id'] == x, 'name'].iloc[0]), key='rent_supplier')
        competitor_row = comp.loc[comp['id'] == competitor_id].iloc[0]
        supplier_row = wholesale.loc[wholesale['id'] == supplier_id].iloc[0]
        st.warning('Seleccionar dos productos NO confirma equivalencia. Verifica concentración, tamaño, pack y calidad.')
        a,b,c = st.columns(3)
        with a:
            discount = st.slider('Vender % más barato que Disprolim', 0, 15, 3, key='rent_discount')
        with b:
            other_cost = st.number_input('Otros costos variables netos ($)', min_value=0.0, value=0.0, step=100.0)
        with c:
            pack_units = st.number_input('Unidades vendibles por embalaje comprado', min_value=1, value=1, step=1)
        iva = st.radio('¿Cómo está publicado el precio del proveedor?',
            ['Neto, sin IVA', 'IVA incluido', 'Desconocido: no calcular margen'],
            index=0 if 'IVA excluido' in str(supplier_row['vat_status']) else 2)
        comp_iva = st.checkbox('El precio de Disprolim incluye IVA (19 %)', value=True)
        equivalent = st.checkbox('Confirmé manualmente que ambos productos son equivalentes en calidad, presentación y cantidad', value=False)
        published = float(supplier_row['price_clp'])
        net_cost = published / (1.19 if iva == 'IVA incluido' else 1) / pack_units
        comp_price = float(competitor_row['price_clp'])
        sale_gross = comp_price * (1-discount/100)
        sale_net = sale_gross / (1.19 if comp_iva else 1)
        margin = (sale_net - net_cost - other_cost) / sale_net * 100 if sale_net > 0 else float('nan')
        max_cost = sale_net * 0.70 - other_cost
        st.caption(f'Proveedor: {supplier_row["provider"]} · Precio publicado por embalaje: ${published:,.0f} · Estado IVA: {supplier_row["vat_status"]}')
        if iva.startswith('Desconocido') or not equivalent:
            st.info('Pendiente de validar IVA o equivalencia. No se emite recomendación de rentabilidad.')
        else:
            x,y,z = st.columns(3)
            x.metric('Precio de venta estimado', f'${sale_gross:,.0f}')
            y.metric('Margen bruto estimado', f'{margin:.1f}%')
            z.metric('Costo máximo neto/unidad para 30 %', f'${max_cost:,.0f}')
            if margin >= 30:
                st.success('Alcanza el margen bruto mínimo del 30 % bajo los supuestos ingresados.')
            else:
                st.error('No alcanza el margen bruto mínimo del 30 % bajo los supuestos ingresados.')
        st.caption('Supuestos: venta afecta a IVA 19 %, compra con crédito fiscal recuperable, y costos variables netos. No incluye costos fijos ni impuestos sobre utilidades. No guarda equivalencias confirmadas.')
