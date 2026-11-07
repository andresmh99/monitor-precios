import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd


def normalizar(texto):
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto.lower()).strip()


PATRON = re.compile(r'(?<!\d)(\d+(?:[.,]\d+)?)\s*(litros?|lts?\.?|ml|cc|grs?\.?|gramos?|kg|kilos?|unidades?|unds?\.?|un\.?)(?![a-z])', re.I)


def formato(nombre):
    texto = normalizar(nombre)
    coincidencias = list(PATRON.finditer(texto))
    if not coincidencias:
        return None, None
    # Se usa el último tamaño explícito. Si hay varios formatos, requiere revisión manual.
    m = coincidencias[-1]
    cantidad = float(m.group(1).replace(',', '.'))
    unidad = m.group(2).rstrip('.')
    if unidad in ('ml', 'cc'):
        return cantidad / 1000, 'L'
    if unidad.startswith(('litro', 'lt')):
        return cantidad, 'L'
    if unidad in ('kg', 'kilo', 'kilos'):
        return cantidad, 'kg'
    if unidad.startswith(('gr', 'gramo')):
        return cantidad / 1000, 'kg'
    return cantidad, 'un'


CATEGORIAS = [
    ('abrillantador piso flotante', ('abrillantador', 'piso', 'flotante')),
    ('limpiador piso flotante', ('limpiador', 'piso', 'flotante')),
    ('desengrasante', ('desengrasante',)),
    ('limpiavidrios', ('limpiavidrio',)),
    ('bolsas basura', ('bolsa', 'basura')),
    ('lustra muebles', ('lustra', 'mueble')),
    ('guantes', ('guante',)),
    ('panos microfibra', ('pano', 'microfibra')),
    ('traperos', ('trapero',)),
    ('esponjas', ('esponja',)),
    ('escobas', ('escoba', 'escobillon')),
    ('mopas', ('mopa',)),
]


def categoria(nombre):
    t = normalizar(nombre)
    for etiqueta, palabras in CATEGORIAS:
        if etiqueta == 'escobas':
            if any(p in t for p in palabras):
                return etiqueta
        elif all(p in t for p in palabras):
            return etiqueta
    return None


def construir_comparaciones(productos, max_por_purity=5):
    columnas = [
        'categoria', 'purity_id', 'purity_producto', 'purity_precio',
        'purity_url', 'purity_iva', 'disprolim_id', 'disprolim_producto',
        'disprolim_precio', 'disprolim_url', 'disprolim_iva',
        'cantidad_purity', 'cantidad_disprolim', 'unidad',
        'purity_precio_base', 'disprolim_precio_base',
        'diferencia_pct', 'ahorro_clp_base', 'similitud',
        'estado', 'observacion'
    ]
    if productos.empty:
        return pd.DataFrame(columns=columnas)
    df = productos.copy()
    df['categoria_comparacion'] = df['name'].map(categoria)
    formatos = df['name'].map(formato)
    df['cantidad'] = formatos.map(lambda x: x[0])
    df['unidad_formato'] = formatos.map(lambda x: x[1])
    purity = df[(df['provider'] == 'Purity') & df['categoria_comparacion'].notna()]
    disprolim = df[(df['provider'] == 'Disprolim') & df['categoria_comparacion'].notna()]
    resultado = []
    for _, p in purity.iterrows():
        candidatos = disprolim[disprolim['categoria_comparacion'] == p['categoria_comparacion']]
        ranking = []
        for _, d in candidatos.iterrows():
            mismo_formato = (p['unidad_formato'] is not None and p['unidad_formato'] == d['unidad_formato']
                             and p['cantidad'] is not None and d['cantidad'] is not None
                             and p['cantidad'] > 0 and d['cantidad'] > 0)
            similitud = SequenceMatcher(None, normalizar(p['name']), normalizar(d['name'])).ratio()
            if mismo_formato:
                similitud += 0.15
            ranking.append((similitud, mismo_formato, d))
        ranking.sort(key=lambda x: x[0], reverse=True)
        for similitud, mismo_formato, d in ranking[:max_por_purity]:
            precio_p = float(p['price_clp'])
            precio_d = float(d['price_clp'])
            pp = precio_p / p['cantidad'] if mismo_formato else None
            pd_ = precio_d / d['cantidad'] if mismo_formato else None
            diferencia = (pd_ - pp) / pd_ * 100 if mismo_formato and pd_ else None
            ahorro = pd_ - pp if mismo_formato else None
            iva_confirmado = ('confirmar' not in normalizar(p.get('vat_status', ''))
                              and 'confirmar' not in normalizar(d.get('vat_status', '')))
            observacion = ('Formato no comparable; revisar unidades, presentación y pack'
                           if not mismo_formato else
                           'Revisar fórmula, concentración, IVA y condiciones comerciales')
            if not iva_confirmado:
                observacion += '; IVA pendiente de validar'
            resultado.append({
                'categoria': p['categoria_comparacion'],
                'purity_id': p['id'], 'purity_producto': p['name'],
                'purity_precio': precio_p, 'purity_url': p.get('url', ''),
                'purity_iva': p.get('vat_status', ''),
                'disprolim_id': d['id'], 'disprolim_producto': d['name'],
                'disprolim_precio': precio_d, 'disprolim_url': d.get('url', ''),
                'disprolim_iva': d.get('vat_status', ''),
                'cantidad_purity': p['cantidad'], 'cantidad_disprolim': d['cantidad'],
                'unidad': p['unidad_formato'] if mismo_formato else None,
                'purity_precio_base': pp, 'disprolim_precio_base': pd_,
                'diferencia_pct': diferencia, 'ahorro_clp_base': ahorro,
                'similitud': min(similitud, 1.0),
                'estado': 'Candidato - pendiente de validar',
                'observacion': observacion
            })
    return pd.DataFrame(resultado, columns=columnas)
