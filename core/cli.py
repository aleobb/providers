from __future__ import annotations

import asyncio
import os
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
    drive_uploader=None,
    drive_root_id: str = "",
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
                    period = _determine_period(path, provider.name)
                    run_log.log_ok(provider.name, account.client_number, period, path)
                    if drive_uploader and drive_root_id:
                        banco = account.extra.get("banco", "") if account.extra else ""
                        _upload_to_drive(drive_uploader, drive_root_id, provider.name, period, path, banco)
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
        period = _determine_period(pdf_path, provider.name)
        run_log.log_ok(provider.name, account.client_number, period, pdf_path)
        if drive_uploader and drive_root_id:
            banco = account.extra.get("banco", "") if account.extra else ""
            _upload_to_drive(drive_uploader, drive_root_id, provider.name, period, pdf_path, banco)
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
    """Extrae el período del nombre del archivo. Devuelve YYYY-MM-DD o YYYY-MM."""
    import re
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    if m:
        return m.group(1)
    m = re.search(r"(\d{4}-\d{2})", path.name)
    return m.group(1) if m else "-"


def _determine_period(path: Path, provider_name: str) -> str:
    """
    Determina el período del documento intentando leer el PDF con pdfplumber.

    - Éxito  → YYYY-MM-DD extraído del contenido del PDF.
    - Fallo  → período del nombre del archivo + '_pdf_read_error'
               (señal visible en el nombre del archivo en Drive).
    """
    try:
        from .pdf_extractor import extract_invoice_date
        date = extract_invoice_date(path, provider_name)
        if date:
            return date
    except Exception:
        pass

    # Fallback: nombre de archivo + marcador de error
    period = _extract_period(path)
    if period == "-":
        return "sin_fecha_pdf_read_error"
    return f"{period}_pdf_read_error"


def _upload_to_drive(
    uploader,
    root_folder_id: str,
    provider_name: str,
    period: str,
    path: Path,
    banco: str = "",
) -> None:
    """Sube el PDF a Drive. Silencia errores para no interrumpir el flujo principal."""
    try:
        from .drive_naming import get_drive_target
        target = get_drive_target(provider_name, period, banco=banco)
        file_id = uploader.upload_to_path(
            path, root_folder_id, target.subfolder_parts, target.filename
        )
        drive_path = "/".join(target.subfolder_parts + [target.filename])
        if file_id:
            print(f"  Drive: {drive_path} ✓")
        else:
            print(f"  Drive: {drive_path} (ya existía)")
    except Exception as e:
        print(f"  [Drive] Error al subir {path.name}: {e}", file=sys.stderr)


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

    # Inicializar Google Drive uploader si las credenciales están configuradas
    drive_uploader = None
    drive_root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    if drive_root_id and os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        try:
            from .drive import DriveUploader
            drive_uploader = DriveUploader()
            print(f"[Drive] Uploader iniciado. Carpeta raíz: {drive_root_id}")
        except Exception as e:
            print(f"[Drive] No se pudo inicializar el uploader: {e}", file=sys.stderr)
            drive_uploader = None

    if not listar:
        run_log.log_run_start([p.name for p in providers])

    all_ok = True
    for provider in providers:
        try:
            ok = await run_provider(
                provider, debug, listar, todas, cuenta,
                drive_uploader=drive_uploader,
                drive_root_id=drive_root_id,
            )
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
