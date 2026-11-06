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
    # Deliberately fail closed: site-specific parser not yet validated.
    # Prevents silently inventing updates or confusing retail and case prices.
    raise NotImplementedError('Extractor de Purity pendiente de validar: usar importación inicial y configurar selectores antes de activarlo.')
