# Monitor de precios — Purity / Disprolim

Proyecto inicial de monitoreo con historial, dashboard y alertas. **No está desplegado ni ejecutándose todavía.**

## Arquitectura
- **Streamlit Community Cloud**: interfaz pública o privada según configuración.
- **PostgreSQL administrado** (por ejemplo Supabase/Neon): almacenamiento persistente compartido entre dashboard y scraping.
- **GitHub Actions**: ejecución diaria del scraper en la nube (programación aproximada, no SLA 24/7).
- **SMTP**: alertas por correo cuando cambia el precio >= 5% respecto de la captura anterior.

## Puesta en marcha
1. Crea un repositorio GitHub **privado** y sube esta carpeta. Los Excel de `data/` contienen el catálogo proporcionado por el usuario.
2. Crea una base PostgreSQL administrada y copia su URL de conexión segura (con SSL).
3. En el repositorio, configura `Settings > Secrets and variables > Actions` con `DATABASE_URL`. Añade opcionalmente `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO`.
4. En tu Mac: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.
5. Configura la variable `DATABASE_URL` localmente (no la subas al repositorio). Ejecuta **una sola vez** `python seed.py` para cargar la línea base.
6. Publica el repositorio en Streamlit Community Cloud, archivo principal `app.py`, y configura allí `DATABASE_URL` como secreto/variable de entorno. Para Streamlit Cloud, puede requerirse agregar en Secrets `DATABASE_URL = "..."`.
7. En GitHub, abre `Actions > Monitor diario de precios > Run workflow` para probar el scraper. Luego corre diariamente según el cron UTC.
8. Ejecuta `streamlit run app.py` para probar localmente.

## Estado real / limitaciones
- **Disprolim**: extractor de categoría con scroll infinito. Debe probarse en GitHub Actions; puede fallar por protección anti-bot o por cambios de HTML. Si devuelve menos de 100 productos, se considera extracción incompleta y no se guarda.
- **Purity**: importación inicial de 36 productos; scraper automático **no implementado** hasta verificar selectores y formatos. Por tanto todavía NO se monitorea Purity automáticamente.
- **Comparación**: no se automatiza el cruce entre productos de distinto formato; hay que confirmar equivalencias, contenido e IVA antes de concluir ahorro.
- **Historial**: los Excel importados representan un punto inicial, no fechas históricas inventadas.
- **Alertas**: solo cambios observados desde la captura previa; el primer registro no dispara alertas. Las credenciales SMTP son necesarias.
- **Frecuencia**: GitHub Actions schedule puede retrasarse. No es un servicio de vigilancia continua con garantía de ejecución. El dashboard solo refleja el último dato almacenado.
- **Acceso**: si el repositorio contiene datos sensibles, no publiques los Excel en un repositorio público; usa acceso privado.
- **Seguridad**: no guardes credenciales en código. Revisa robots.txt, términos del sitio y límites de solicitudes antes de automatizar.

## Mejoras siguientes
Confirmar equivalencias con SKU/volumen/unidades, incorporar precio normalizado, scraper Purity, monitor de fallos con alerta, comparar contra hace 7/30/90 días y alertas por diferencias entre proveedores.
