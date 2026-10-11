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
from .credential_cli import manage_credentials
from .credential_store import (
    CredentialStore,
    CredentialStoreError,
)
from .provider import Provider
from .registry import all_provider_names, all_providers, get_provider
from .utils import dismiss_popups
from . import run_log
from integrations.pdf_extractor import determine_invoice_period


def parse_args() -> dict:
    args = sys.argv[1:]
    result = {
        "debug": False,
        "listar": False,
        "todas": False,
        "nosession": False,
        "cuenta": None,
        "proveedor": None,
        "todos_proveedores": False,
        "url": None,
        "gestionar_credenciales": False,
    }
    i = 0
    while i < len(args):
        if args[i] == "--debug":
            result["debug"] = True
        elif args[i] == "--listar":
            result["listar"] = True
        elif args[i] == "--todas":
            result["todas"] = True
        elif args[i] == "--nosession":
            result["nosession"] = True
        elif args[i] in ("--proveedor", "-p") and i + 1 < len(args):
            result["proveedor"] = args[i + 1].lower()
            i += 1
        elif args[i] == "--cuenta" and i + 1 < len(args):
            result["cuenta"] = args[i + 1]
            i += 1
        elif args[i] == "--todos-proveedores":
            result["todos_proveedores"] = True
        elif args[i] == "--gestionar-credenciales":
            result["gestionar_credenciales"] = True
        elif args[i] == "--url" and i + 1 < len(args):
            result["url"] = args[i + 1]
            i += 1
        i += 1
    return result


async def _download_one(provider: Provider, page, context, account):
    """Download one invoice, returning (path, error)."""
    try:
        path = await provider.download_invoice(page, context, account)
        return path, None
    except InvoiceDownloaderError as e:
        return None, e


async def _run_provider_no_browser(
    provider: Provider,
    accounts: list,
    todas: bool,
    cuenta: str | None,
    drive_uploader,
    drive_root_id: str,
) -> bool:
    """
    Descarga facturas usando sesión guardada — sin abrir el browser.
    Devuelve True si todo fue OK; False si alguna descarga falló.
    """
    from core import session_store

    if todas:
        print(f"\nDescargando facturas de {len(accounts)} cuenta(s) (sin browser)...\n")
        results = []
        for i, account in enumerate(accounts, 1):
            label = f"[{i}/{len(accounts)}] N {account.client_number} - {account.display_name}"
            print(f"{label} - descargando...")
            try:
                path = await provider.download_invoice(None, None, account)
                print(f"  OK: {path.resolve()}")
                period = determine_invoice_period(path, provider.extract_invoice_date)
                run_log.log_ok(provider.name, account.client_number, period, path)
                if drive_uploader and drive_root_id:
                    banco = account.extra.get("banco", "") if account.extra else ""
                    from integrations.drive import upload_invoice_to_drive
                    upload_invoice_to_drive(
                        drive_uploader, drive_root_id, provider, period, path, banco
                    )
                results.append((account, path, None))
            except Exception as e:
                print(f"  ERROR: {e}", file=sys.stderr)
                run_log.log_error(provider.name, account.client_number, str(e))
                results.append((account, None, e))
                if provider.is_session_error(e):
                    session_store.clear(provider.session_key)
                    print(
                        f"  [Session] Sesión invalidada — el próximo run hará login.",
                        file=sys.stderr,
                    )

        ok = [r for r in results if r[1]]
        fail = [r for r in results if r[2]]
        print(f"\nResumen {provider.display_name}:")
        for acc, path, _ in ok:
            print(f"  OK   N {acc.client_number}: {path.name}")
        for acc, _, err in fail:
            print(f"  FAIL N {acc.client_number}: {err}", file=sys.stderr)
        return len(fail) == 0

    account = select_account(accounts, cuenta)
    if len(accounts) > 1:
        print(f"\nCuenta seleccionada: N {account.client_number} - {account.display_name}")

    print("Descargando ultima factura (sin browser)...")
    try:
        pdf_path = await provider.download_invoice(None, None, account)
    except Exception as e:
        if provider.is_session_error(e):
            session_store.clear(provider.session_key)
        raise
    print(f"\nFactura descargada: {pdf_path.resolve()}")
    period = determine_invoice_period(pdf_path, provider.extract_invoice_date)
    run_log.log_ok(provider.name, account.client_number, period, pdf_path)
    if drive_uploader and drive_root_id:
        banco = account.extra.get("banco", "") if account.extra else ""
        from integrations.drive import upload_invoice_to_drive
        upload_invoice_to_drive(
            drive_uploader, drive_root_id, provider, period, pdf_path, banco
        )
    return True


