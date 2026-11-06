import os, asyncio, smtplib
from email.message import EmailMessage
from db import init, save, record_run
from scrapers import collect_disprolim, collect_purity

def notify(changes):
    threshold=float(os.getenv('ALERT_THRESHOLD_PERCENT','5'))
    relevant=[(p,n,a,b,u) for p,n,a,b,u in changes if a and abs((b-a)/a*100)>=threshold]
    if not relevant: return
    if not all(os.getenv(k) for k in ('SMTP_HOST','SMTP_USER','SMTP_PASSWORD','ALERT_EMAIL_TO')):
        print(f'{len(relevant)} alertas detectadas; SMTP no configurado')
        return
    msg=EmailMessage()
    msg['Subject']=f'Monitor de precios: {len(relevant)} variaciones'
    msg['From']=os.getenv('SMTP_FROM',os.getenv('SMTP_USER'))
    msg['To']=os.getenv('ALERT_EMAIL_TO')
    msg.set_content('\n'.join(f'{p} | {n}: ${a:,.0f} -> ${b:,.0f} ({(b-a)/a*100:+.1f}%) | {u}' for p,n,a,b,u in relevant))
    with smtplib.SMTP(os.getenv('SMTP_HOST'),int(os.getenv('SMTP_PORT','587')),timeout=25) as s:
        s.starttls(); s.login(os.getenv('SMTP_USER'),os.getenv('SMTP_PASSWORD')); s.send_message(msg)

async def main():
    init(); changes=[]
    for provider, fn in [('Disprolim',collect_disprolim)]:
        try:
            rows=await fn()
            minimum=int(os.getenv('MIN_DISPROLIM_PRODUCTS','100'))
            if len(rows)<minimum:
                raise RuntimeError(f'Extracción incompleta: {len(rows)} productos; mínimo esperado {minimum}')
            changes.extend(save(provider,rows,'scraping_automatico'))
            record_run(provider,'ok',len(rows))
            print(provider,len(rows),'productos')
        except Exception as exc:
            record_run(provider,'error',0,str(exc))
            print(provider,'ERROR',exc)
    # Purity: no scraping automático hasta validar su estructura.
    notify(changes)
if __name__=='__main__': asyncio.run(main())
