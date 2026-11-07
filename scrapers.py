import asyncio, re, os
from playwright.async_api import async_playwright

DISPROLIM='https://disprolim.cl/categoria-producto/quimicos_limpieza/'
PURITY='https://purity.cl/todos-los-productos/?resultsPerPage=99999'

def price_clp(text):
    # Chilean formatting: $12.990 / $12.990,00; exclude non-price strings
    s=(text or '').replace('\xa0',' ')
    m=re.search(r'\$\s*([\d.]+)(?:,(\d{1,2}))?',s)
    if not m: return None
    try: return float(m.group(1).replace('.','')+'.'+(m.group(2) or '0'))
    except ValueError: return None

async def collect_disprolim():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--no-sandbox'])
        try:
            page=await browser.new_page(locale='es-CL',viewport={'width':1366,'height':900})
            resp=await page.goto(DISPROLIM,wait_until='domcontentloaded',timeout=60000)
            if resp and resp.status>=400: raise RuntimeError(f'HTTP {resp.status}')
            await page.locator('li.product').first.wait_for(timeout=30000)
            seen={}; stagnant=0
            for i in range(120):
                cards=await page.locator('li.product').evaluate_all('''els=>els.map(el=>({
                  name:(el.querySelector('.woocommerce-loop-product__title,h2')?.textContent||'').trim(),
                  price:(el.querySelector('.price')?.innerText||'').trim(),
                  url:el.querySelector('a.woocommerce-LoopProduct-link,a[href]')?.href||''
                }))''')
                before=len(seen)
                for item in cards:
                    if item['name'] and item['url'] and price_clp(item['price']) is not None:
                        seen[item['url']]={'name':item['name'],'url':item['url'],'price':price_clp(item['price']),'vat_status':'IVA incluido (sitio)'}
                await page.evaluate('window.scrollTo(0,document.body.scrollHeight)')
                await page.wait_for_timeout(2000)
                # Some shops have a separate load-more button
                for sel in ('button.load-more','a.load-more','.load-more-button'):
                    btn=page.locator(sel).first
                    try:
                        if await btn.is_visible(timeout=300):
                            await btn.click(timeout=1500)
                            break
                    except Exception: pass
                stagnant=stagnant+1 if len(seen)==before else 0
                if stagnant>=6: break
            if not seen: raise RuntimeError('No se detectaron productos; revisar selectores o bloqueo')
            return list(seen.values())
        finally: await browser.close()


async def collect_purity():
    url = "https://purity.cl/todos-los-productos/?resultsPerPage=99999"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )

        try:
            page = await browser.new_page(locale="es-CL")

            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            if response and response.status >= 400:
                raise RuntimeError(f"Purity HTTP {response.status}")

            selector = ".js-product-miniature, .product-miniature"

            await page.locator(selector).first.wait_for(
                timeout=30000
            )

            cards = await page.locator(selector).evaluate_all(
                """elements => elements.map(el => {
                    const title = el.querySelector(
                        '.product-title a, h2 a, h3 a'
                    );

                    return {
                        name: (title?.textContent || '').trim(),
                        url: title?.href || '',
                        text: (el.innerText || '').trim()
                    };
                })"""
            )

            productos = {}

            for card in cards:
                name = card["name"]
                product_url = card["url"]

                if not name or not product_url:
                    continue

                precios = re.findall(
                    r"\$\s*[\d.]+(?:,\d{1,2})?",
                    card["text"]
                )

                if not precios:
                    continue

                unitario = price_clp(precios[0])

                if unitario is None or unitario <= 0:
                    continue

                productos[product_url] = {
                    "name": name,
                    "url": product_url,
                    "price": unitario,
                    "vat_status": "IVA por confirmar"
                }

            if len(productos) < 30:
                raise RuntimeError(
                    f"Extraccion Purity incompleta: "
                    f"{len(productos)} productos"
                )

            return list(productos.values())

        finally:
            await browser.close()

# Nuevos proveedores. No se infieren unidades por embalaje.
EGLE_SHOP = 'https://www.grupoegle.cl/shop/'
CRUPLAS_CATALOG = 'https://tienda.cruplas.cl/catalogo'

