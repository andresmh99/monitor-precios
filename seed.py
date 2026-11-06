"""Importa las capturas aportadas por el usuario como línea base; NO simula historial anterior."""
import pandas as pd
from db import init, save, record_run
from scrapers import price_clp
from pathlib import Path

BASE=Path(__file__).parent/'data'

def main():
    init()
    files=['disprolim_quimicos_completo.xlsx','disprolim_quimicos_completo_1.xlsx']
    merged={}
    for fn in files:
        for r in pd.read_excel(BASE/fn).fillna('').to_dict('records'):
            name=str(r.get('nombre','')).strip(); url=str(r.get('url','')).strip()
            price=price_clp(str(r.get('precio','')))
            if name and url and price is not None:
                merged[url]={'name':name,'url':url,'price':price,'vat_status':'IVA incluido (sitio)'}
    save('Disprolim',list(merged.values()),'importacion_archivos_usuario')
    record_run('Disprolim','importacion',len(merged),'Captura inicial importada; fecha exacta de cada precio no disponible')
    df=pd.read_excel(BASE/'catalogo_purity_precios.xlsx',sheet_name='Productos').fillna('')
    rows=[]
    for r in df.to_dict('records'):
        name=str(r.get('Producto','')).strip()
        price=r.get('Precio unitario (CLP)')
        if not name or not isinstance(price,(float,int)) or price<=0: continue
        rows.append({'name':name,'url':'','price':float(price),'vat_status':'IVA no verificado'})
    save('Purity',rows,'importacion_catalogo_usuario')
    record_run('Purity','importacion',len(rows),'Precios unitarios importados; IVA y formatos requieren validación')
    print(f'Importados: Disprolim={len(merged)}, Purity={len(rows)}')
if __name__=='__main__': main()
