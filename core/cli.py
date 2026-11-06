from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .accounts import Account, select_account
from .browser import BrowserSession
from .exceptions import (
    CaptchaError,
    ConfigurationError,
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
from integrations.airtable.sync import (
    AirtableConfigurationError,
    AirtableConfig,
    AirtableInvoiceSync,
    AirtableSyncError,
)
from integrations.pdf_extractor.extractor import determine_invoice_period
from integrations.pdf_extractor.csv_export import (
    invoice_data_to_csv_row,
    write_invoice_data_csv,
)
from integrations.pdf_extractor.invoice_data import (
    InvoiceData,
    extract_invoice_data,
    extract_invoice_data_from_text,
)
from integrations.pdf_extractor.card_statement import detect_card_provider
from integrations.pdf_extractor.extractor import _read_text
from pdfminer.pdfexceptions import PDFException


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
        "datos_pdf_csv": None,
        "ingresar": False,
        "airtable": False,
        "airtable_documento": None,
        "banco": None,
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
        elif args[i] == "--ingresar":
            result["ingresar"] = True
        elif args[i] == "--airtable":
            result["airtable"] = True
        elif args[i] == "--airtable-documento" and i + 1 < len(args):
            result["airtable_documento"] = args[i + 1]
            i += 1
        elif args[i] == "--banco" and i + 1 < len(args):
            result["banco"] = args[i + 1]
            i += 1
        elif args[i] == "--gestionar-credenciales":
            result["gestionar_credenciales"] = True
        elif args[i] == "--datos-pdf-csv" and i + 1 < len(args):
            result["datos_pdf_csv"] = args[i + 1]
            i += 1
        elif args[i] == "--url" and i + 1 < len(args):
            result["url"] = args[i + 1]
            i += 1
        i += 1
    return result


async def _download_one(
    provider: Provider, page, context, account, *, catch_all: bool = False
):
    """Download one invoice, returning (path, error)."""
    try:
        path = await provider.download_invoice(page, context, account)
        return path, None
    except Exception as error:
        if catch_all or isinstance(error, InvoiceDownloaderError):
            return None, error
        raise


def _upload_if_enabled(
    provider: Provider,
    account,
    period: str,
    path: Path,
    drive_uploader,
    drive_root_id: str,
) -> None:
    if not drive_uploader or not drive_root_id:
        return
    banco = account.extra.get("banco", "") if account.extra else ""
    from integrations.google_drive.drive import upload_invoice_to_drive

    upload_invoice_to_drive(
        drive_uploader, drive_root_id, provider, period, path, banco
    )


async def _record_download_success(
    provider: Provider,
    account,
    path: Path,
    drive_uploader,
    drive_root_id: str,
    invoice_data_rows: list[dict[str, str]] | None = None,
    airtable_sync: AirtableInvoiceSync | None = None,
) -> None:
    period = determine_invoice_period(path, provider.extract_invoice_date)
    run_log.log_ok(provider.name, account.client_number, period, path)
    account_bank = (getattr(account, "extra", None) or {}).get("banco")
    invoice_data = extract_invoice_data(
        path, provider, bank_name=account_bank
    )
    amount = f"{invoice_data.amount:.2f}" if invoice_data.amount is not None else "-"
    current_due = invoice_data.current_due_date or "-"
    next_due = invoice_data.next_due_date or "-"
    text_status = (
        "error de lectura"
        if invoice_data.read_error
        else (
            "disponible"
            if invoice_data.text_layer_available
            else "no detectado; pdfplumber no aplica OCR"
        )
    )
    print(
        f"  Datos PDF: proveedor={invoice_data.provider_name}; "
        f"importe={amount}; vencimiento_actual={current_due}; "
        f"proximo_vto={next_due}; texto={text_status}"
    )
    if invoice_data.bank_name:
        amount_ars = (
            f"{invoice_data.amount_ars:.2f}"
            if invoice_data.amount_ars is not None
            else "-"
        )
        amount_usd = (
            f"{invoice_data.amount_usd:.2f}"
            if invoice_data.amount_usd is not None
            else "-"
        )
        print(
            f"  Resumen tarjeta: banco={invoice_data.bank_name}; "
            f"cierre_actual={invoice_data.current_closing_date or '-'}; "
            f"proximo_cierre={invoice_data.next_closing_date or '-'}; "
            f"importe_pesos={amount_ars}; "
            f"importe_dolares={amount_usd}"
        )
    if invoice_data_rows is not None:
        invoice_data_rows.append(invoice_data_to_csv_row(path, invoice_data))
    _upload_if_enabled(
        provider, account, period, path, drive_uploader, drive_root_id
    )
    if airtable_sync is not None:
        result = await asyncio.to_thread(
            airtable_sync.sync_invoice, path, invoice_data
        )
        action = "creado" if result.created else "actualizado"
        print(
            f"  [Airtable] Comprobante {action}: "
            f"{result.record_id}"
        )
        if result.attachment_uploaded:
            print("  [Airtable] PDF adjuntado en el campo Doc.")
        else:
            print("  [Airtable] PDF ya adjunto; se omitió duplicarlo.")


async def _download_all_accounts(
    provider: Provider,
    accounts: list,
    page,
    context,
    drive_uploader,
    drive_root_id: str,
    *,
    without_browser: bool,
    invoice_data_rows: list[dict[str, str]] | None = None,
    airtable_sync: AirtableInvoiceSync | None = None,
) -> bool:
    results = []
    for index, account in enumerate(accounts, 1):
        label = (
            f"[{index}/{len(accounts)}] N {account.client_number} - "
            f"{account.display_name}"
        )
        print(f"{label} - descargando...")
        path, error = await _download_one(
            provider, page, context, account, catch_all=without_browser
        )
        if path:
            print(f"  OK: {path.resolve()}")
            try:
                await _record_download_success(
                    provider, account, path, drive_uploader, drive_root_id,
                    invoice_data_rows, airtable_sync,
                )
            except Exception as record_error:
                if not without_browser and not isinstance(
                    record_error, AirtableSyncError
                ):
                    raise
                path, error = None, record_error

        if error:
            print(f"  ERROR: {error}", file=sys.stderr)
            run_log.log_error(provider.name, account.client_number, str(error))
            if without_browser and provider.is_session_error(error):
                from core import session_store

                session_store.clear(provider.session_key)
                print(
                    "  [Session] Sesión invalidada — el próximo run hará login.",
                    file=sys.stderr,
                )
            results.append((account, None, error))
        else:
            results.append((account, path, None))

    ok = [result for result in results if result[1]]
    failed = [result for result in results if result[2]]
    print(f"\nResumen {provider.display_name}:")
    for account, path, _ in ok:
        print(f"  OK   N {account.client_number}: {path.name}")
    for account, _, error in failed:
        print(f"  FAIL N {account.client_number}: {error}", file=sys.stderr)
    return not failed


async def _run_provider_no_browser(
    provider: Provider,
    accounts: list,
    todas: bool,
    cuenta: str | None,
    drive_uploader,
    drive_root_id: str,
    invoice_data_rows: list[dict[str, str]] | None = None,
    airtable_sync: AirtableInvoiceSync | None = None,
) -> bool:
    """
    Descarga facturas usando sesión guardada — sin abrir el browser.
    Devuelve True si todo fue OK; False si alguna descarga falló.
    """
    from core import session_store

    if todas:
        print(f"\nDescargando facturas de {len(accounts)} cuenta(s) (sin browser)...\n")
        return await _download_all_accounts(
            provider,
            accounts,
            None,
            None,
            drive_uploader,
            drive_root_id,
            without_browser=True,
            invoice_data_rows=invoice_data_rows,
            airtable_sync=airtable_sync,
        )

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
    await _record_download_success(
        provider, account, pdf_path, drive_uploader, drive_root_id,
        invoice_data_rows, airtable_sync,
    )
    return True


async def _run_provider(
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
    invoice_data_rows: list[dict[str, str]] | None = None,
    airtable_sync: AirtableInvoiceSync | None = None,
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
                        provider, accounts, todas, cuenta, drive_uploader,
                        drive_root_id, invoice_data_rows, airtable_sync,
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
            return await _download_all_accounts(
                provider,
                accounts,
                service_page,
                service_context,
                drive_uploader,
                drive_root_id,
                without_browser=False,
                invoice_data_rows=invoice_data_rows,
                airtable_sync=airtable_sync,
            )

        # Single account
        account = select_account(accounts, cuenta)
        if len(accounts) > 1:
            print(f"\nCuenta seleccionada: N {account.client_number} - {account.display_name}")

        print("Descargando ultima factura...")
        pdf_path = await provider.download_invoice(service_page, service_context, account)
        print(f"\nFactura descargada: {pdf_path.resolve()}")
        await _record_download_success(
            provider, account, pdf_path, drive_uploader, drive_root_id,
            invoice_data_rows, airtable_sync,
        )
        return True

      finally:
        # Cerrar sesion antes de que el browser se cierre (evita conflictos en la proxima ejecucion)
        try:
            await provider.logout(session.page, session.context)
        except Exception as e:
            print(f"  [logout] {provider.name}: {e}", file=sys.stderr)


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
    invoice_data_rows: list[dict[str, str]] | None = None,
    airtable_sync: AirtableInvoiceSync | None = None,
) -> bool:
    """Run a single provider and release its resources."""
    try:
        return await _run_provider(
            provider,
            debug,
            listar,
            todas,
            cuenta,
            url=url,
            drive_uploader=drive_uploader,
            drive_root_id=drive_root_id,
            nosession=nosession,
            credential_store=credential_store,
            invoice_data_rows=invoice_data_rows,
            airtable_sync=airtable_sync,
        )
    finally:
        await provider.close()


async def _login_provider(
    provider: Provider,
    *,
    url: str | None,
    credential_store: CredentialStore | None,
) -> bool:
    config = provider.get_config()
    if provider.requires_credentials:
        credential_store = credential_store or CredentialStore()
        profile = credential_store.request_credentials(provider.name)
        provider.configure_credentials(
            profile,
            len(credential_store.list_profiles(provider.name)),
            Path(__file__).resolve().parents[1] / ".sessions",
        )
    config.headless = False
    provider.apply_run_options(url=url)

    print(f"\nIngresando a {provider.display_name}...")
    async with BrowserSession(config, profile_name=provider.session_key) as session:
        await provider.login(session.page, session.context)
        await asyncio.sleep(2)
        for _ in range(3):
            closed = await dismiss_popups(session.page, label=provider.name)
            if not closed:
                break
            await asyncio.sleep(0.5)

        print(
            "Login completado. El portal quedará abierto; "
            "cerrá la ventana para finalizar."
        )
        await session.page.wait_for_event("close")
    print(f"Ventana de {provider.display_name} cerrada.")
    return True


async def login_provider(
    provider: Provider,
    *,
    url: str | None = None,
    credential_store: CredentialStore | None = None,
) -> bool:
    """Log in visibly and keep the provider portal open until Chrome closes."""
    try:
        return await _login_provider(
            provider,
            url=url,
            credential_store=credential_store,
        )
    finally:
        await provider.close()


def _extract_document_invoice(
    pdf_path: Path,
    provider_name: str | None,
    bank_name: str | None,
) -> InvoiceData:
    if not pdf_path.is_file():
        raise AirtableSyncError(f"No se encontró el documento: {pdf_path}.")
    if pdf_path.suffix.lower() != ".pdf":
        raise AirtableSyncError(
            f"El documento debe ser un PDF: {pdf_path.name}."
        )
    try:
        text = _read_text(pdf_path, max_pages=None)
    except (OSError, ValueError, PDFException) as error:
        raise AirtableSyncError(
            f"No se pudo leer el PDF {pdf_path}: {error}"
        ) from error
    if not text.strip():
        raise AirtableSyncError(
            f"El PDF {pdf_path.name} no contiene texto seleccionable; "
            "el extractor no realiza OCR."
        )

    selected_provider = provider_name or detect_card_provider(text)
    if not selected_provider:
        raise AirtableSyncError(
            "No se pudo identificar el proveedor en el documento. "
            "Indicá --proveedor <nombre>."
        )
    try:
        provider = get_provider(selected_provider.lower())
    except ConfigurationError as error:
        raise AirtableSyncError(
            f"No se pudo cargar el proveedor '{selected_provider}': {error}"
        ) from error
    data = extract_invoice_data_from_text(
        text, provider, bank_name=bank_name
    )
    return data


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
    datos_pdf_csv: str | None = None,
    ingresar: bool = False,
    airtable: bool = False,
    airtable_documento: str | None = None,
    banco: str | None = None,
) -> None:
    if airtable_documento is not None:
        if (
            todos_proveedores
            or listar
            or todas
            or cuenta is not None
            or datos_pdf_csv is not None
            or ingresar
            or airtable
        ):
            print(
                "--airtable-documento se usa solo y no se combina con "
                "--listar, --todas, --cuenta, --todos-proveedores, "
                "--datos-pdf-csv, --ingresar ni --airtable.",
                file=sys.stderr,
            )
            sys.exit(2)
        try:
            pdf_path = Path(airtable_documento).expanduser()
            invoice_data = _extract_document_invoice(
                pdf_path, proveedor, banco
            )
            airtable_sync = AirtableInvoiceSync(AirtableConfig.from_env())
            result = await asyncio.to_thread(
                airtable_sync.sync_invoice, pdf_path, invoice_data
            )
        except (AirtableConfigurationError, AirtableSyncError) as error:
            print(f"ERROR [Airtable]: {error}", file=sys.stderr)
            sys.exit(1)

        action = "creado" if result.created else "actualizado"
        print(
            f"[Airtable] Comprobante {action}: {result.record_id} "
            f"(proveedor={invoice_data.provider_name}; "
            f"banco={invoice_data.bank_name or '-'})"
        )
        if result.attachment_uploaded:
            print("[Airtable] PDF adjuntado en el campo Doc.")
        else:
            print("[Airtable] PDF ya adjunto; se omitió duplicarlo.")
        return

    if banco is not None:
        print("--banco solo se puede usar junto con --airtable-documento.", file=sys.stderr)
        sys.exit(2)

    if ingresar and (
        todos_proveedores
        or not proveedor
        or listar
        or todas
        or cuenta is not None
        or datos_pdf_csv is not None
        or airtable
    ):
        print(
            "--ingresar requiere un único --proveedor y no se combina con "
            "--listar, --todas, --cuenta, --datos-pdf-csv ni --airtable.",
            file=sys.stderr,
        )
        sys.exit(2)

    if airtable and listar:
        print("--airtable solo se puede usar al descargar comprobantes.", file=sys.stderr)
        sys.exit(2)

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

    if ingresar:
        try:
            await login_provider(
                providers[0],
                url=url,
                credential_store=credential_store,
            )
        except ServerUnavailableError as error:
            print(
                f"\n[{providers[0].display_name}] Servidor no disponible: "
                f"{error}",
                file=sys.stderr,
            )
            sys.exit(1)
        except (InvoiceDownloaderError, CredentialStoreError) as error:
            print(f"\nERROR [{providers[0].display_name}]: {error}", file=sys.stderr)
            sys.exit(1)
        return

    airtable_sync = None
    if airtable:
        try:
            airtable_sync = AirtableInvoiceSync(AirtableConfig.from_env())
        except AirtableConfigurationError as error:
            print(f"ERROR [Airtable]: {error}", file=sys.stderr)
            sys.exit(2)
        print("[Airtable] Sincronización de comprobantes activada.")

    if debug:
        print("[DEBUG] Modo headless desactivado - el browser sera visible.")

    # Inicializar Google Drive uploader si las credenciales están configuradas
    drive_uploader = None
    drive_root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    if drive_root_id and os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        try:
            from integrations.google_drive.drive import DriveUploader
            drive_uploader = DriveUploader()
            print(f"[Drive] Uploader iniciado. Carpeta raíz: {drive_root_id}")
        except Exception as e:
            print(f"[Drive] No se pudo inicializar el uploader: {e}", file=sys.stderr)
            drive_uploader = None

    if not listar:
        run_log.log_run_start([p.name for p in providers])

    all_ok = True
    invoice_data_rows: list[dict[str, str]] | None = (
        [] if datos_pdf_csv else None
    )
    for provider in providers:
        try:
            ok = await run_provider(
                provider, debug, listar, todas, cuenta,
                url=url,
                drive_uploader=drive_uploader,
                drive_root_id=drive_root_id,
                nosession=nosession,
                credential_store=credential_store,
                invoice_data_rows=invoice_data_rows,
                airtable_sync=airtable_sync,
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
        except AirtableSyncError as e:
            print(f"\nERROR [Airtable] [{provider.display_name}]: {e}", file=sys.stderr)
            run_log.log_error(provider.name, None, str(e))
            all_ok = False

    if datos_pdf_csv and invoice_data_rows is not None:
        try:
            write_invoice_data_csv(Path(datos_pdf_csv), invoice_data_rows)
        except OSError as error:
            print(
                f"\nERROR: No se pudo escribir el CSV {datos_pdf_csv}: {error}",
                file=sys.stderr,
            )
            all_ok = False
        else:
            print(f"Datos de facturas guardados en: {datos_pdf_csv}")

    if not all_ok:
        sys.exit(1)


def main() -> None:
    from dotenv import load_dotenv

    args = parse_args()
    manual_airtable_document = args["airtable_documento"] is not None
    if manual_airtable_document and args["gestionar_credenciales"]:
        print(
            "--airtable-documento no se combina con "
            "--gestionar-credenciales.",
            file=sys.stderr,
        )
        sys.exit(2)

    credential_store = None
    if not manual_airtable_document:
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
    if args.pop("gestionar_credenciales"):
        assert credential_store is not None
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