async def run_provider(
    provider: Provider,
    debug: bool,
    listar: bool,
    todas: bool,
    cuenta: str | None,
    url: str | None = None,
    drive_uploader=None,
    drive_root_id: str = "",
    nosession: bool = False,
    credential_store: CredentialStore | None = None,
) -> bool:
    """Run a single provider. Returns True on full success."""
    from core import session_store

    config = provider.get_config()
    if provider.requires_credentials:
        credential_store = credential_store or CredentialStore()
        profile = credential_store.request_credentials(provider.name)
        provider.configure_credentials(
            profile,
            len(credential_store.list_profiles(provider.name)),
            Path(__file__).resolve().parents[1] / ".sessions",
        )
    credential_alias = provider.credential_alias
    provider_session_key = provider.session_key
    if debug:
        config.headless = False
    provider.apply_run_options(url=url)

    print(f"\n{'='*50}")
    print(f"  {provider.display_name}")
    print(f"{'='*50}")

    # ─── Intento session-first (sin browser) ─────────────────────────────────
    if nosession:
        print("[Session] Ignorando la sesión guardada; se usará un perfil temporal limpio.")
    elif not listar and provider.can_resume_session:
        saved = session_store.load(provider_session_key)
        if saved:
            print("Sesión guardada encontrada — verificando...")
            try:
                accounts = await provider.try_resume_session(saved)
                if accounts is not None:
                    run_log.log_run_start([provider.name])
                    return await _run_provider_no_browser(
                        provider, accounts, todas, cuenta, drive_uploader, drive_root_id
                    )
                else:
                    print("Sesión expirada. Haciendo login con browser...")
                    session_store.clear(provider_session_key)
            except Exception as e:
                print(f"  Error restaurando sesión: {e}. Haciendo login con browser...")
                session_store.clear(provider_session_key)

    # ─── Path con browser (flujo original) ───────────────────────────────────
    if credential_alias:
        print(f"Iniciando sesión con el perfil «{credential_alias}»...")
    else:
        print(f"Iniciando sesion como {config.email} ...")

    async with BrowserSession(
        config, profile_name=provider_session_key, fresh_profile=nosession
    ) as session:
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

        # Guardar sesión para la próxima ejecución (evita login al browser)
        if not nosession:
            try:
                await provider.save_session(session.page, session.context, accounts)
            except Exception as _se:
                print(f"  [Session] No se pudo guardar: {_se}", file=sys.stderr)

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
                    period = determine_invoice_period(path, provider.extract_invoice_date)
                    run_log.log_ok(provider.name, account.client_number, period, path)
                    if drive_uploader and drive_root_id:
                        banco = account.extra.get("banco", "") if account.extra else ""
                        from integrations.drive import upload_invoice_to_drive
                        upload_invoice_to_drive(
                            drive_uploader, drive_root_id, provider, period, path, banco
                        )
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
        period = determine_invoice_period(pdf_path, provider.extract_invoice_date)
        run_log.log_ok(provider.name, account.client_number, period, pdf_path)
        if drive_uploader and drive_root_id:
            banco = account.extra.get("banco", "") if account.extra else ""
            from integrations.drive import upload_invoice_to_drive
            upload_invoice_to_drive(
                drive_uploader, drive_root_id, provider, period, pdf_path, banco
            )
        return True

      finally:
        # Cerrar sesion antes de que el browser se cierre (evita conflictos en la proxima ejecucion)
        try:
            await provider.logout(session.page, session.context)
        except Exception as e:
            print(f"  [logout] {provider.name}: {e}", file=sys.stderr)


async def run(
    debug: bool,
    listar: bool,
    todas: bool,
    cuenta: str | None,
    proveedor: str | None,
    todos_proveedores: bool,
    url: str | None = None,
    nosession: bool = False,
    credential_store: CredentialStore | None = None,
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
            from integrations.drive import DriveUploader
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
                url=url,
                drive_uploader=drive_uploader,
                drive_root_id=drive_root_id,
                nosession=nosession,
                credential_store=credential_store,
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
        except CredentialStoreError as e:
            print(f"\nERROR [{provider.display_name}]: {e}", file=sys.stderr)
            all_ok = False

    if not all_ok:
        sys.exit(1)


def main() -> None:
    from dotenv import load_dotenv

    try:
        credential_store = CredentialStore()
        imported = credential_store.import_legacy_dotenv_once(
            Path(__file__).resolve().parents[1] / ".env"
        )
    except CredentialStoreError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    if imported:
        print(f"[Credenciales] Se importaron {imported} perfil(es) desde .env.")

    load_dotenv()
    args = parse_args()
    if args.pop("gestionar_credenciales"):
        manage_credentials(credential_store)
        return

    # Import providers to trigger registration
    import providers  # noqa: F401

    try:
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run(**args, credential_store=credential_store))
            loop.close()
        else:
            asyncio.run(run(**args, credential_store=credential_store))
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
