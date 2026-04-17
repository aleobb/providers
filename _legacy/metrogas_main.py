#!/usr/bin/env python3
"""
Descargador de facturas Metrogas.

Uso:
    python metrogas_main.py [--debug] [--cuenta N] [--listar] [--todas]

Variables de entorno requeridas (o en archivo .env):
    METROGAS_EMAIL       Email de la cuenta
    METROGAS_PASSWORD    Contraseña de la cuenta

Variables opcionales:
    METROGAS_OUTPUT_DIR  Directorio de destino (default: ./facturas)
    METROGAS_HEADLESS    true/false (default: true)
    METROGAS_TIMEOUT_MS  Timeout en ms (default: 30000)
"""

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from metrogas_downloader.accounts import fetch_accounts, select_account
from metrogas_downloader.browser import BrowserSession
from metrogas_downloader.config import Config
from metrogas_downloader.exceptions import (
    DownloadError,
    InvoiceNotFoundError,
    LoginError,
    MetrogasError,
)
from metrogas_downloader.invoice import InvoiceService
from metrogas_downloader.login import LoginOrchestrator


def _parse_args() -> dict:
    args = sys.argv[1:]
    result = {"debug": False, "listar": False, "todas": False, "cuenta": None}
    i = 0
    while i < len(args):
        if args[i] == "--debug":
            result["debug"] = True
        elif args[i] == "--listar":
            result["listar"] = True
        elif args[i] == "--todas":
            result["todas"] = True
        elif args[i] == "--cuenta" and i + 1 < len(args):
            result["cuenta"] = args[i + 1]
            i += 1
        i += 1
    return result


async def download_one(service, account):
    try:
        path = await service.download_for_client(account.client_number)
        return path, None
    except MetrogasError as e:
        return None, e


async def run(debug: bool, listar: bool, todas: bool, cuenta: str | None) -> None:
    config = Config()

    if debug:
        config.headless = False
        print("[DEBUG] Modo headless desactivado — el browser será visible.")

    print(f"Iniciando sesión como {config.email} ...")

    async with BrowserSession(config) as session:
        login = LoginOrchestrator(session.page, config)
        await login.execute()
        print("Login exitoso.")
        await asyncio.sleep(3)

        accounts = await fetch_accounts(session.page, config)
        if not accounts:
            raise InvoiceNotFoundError("No se encontraron cuentas asociadas al usuario.")

        # --listar
        if listar:
            print(f"\n{len(accounts)} cuenta(s) de servicio:\n")
            for i, acc in enumerate(accounts, 1):
                print(acc.display(i))
            print()
            return

        service = InvoiceService(session.page, config)

        # --todas
        if todas:
            print(f"\nDescargando facturas de {len(accounts)} cuenta(s)...\n")
            results = []
            for i, account in enumerate(accounts, 1):
                label = f"[{i}/{len(accounts)}] N° {account.client_number} — {account.titular}"
                print(f"{label} — descargando...")
                path, err = await download_one(service, account)
                if path:
                    print(f"  OK: {path.resolve()}")
                    results.append((account, path, None))
                else:
                    print(f"  ERROR: {err}", file=sys.stderr)
                    results.append((account, None, err))

            print(f"\nResumen:")
            ok = [r for r in results if r[1]]
            fail = [r for r in results if r[2]]
            for acc, path, _ in ok:
                print(f"  OK   N° {acc.client_number}: {path.name}")
            for acc, _, err in fail:
                print(f"  FAIL N° {acc.client_number}: {err}", file=sys.stderr)

            if fail and not ok:
                sys.exit(1)
            return

        # Single account
        account = select_account(accounts, cuenta)
        if len(accounts) > 1:
            print(f"\nCuenta seleccionada: N° {account.client_number} — {account.titular}")

        print("Descargando última factura...")
        pdf_path = await service.download_for_client(account.client_number)

    print(f"\nFactura descargada: {pdf_path.resolve()}")


def main() -> None:
    args = _parse_args()

    try:
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run(**args))
            loop.close()
        else:
            asyncio.run(run(**args))
    except LoginError as e:
        print(f"\nERROR de login: {e}", file=sys.stderr)
        print("Verificar METROGAS_EMAIL y METROGAS_PASSWORD en el archivo .env", file=sys.stderr)
        sys.exit(1)
    except InvoiceNotFoundError as e:
        print(f"\nNo se encontraron facturas: {e}", file=sys.stderr)
        sys.exit(1)
    except MetrogasError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"\nError inesperado: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
