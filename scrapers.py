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
    """Consulta categorías WooCommerce reales; solo guarda precios únicos verificables."""
    bases = [
        'https://www.grupoegle.cl/categoria-producto/hogar-y-retail/',
        'https://www.grupoegle.cl/categoria-producto/detergentes-industriales/',
    ]
    found = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        try:
            page = await browser.new_page(locale='es-CL')
            for base in bases:
                for number in range(1, 16):
                    url = base if number == 1 else base.rstrip('/') + f'/page/{number}/'
                    try:
                        response = await page.goto(url, wait_until='domcontentloaded', timeout=45000)
                        if response and response.status >= 400:
                            break
                        await page.wait_for_timeout(1200)
                        cards = await page.locator('li.product, .products .product').evaluate_all("""els => els.map(el => {
                            const a=el.querySelector('a.woocommerce-LoopProduct-link, a[href]');
                            const name=el.querySelector('.woocommerce-loop-product__title, h2, h3');
                            const price=el.querySelector('.price');
                            return {name:(name?.textContent||'').trim(),url:a?.href||'',
                              price:(price?.innerText||price?.textContent||'').trim(),
                              variable:!!el.querySelector('.product_type_variable')};
                        })""")
                        print(f'Egle: {url} -> {len(cards)} tarjetas', flush=True)
                        if not cards:
                            break
                        urls_before = set(found)
                        for card in cards:
                            if not card['name'] or not card['url'] or card['variable']:
                                continue
                            matches = re.findall(r'\$\s*[\d.]+(?:,\d{1,2})?', card['price'])
                            if not matches:
                                continue
                            # Rangos o precios ambiguos se excluyen; no asignar un costo ficticio.
                            if len(matches) > 2 or '–' in card['price'] or ' - ' in card['price']:
                                continue
                            price = price_clp(matches[-1])
                            if price and price > 0:
                                found[card['url']] = {'name':card['name'], 'url':card['url'],
                                    'price':price, 'vat_status':'IVA por confirmar (Egle)'}
                        if number > 1 and set(found) == urls_before:
                            break
                    except Exception as exc:
                        print(f'Egle: aviso en {url}: {str(exc)[:160]}', flush=True)
                        break
            if not found:
                raise RuntimeError('Egle: categorías reales consultadas, pero sin precios simples verificables; revisar fichas de variantes')
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
                try:
                    await page.locator('a[href*="/producto/"]').first.wait_for(state='attached', timeout=12000)
                except Exception:
                    if number > 1 and found:
                        print(f'Cruplas: fin de paginacion en pagina {number}', flush=True)
                        break
                    raise RuntimeError(f'Cruplas: sin tarjetas de productos en {url}')
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
