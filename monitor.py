
import os
import asyncio
import smtplib
from email.message import EmailMessage

from db import init, save, record_run, connect, PG
from scrapers import collect_disprolim, collect_purity, collect_egle, collect_cruplas


def diagnosticar_base_datos():
    """Muestra el estado de la base de datos sin revelar credenciales."""

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

            for table in (
                "products",
                "observations",
                "scrape_runs"
            ):
                count = conn.execute(
                    f"SELECT COUNT(*) FROM public.{table}"
                ).fetchone()[0]

                print(
                    f"Registros en {table}: {count}",
                    flush=True
                )

        else:
            print(
                "ADVERTENCIA: Se esta utilizando SQLite.",
                flush=True
            )

    print("=== FIN DEL DIAGNOSTICO ===", flush=True)


def notify(changes):
    """Envia alertas cuando los precios superan el umbral."""

    threshold = float(
        os.getenv("ALERT_THRESHOLD_PERCENT", "5")
    )

    relevant = [
        (provider, name, old, new, url)
        for provider, name, old, new, url in changes
        if old and abs((new - old) / old * 100) >= threshold
    ]

    if not relevant:
        print(
            "No se detectaron variaciones importantes.",
            flush=True
        )
        return

    required = (
        "SMTP_HOST",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "ALERT_EMAIL_TO"
    )

    if not all(os.getenv(key) for key in required):
        print(
            f"{len(relevant)} alertas detectadas; "
            "SMTP no configurado.",
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

    msg.set_content(
        "\n".join(
            (
                f"{provider} | {name}: "
                f"${old:,.0f} -> ${new:,.0f} "
                f"({(new - old) / old * 100:+.1f}%) | {url}"
            )
            for provider, name, old, new, url in relevant
        )
    )

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

    print(
        f"Se enviaron {len(relevant)} alertas.",
        flush=True
    )


async def main():

    print(
        "Iniciando monitor de precios...",
        flush=True
    )

    # Evitar que GitHub Actions guarde datos en SQLite.
    if not PG:
        raise RuntimeError(
            "DATABASE_URL no esta configurada como PostgreSQL. "
            "Se cancela la ejecucion para proteger los datos."
        )

    # Crear las tablas si no existen.
    init()

    # Diagnostico inicial.
    diagnosticar_base_datos()

    changes = []
    errors = []

    # Proveedores activos.
    providers = [
        (
            "Disprolim",
            collect_disprolim,
            int(os.getenv("MIN_DISPROLIM_PRODUCTS", "100"))
        ),
        (
            "Purity",
            collect_purity,
            int(os.getenv("MIN_PURITY_PRODUCTS", "30"))
        ),
        ("Grupo Egle", collect_egle, int(os.getenv("MIN_EGLE_PRODUCTS", "1"))),
        ("Cruplas", collect_cruplas, int(os.getenv("MIN_CRUPLAS_PRODUCTS", "1")))
    ]

    for provider, scraper, minimum in providers:

        print(
            f"Iniciando extraccion de {provider}...",
            flush=True
        )

        try:
            # Obtener productos desde el sitio web.
            rows = await scraper()

            print(
                f"{provider}: {len(rows)} productos encontrados.",
                flush=True
            )

            # Comprobar que la extraccion este completa.
            if len(rows) < minimum:
                raise RuntimeError(
                    f"Extraccion incompleta de {provider}: "
                    f"{len(rows)} productos; "
                    f"minimo esperado {minimum}"
                )

            # Guardar productos y precios en Supabase.
            provider_changes = save(
                provider,
                rows,
                "scraping_automatico"
            )

            changes.extend(provider_changes)

            # Registrar ejecucion exitosa.
            record_run(
                provider,
                "ok",
                len(rows)
            )

            print(
                f"{provider}: {len(rows)} productos guardados.",
                flush=True
            )

        except Exception as exc:

            error_message = str(exc)

            print(
                f"ERROR en {provider}: {error_message}",
                flush=True
            )

            # Registrar el error en Supabase.
            record_run(
                provider,
                "error",
                0,
                error_message
            )

            errors.append(
                f"{provider}: {error_message}"
            )

            # Continuar con el siguiente proveedor.
            continue

    # Enviar alertas si estan configuradas.
    try:
        notify(changes)
    except Exception as exc:
        print(
            f"ERROR enviando alertas: {exc}",
            flush=True
        )
        errors.append(f"Alertas: {exc}")

    # Diagnostico final.
    diagnosticar_base_datos()

    if errors:
        print(
            "La ejecucion termino con errores:",
            flush=True
        )

        for error in errors:
            print(f"- {error}", flush=True)

        # GitHub Actions marcara esta ejecucion como fallida.
        raise RuntimeError(
            "El monitor termino con uno o mas errores."
        )

    print(
        "Monitor finalizado correctamente.",
        flush=True
    )


if __name__ == "__main__":
    asyncio.run(main())
