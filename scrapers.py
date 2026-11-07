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

# NUEVOS PROVEEDORES. Se excluyen productos sin precio inequívoco.
EGLE_SHOP = 'https://www.grupoegle.cl/shop/'
CRUPLAS_CATALOG = 'https://tienda.cruplas.cl/catalogo'

async def collect_egle():
    """WooCommerce: solo artículos simples con precio inequívoco; no confundir
    el precio 'desde' de productos variables con un SKU comprable."""
    from urllib.parse import urljoin
    found = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        try:
            page = await browser.new_page(locale='es-CL')
            for number in range(1, 51):
                url = EGLE_SHOP if number == 1 else urljoin(EGLE_SHOP, f'page/{number}/')
                response = await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                if response and response.status == 404:
                    break
                if response and response.status >= 400:
                    raise RuntimeError(f'Egle HTTP {response.status} en {url}')
                cards = await page.locator('li.product').evaluate_all('''els => els.map(el => {
                    const a = el.querySelector('a.woocommerce-LoopProduct-link, a.woocommerce-loop-product__link, a[href*="/producto/"]');
                    const title = el.querySelector('.woocommerce-loop-product__title, h2');
                    const price = el.querySelector('.price');
                    const variable = !!el.querySelector('a.product_type_variable, a[href*="attribute_"]');
                    const soldOut = !!el.querySelector('.outofstock');
                    return {name: title?.textContent?.trim() || '', url: a?.href || '',
                        price: price?.innerText || '', variable, soldOut};
                })''')
                if not cards:
                    if number == 1:
                        raise RuntimeError('Egle: no se encontraron tarjetas WooCommerce')
                    break
                before = len(found)
                for card in cards:
                    if card['variable'] or card['soldOut'] or not card['name'] or not card['url']:
                        continue
                    # El precio de oferta es el último precio visible (precio anterior tachado primero).
                    values = re.findall(r'\$\s*[\d.]+(?:,\d{1,2})?', card['price'])
                    if not values:
                        continue
                    price = price_clp(values[-1])
                    if price and price > 0:
                        found[card['url']] = dict(name=card['name'], url=card['url'],
                            price=price, vat_status='IVA por confirmar (Egle)')
                if number > 1 and len(found) == before:
                    # Una página repetida puede significar que el sitio redirige páginas inexistentes.
                    break
            if not found:
                raise RuntimeError('Egle: no se encontraron productos simples con precio')
            return list(found.values())
        finally:
            await browser.close()

async def collect_cruplas():
    """Cruplas: precio publicado neto por embalaje. No dividir por unidades sin
    leer el detalle específico de cada producto."""
    from urllib.parse import urljoin
    found = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        try:
            page = await browser.new_page(locale='es-CL')
            for number in range(1, 11):
                url = CRUPLAS_CATALOG if number == 1 else f'{CRUPLAS_CATALOG}?page={number}'
                response = await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                if response and response.status >= 400:
                    if number > 1 and response.status == 404:
                        break
                    raise RuntimeError(f'Cruplas HTTP {response.status}')
                await page.locator('a[href*="/producto/"]').first.wait_for(timeout=20000)
                cards = await page.locator('a[href*="/producto/"]').evaluate_all('''els => els.map(a => ({
                    name: (a.querySelector('h2,h3,h4')?.innerText || '').trim(),
                    url: a.href, text: (a.innerText || '').trim()
                }))''')
                before = len(found)
                for card in cards:
                    if not card['url'] or 'cotización' in card['text'].lower() or 'agotado' in card['text'].lower():
                        continue
                    price = price_clp(card['text'])
                    if not price or price <= 0:
                        continue
                    # Enlaces a veces incluyen imagen y texto, sin h3; recuperamos título desde la página.
                    name = card['name'] or card['text'].split('SKU:')[0].split('SKU :')[0].strip()
                    name = re.sub(r'^(Destacado|Bolsas de Basura Planas|Bolsas Transparentes)\s+', '', name, flags=re.I)
                    if not name or len(name) > 180:
                        continue
                    found[card['url']] = dict(name=name, url=card['url'], price=price,
                        vat_status='IVA excluido (Cruplas; precio neto por embalaje)')
                if number > 1 and len(found) == before:
                    break
            if not found:
                raise RuntimeError('Cruplas: no se detectaron productos con precio; revisar selectores')
            return list(found.values())
        finally:
            await browser.close()
