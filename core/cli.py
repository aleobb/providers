from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .accounts import select_account
from .browser import BrowserSession
from .exceptions import (
    CaptchaError,
    InvoiceDownloaderError,
    InvoiceNotFoundError,
    LoginError,
    ServerUnavailableError,
)
from .provider import Provider
from .registry import all_provider_names, all_providers, get_provider
from .utils import dismiss_popups
from . import run_log


def parse_args() -> dict:
    args = sys.argv[1:]
    result = {
        "debug": False,
        "listar": False,
        "todas": False,
        "cuenta": None,
        "proveedor": None,
        "todos_proveedores": False,
    }
    i = 0
    while i < len(args):
        if args[i] == "--debug":
            result["debug"] = True
        elif args[i] == "--listar":
            result["listar"] = True
        elif args[i] == "--todas":
            result["todas"] = True
        elif args[i] in ("--proveedor", "-p") and i + 1 < len(args):
            result["proveedor"] = args[i + 1].lower()
            i += 1
        elif args[i] == "--cuenta" and i + 1 < len(args):
            result["cuenta"] = args[i + 1]
            i += 1
        elif args[i] == "--todos-proveedores":
            result["todos_proveedores"] = True
        i += 1
    return result


async def _download_one(provider: Provider, page, context, account):
    """Download one invoice, returning (path, error)."""
    try:
        path = await provider.download_invoice(page, context, account)
        return path, None
    except InvoiceDownloaderError as e:
        return None, e


async def run_provider(
    provider: Provider,
    debug: bool,
    listar: bool,
    todas: bool,
    cuenta: str | None,
) -> bool:
    """Run a single provider. Returns True on full success."""
    config = provider.get_config()
    if debug:
        config.headless = False

    print(f"\n{'='*50}")
    print(f"  {provider.display_name}")
    print(f"{'='*50}")
    print(f"Iniciando sesion como {config.email} ...")

    async with BrowserSession(config) as session:
      try:
        await provider.login(session.page, session.context)
        print("Login exitoso.")
        await asyncio.sleep(2)

        # Cerrar cualquier popup/modal que haya aparecido post-login (hasta 3 rondas)
        for _ in range(3):
            closed = await dismiss_popups(session.page, label=provider.name)
            if not closed:
                break
            await asyncio.sleep(0.5)

        accounts = await provider.fetch_accounts(session.page, session.context)
        if not accounts:
            raise InvoiceNotFoundError("No se encontraron cuentas asociadas al usuario.")

        # --listar
        if listar:
            print(f"\n{len(accounts)} cuenta(s):\n")
            for i, acc in enumerate(accounts, 1):
                print(acc.display(i))
            print()
            return True

        service_page = session.page
        service_context = session.context

        # --todas
        if todas:
            print(f"\nDescargando facturas de {len(accounts)} cuenta(s)...\n")
            results = []
            for i, account in enumerate(accounts, 1):
                label = f"[{i}/{len(accounts)}] N {account.client_number} - {account.display_name}"
                print(f"{label} - descargando...")
                path, err = await _download_one(provider, service_page, service_context, account)
                if path:
                    print(f"  OK: {path.resolve()}")
                    period = _extract_period(path)
                    run_log.log_ok(provider.name, account.client_number, period, path)
                    results.append((account, path, None))
                else:
                    print(f"  ERROR: {err}", file=sys.stderr)
                    run_log.log_error(provider.name, account.client_number, str(err))
                    results.append((account, None, err))

            ok = [r for r in results if r[1]]
            fail = [r for r in results if r[2]]
            print(f"\nResumen {provider.display_name}:")
            for acc, path, _ in ok:
                print(f"  OK   N {acc.client_number}: {path.name}")
            for acc, _, err in fail:
                print(f"  FAIL N {acc.client_number}: {err}", file=sys.stderr)
            return len(fail) == 0

        # Single account
        account = select_account(accounts, cuenta)
        if len(accounts) > 1:
            print(f"\nCuenta seleccionada: N {account.client_number} - {account.display_name}")

        print("Descargando ultima factura...")
        pdf_path = await provider.download_invoice(service_page, service_context, account)
        print(f"\nFactura descargada: {pdf_path.resolve()}")
        period = _extract_period(pdf_path)
        run_log.log_ok(provider.name, account.client_number, period, pdf_path)
        return True

      finally:
        # Cerrar sesion antes de que el browser se cierre (evita conflictos en la proxima ejecucion)
        try:
            logout_fn = getattr(provider, "logout", None)
            if callable(logout_fn):
                await logout_fn(session.page, session.context)
        except Exception as e:
            print(f"  [logout] {provider.name}: {e}", file=sys.stderr)


def _extract_period(path: Path) -> str:
    """Extrae el período (YYYY-MM) del nombre del archivo si está presente."""
    import re
    m = re.search(r"(\d{4}-\d{2})", path.name)
    return m.group(1) if m else "-"


async def run(
    debug: bool,
    listar: bool,
    todas: bool,
    cuenta: str | None,
    proveedor: str | None,
    todos_proveedores: bool,
) -> None:
    if todos_proveedores:
        providers = all_providers()
        if not providers:
            print("No hay proveedores registrados.", file=sys.stderr)
            sys.exit(1)
        print(f"Ejecutando {len(providers)} proveedor(es): {', '.join(p.display_name for p in providers)}")
    elif proveedor:
        providers = [get_provider(proveedor)]
    else:
        names = all_provider_names()
        if len(names) == 1:
            providers = [get_provider(names[0])]
        else:
            print(
                f"Especificar proveedor con --proveedor <nombre> o usar --todos-proveedores.\n"
                f"Disponibles: {', '.join(names)}",
                file=sys.stderr,
            )
            sys.exit(1)

    if debug:
        print("[DEBUG] Modo headless desactivado - el browser sera visible.")

    if not listar:
        run_log.log_run_start([p.name for p in providers])

    all_ok = True
    for provider in providers:
        try:
            ok = await run_provider(provider, debug, listar, todas, cuenta)
            if not ok:
                all_ok = False
        except ServerUnavailableError as e:
            msg = str(e)
            print(f"\n  [{provider.display_name}] Servidor no disponible: {msg}", file=sys.stderr)
            print(f"  Se continua con el siguiente proveedor.", file=sys.stderr)
            run_log.log_server_down(provider.name, msg)
            all_ok = False
        except InvoiceDownloaderError as e:
            print(f"\nERROR [{provider.display_name}]: {e}", file=sys.stderr)
            run_log.log_error(provider.name, None, str(e))
            all_ok = False

    if not all_ok:
        sys.exit(1)


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    # Import providers to trigger registration
    import providers  # noqa: F401

    args = parse_args()

    try:
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run(**args))
            loop.close()
        else:
            asyncio.run(run(**args))
    except CaptchaError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        print("Sugerencia: ejecutar con --debug para resolver el captcha manualmente.", file=sys.stderr)
        sys.exit(1)
    except LoginError as e:
        print(f"\nERROR de login: {e}", file=sys.stderr)
        sys.exit(1)
    except InvoiceDownloaderError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"\nError inesperado: {e}", file=sys.stderr)
        sys.exit(1)
