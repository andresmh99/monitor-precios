import os
import pandas as pd
import streamlit as st
import plotly.express as px
from db import connect, run, init

st.set_page_config(page_title='Monitor de precios',page_icon='📈',layout='wide')
st.title('Monitor de precios · Purity y Disprolim')
st.caption('Historial de capturas verificadas · CLP · Comparar formatos e IVA antes de decidir compras')
try:
    init()
    with connect() as c:
        prods=pd.read_sql_query('SELECT * FROM products',c)
        obs=pd.read_sql_query('SELECT * FROM observations',c)
        runs=pd.read_sql_query('SELECT * FROM scrape_runs ORDER BY checked_at DESC',c)
except Exception as exc:
    st.error('No se pudo conectar a la base de datos. Revisa DATABASE_URL.'); st.stop()
if prods.empty or obs.empty:
    st.info('Aún no hay datos. Ejecuta `python seed.py` una vez para cargar los Excel iniciales.'); st.stop()
obs['observed_at']=pd.to_datetime(obs['observed_at'],utc=True)
latest=obs.sort_values(['observed_at','id']).drop_duplicates('product_id',keep='last')
view=prods.merge(latest[['product_id','price_clp','observed_at']],left_on='id',right_on='product_id')
providers=sorted(view.provider.unique().tolist())
selected=st.sidebar.multiselect('Proveedores',providers,default=providers)
search=st.sidebar.text_input('Buscar producto')
period=st.sidebar.selectbox('Periodo histórico (días)',[7,30,90,180,365],index=2)
view=view[view.provider.isin(selected)]
if search: view=view[view.name.str.contains(search,case=False,na=False,regex=False)]
now=pd.Timestamp.now(tz='UTC')
recent=obs[obs.observed_at>=now-pd.Timedelta(days=period)]
prior=obs.sort_values(['observed_at','id']).groupby('product_id').tail(2).sort_values(['product_id','observed_at'])
change=prior.groupby('product_id').price_clp.agg(['first','last','count']).reset_index()
change['pct']=((change['last']-change['first'])/change['first']*100).where(change['count']>=2)
view=view.merge(change[['product_id','pct']],on='product_id',how='left')
a,b,c,d=st.columns(4)
a.metric('Productos',len(view)); b.metric('Proveedores',len(selected))
c.metric('Cambios registrados',int(change['pct'].fillna(0).ne(0).sum()))
d.metric('Consultas fallidas',int((runs.status=='error').sum()) if not runs.empty else 0)
st.subheader('Catálogo y última variación registrada')
st.dataframe(view[['provider','name','price_clp','pct','observed_at','url','vat_status']].rename(columns={'provider':'Proveedor','name':'Producto','price_clp':'Precio CLP','pct':'Cambio %','observed_at':'Última captura','url':'Enlace','vat_status':'IVA'}),use_container_width=True,hide_index=True)
st.subheader('Historial de precios')
if len(view):
    options=view.sort_values('name').copy()
    options['label']=options['provider']+' · '+options['name']
    selected_id=st.selectbox('Producto',options['id'].tolist(),format_func=lambda x:options.loc[options.id==x,'label'].iloc[0])
    history=obs[(obs.product_id==selected_id)&(obs.observed_at>=now-pd.Timedelta(days=period))].sort_values('observed_at')
    if len(history):
        fig=px.line(history,x='observed_at',y='price_clp',markers=True,labels={'observed_at':'Fecha','price_clp':'Precio CLP'})
        st.plotly_chart(fig,use_container_width=True)
        st.caption('El historial comienza con la primera captura disponible; no se reconstruyen precios anteriores.')
st.subheader('Estado de las consultas')
if not runs.empty: st.dataframe(runs[['provider','checked_at','status','products_found','details']].head(30),hide_index=True,use_container_width=True)
st.warning('Las equivalencias entre proveedores NO están confirmadas automáticamente. Para comparar precios por litro/unidad, validar contenido, pack e IVA.')
st.download_button('Exportar catálogo CSV',view.to_csv(index=False).encode('utf-8-sig'),'precios_actuales.csv','text/csv')
