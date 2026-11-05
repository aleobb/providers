import asyncio
import csv
import sys
from types import SimpleNamespace

from core import cli


def test_download_run_exports_extracted_data_to_csv(monkeypatch, tmp_path):
    csv_path = tmp_path / "download-data.csv"
    provider = SimpleNamespace(name="edenor", display_name="Edenor")
    monkeypatch.setattr(cli, "get_provider", lambda _name: provider)
    monkeypatch.setattr(cli.run_log, "log_run_start", lambda *_args: None)

    async def fake_run_provider(*_args, invoice_data_rows=None, **_kwargs):
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
        )
    )

    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["archivo"] == "factura.pdf"
    assert rows[0]["vencimiento_actual"] == "2026-11-05"


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
