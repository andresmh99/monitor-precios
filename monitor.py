
import os
import asyncio
import smtplib
from email.message import EmailMessage

from db import init, save, record_run, connect, PG
from scrapers import collect_disprolim, collect_purity


def diagnosticar_base_datos():
    """Muestra el motor y las tablas sin revelar credenciales."""
    print("=== DIAGNOSTICO DE BASE DE DATOS ===", flush=True)
    print(
        "Motor de base de datos:",
        "PostgreSQL" if PG else "SQLite",
        flush=True
    )

    with connect() as conn:
        if PG:
            result = conn.execute("""
                SELECT
                    current_database(),
                    current_schema(),
                    (
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                    )
            """).fetchone()

            print("Base de datos:", result[0], flush=True)
            print("Esquema:", result[1], flush=True)
            print("Tablas publicas:", result[2], flush=True)

            tables = conn.execute("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_name IN (
                    'products',
                    'observations',
                    'scrape_runs',
                    'equivalences'
                )
                ORDER BY table_schema, table_name
            """).fetchall()

            print("Tablas del monitor:", tables, flush=True)

            for table in ("products", "observations", "scrape_runs"):
                count = conn.execute(
                    f"SELECT COUNT(*) FROM public.{table}"
                ).fetchone()[0]

                print(f"Registros en {table}: {count}", flush=True)

        else:
            print(
                "ADVERTENCIA: Se esta utilizando SQLite.",
                flush=True
            )

    print("=== FIN DEL DIAGNOSTICO ===", flush=True)


def notify(changes):
    threshold = float(
        os.getenv("ALERT_THRESHOLD_PERCENT", "5")
    )

    relevant = [
        (p, n, a, b, u)
        for p, n, a, b, u in changes
        if a and abs((b - a) / a * 100) >= threshold
    ]

    if not relevant:
        return

    required = (
        "SMTP_HOST",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "ALERT_EMAIL_TO"
    )

    if not all(os.getenv(k) for k in required):
        print(
            f"{len(relevant)} alertas detectadas; "
            "SMTP no configurado",
            flush=True
        )
        return

    msg = EmailMessage()
    msg["Subject"] = (
        f"Monitor de precios: {len(relevant)} variaciones"
    )
    msg["From"] = os.getenv(
        "SMTP_FROM",
        os.getenv("SMTP_USER")
    )
    msg["To"] = os.getenv("ALERT_EMAIL_TO")

    msg.set_content("\n".join(
        (
            f"{p} | {n}: "
            f"${a:,.0f} -> ${b:,.0f} "
            f"({(b-a)/a*100:+.1f}%) | {u}"
        )
        for p, n, a, b, u in relevant
    ))

    with smtplib.SMTP(
        os.getenv("SMTP_HOST"),
        int(os.getenv("SMTP_PORT", "587")),
        timeout=25
    ) as smtp:
        smtp.starttls()
        smtp.login(
            os.getenv("SMTP_USER"),
            os.getenv("SMTP_PASSWORD")
        )
        smtp.send_message(msg)


async def main():
    print("Iniciando monitor de precios...", flush=True)

    # Crear tablas si no existen
    init()

    # Diagnosticar la conexion despues de crear las tablas
    diagnosticar_base_datos()

    changes = []

    # Extraccion automatica de Disprolim
    for provider, fn in [
        ("Disprolim", collect_disprolim)
    ]:
        try:
            rows = await fn()

            minimum = int(
                os.getenv("MIN_DISPROLIM_PRODUCTS", "100")
            )

            if len(rows) < minimum:
                raise RuntimeError(
                    f"Extraccion incompleta: {len(rows)} "
                    f"productos; minimo esperado {minimum}"
                )

            changes.extend(
                save(
                    provider,
                    rows,
                    "scraping_automatico"
                )
            )

            record_run(
                provider,
                "ok",
                len(rows)
            )

            print(
                provider,
                len(rows),
                "productos",
                flush=True
            )

        except Exception as exc:
            record_run(
                provider,
                "error",
                0,
                str(exc)
            )

            print(
                provider,
                "ERROR",
                exc,
                flush=True
            )

            # Marcar como fallida la ejecucion en GitHub
            raise

    # Purity: scraping automatico pendiente
    # hasta validar su estructura.

    notify(changes)

    # Verificar registros despues de la extraccion
    diagnosticar_base_datos()

    print("Monitor finalizado correctamente.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