async def collect_egle():
    """Recorre la tienda y categorías enlazadas. Excluye precios de variantes ambiguas."""
    from urllib.parse import urlparse
    found = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        try:
            page = await browser.new_page(locale='es-CL')
            await page.goto(EGLE_SHOP, wait_until='domcontentloaded', timeout=60000)
            links = await page.locator('a[href]').evaluate_all("""els => els.map(a => ({
                url:a.href, text:(a.innerText||'').trim()
            }))""")
            categories = []
            for item in links:
                u = item['url'].split('#')[0]
                t = item['text'].lower()
                if urlparse(u).netloc not in ('www.grupoegle.cl','grupoegle.cl'):
                    continue
                if any(x in u.lower() for x in ('product-category','categoria-producto')) or any(x in t for x in ('industriales','hogar y retail')):
                    if u not in categories: categories.append(u)
            print(f'Egle: {len(categories)} categorias candidatas', flush=True)
            for base in [EGLE_SHOP] + categories[:35]:
                for number in range(1, 8):
                    u = base.rstrip('/') + ('/' if number == 1 else f'/page/{number}/')
                    try:
                        response = await page.goto(u, wait_until='domcontentloaded', timeout=45000)
                        if response and response.status >= 400: break
                        cards = await page.locator('li.product, .products .product').evaluate_all("""els => els.map(el => ({
                            name:(el.querySelector('.woocommerce-loop-product__title,h2,h3')?.textContent||'').trim(),
                            url:el.querySelector('a[href]')?.href||'',
                            price:(el.querySelector('.price')?.innerText||'').trim(),
                            variable:!!el.querySelector('.product_type_variable'),
                            soldOut:el.classList.contains('outofstock')
                        }))""")
                        before = len(found)
                        for card in cards:
                            prices = re.findall(r'\$\s*[\d.]+(?:,\d{1,2})?',card['price'])
                            if not card['name'] or not card['url'] or not prices or card['variable'] or card['soldOut']:
                                continue
                            if '–' in card['price'] or ' - ' in card['price'] or len(prices)>2:
                                continue
                            value=price_clp(prices[-1])
                            if value and value>0:
                                found[card['url']] = {'name':card['name'],'url':card['url'],
                                    'price':value,'vat_status':'IVA por confirmar (Egle)'}
                        if number>1 and len(found)==before: break
                    except Exception as exc:
                        print(f'Egle: aviso en {u}: {str(exc)[:100]}',flush=True)
                        break
            if not found:
                raise RuntimeError(f'Egle: sin precios simples verificables; categorias candidatas={len(categories)}. Revisar variantes o rutas de categorias')
            return list(found.values())
        finally:
            await browser.close()

async def collect_cruplas():
    """Precio publicado neto por embalaje; no supone unidades por paquete."""
    found = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        try:
            page = await browser.new_page(locale='es-CL')
            last_urls=set()
            for number in range(1,15):
                url = CRUPLAS_CATALOG if number==1 else f'{CRUPLAS_CATALOG}?page={number}'
                response=await page.goto(url,wait_until='domcontentloaded',timeout=60000)
                if response and response.status>=400:
                    if number>1: break
                    raise RuntimeError(f'Cruplas HTTP {response.status}')
                await page.locator('a[href*="/producto/"]').first.wait_for(state='attached',timeout=30000)
                cards=await page.locator('a[href*="/producto/"]').evaluate_all("""els => els.map(a => {
                    let node=a, chosen=a;
                    for(let i=0;i<6&&node;i++,node=node.parentElement){
                        const t=(node.innerText||'').trim();
                        if(t.includes('$')&&t.length<900){chosen=node;break;}
                    }
                    return {url:a.href,text:(chosen.innerText||'').trim()};
                })""")
                urls={c['url'] for c in cards if c['url']}
                if number>1 and urls==last_urls: break
                last_urls=urls
                for card in cards:
                    t=card['text']
                    prices=re.findall(r'\$\s*[\d.]+(?:,\d{1,2})?',t)
                    if not prices: continue
                    price=price_clp(prices[0])
                    if not price or price<=0: continue
                    lines=[x.strip() for x in t.splitlines() if x.strip()]
                    name=next((x for x in lines if any(k in x.lower() for k in ('bolsa ', 'film ', 'stretch ', 'masterbatch ')) and '$' not in x), '')
                    if not name:
                        name=next((x for x in lines if len(x)>9 and not any(k in x.lower() for k in ('sku:', 'disp.', 'iva', '$', 'destacado', 'bolsas transparentes'))), '')
                    if not name or len(name)>180: continue
                    found[card['url']]={'name':name,'url':card['url'],'price':price,
                        'vat_status':'IVA excluido (Cruplas; neto por embalaje)'}
                print(f'Cruplas: pagina {number}, {len(found)} productos acumulados',flush=True)
            if not found:
                raise RuntimeError('Cruplas: enlaces presentes, pero no se pudieron extraer precios y nombres')
            return list(found.values())
        finally:
            await browser.close()
