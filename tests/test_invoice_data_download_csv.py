import asyncio
import csv
import sys
from types import SimpleNamespace

from core import cli


def test_download_run_exports_extracted_data_to_csv(monkeypatch, tmp_path):
    csv_path = tmp_path / "download-data.csv"
    provider = SimpleNamespace(name="edenor", display_name="Edenor")
    airtable_instance = object()
    received_airtable = []
    monkeypatch.setattr(cli, "get_provider", lambda _name: provider)
    monkeypatch.setattr(cli.run_log, "log_run_start", lambda *_args: None)
    monkeypatch.setattr(cli.AirtableConfig, "from_env", lambda: object())
    monkeypatch.setattr(
        cli, "AirtableInvoiceSync", lambda _config: airtable_instance
    )

    async def fake_run_provider(*_args, invoice_data_rows=None, **_kwargs):
        received_airtable.append(_kwargs["airtable_sync"])
        invoice_data_rows.append(
            {
                "archivo": "factura.pdf",
                "proveedor": "Edenor",
                "banco": "",
                "importe": "250.00",
                "vencimiento_actual": "2026-11-05",
                "proximo_vencimiento": "",
                "cierre_actual": "",
                "proximo_cierre": "",
                "importe_pesos": "",
                "importe_dolares": "",
                "texto_disponible": "true",
                "error_lectura": "false",
            }
        )
        return True

    monkeypatch.setattr(cli, "run_provider", fake_run_provider)

    asyncio.run(
        cli.run(
            debug=False,
            listar=False,
            todas=True,
            cuenta=None,
            proveedor="edenor",
            todos_proveedores=False,
            credential_store=object(),
            datos_pdf_csv=str(csv_path),
            airtable=True,
        )
    )

    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["archivo"] == "factura.pdf"
    assert rows[0]["vencimiento_actual"] == "2026-11-05"
    assert received_airtable == [airtable_instance]


def test_parse_args_accepts_download_data_csv(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--proveedor", "edenor", "--datos-pdf-csv", "datos.csv"],
    )

    args = cli.parse_args()

    assert args["datos_pdf_csv"] == "datos.csv"


def test_parse_args_accepts_ingresar(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--proveedor", "edenor", "--ingresar"],
    )

    args = cli.parse_args()

    assert args["proveedor"] == "edenor"
    assert args["ingresar"] is True


def test_parse_args_accepts_airtable(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--proveedor", "edenor", "--todas", "--airtable"],
    )

    args = cli.parse_args()

    assert args["airtable"] is True


def test_parse_args_accepts_airtable_document_and_bank(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--airtable-documento",
            r"C:\documentos\factura.pdf",
            "--proveedor",
            "edenor",
            "--banco",
            "BBVA",
        ],
    )

    args = cli.parse_args()

    assert args["airtable_documento"] == r"C:\documentos\factura.pdf"
    assert args["proveedor"] == "edenor"
    assert args["banco"] == "BBVA"


def test_airtable_document_mode_does_not_run_provider_download(
    monkeypatch, tmp_path, capsys
):
    from integrations.airtable.sync import AirtableSyncResult

    pdf_path = tmp_path / "visa.pdf"
    pdf_path.write_bytes(b"test")
    invoice_data = SimpleNamespace(
        provider_name="Visa (Prisma)", bank_name="BBVA"
    )
    sync_calls = []
    provider = object()
    airtable_sync = SimpleNamespace(
        sync_invoice=lambda path, data: (
            sync_calls.append((path, data))
            or AirtableSyncResult(
                record_id="rec-123",
                created=True,
                attachment_uploaded=True,
            )
        )
    )
    monkeypatch.setattr(cli, "_read_text", lambda *_args, **_kwargs: "card text")
    monkeypatch.setattr(cli, "detect_card_provider", lambda _text: "visa")
    monkeypatch.setattr(cli, "get_provider", lambda _name: provider)
    monkeypatch.setattr(
        cli, "extract_invoice_data_from_text", lambda *_args, **_kwargs: invoice_data
    )
    monkeypatch.setattr(cli.AirtableConfig, "from_env", lambda: object())
    monkeypatch.setattr(
        cli, "AirtableInvoiceSync", lambda _config: airtable_sync
    )

    async def fail_if_downloading(*_args, **_kwargs):
        raise AssertionError("manual document mode must not run a provider")

    monkeypatch.setattr(cli, "run_provider", fail_if_downloading)

    asyncio.run(
        cli.run(
            debug=False,
            listar=False,
            todas=False,
            cuenta=None,
            proveedor=None,
            todos_proveedores=False,
            airtable_documento=str(pdf_path),
        )
    )

    assert sync_calls == [(pdf_path, invoice_data)]
    output = capsys.readouterr().out
    assert "[Airtable] Comprobante creado: rec-123" in output
    assert "[Airtable] PDF adjuntado en el campo Doc." in output


def test_main_skips_credential_store_for_airtable_document(
    monkeypatch, tmp_path
):
    received_args = []
    pdf_path = tmp_path / "factura.pdf"

    def fail_if_initializing_credentials():
        raise AssertionError("manual Airtable mode must not load credentials")

    async def fake_run(**kwargs):
        received_args.append(kwargs)

    monkeypatch.setattr(
        sys, "argv", ["main.py", "--airtable-documento", str(pdf_path)]
    )
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(cli, "CredentialStore", fail_if_initializing_credentials)
    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)

    cli.main()

    assert received_args[0]["credential_store"] is None
