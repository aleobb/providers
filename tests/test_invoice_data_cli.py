from decimal import Decimal
from types import SimpleNamespace

from core import cli
from integrations.pdf_extractor.invoice_data import InvoiceData


def test_success_report_includes_extracted_invoice_data(monkeypatch, tmp_path, capsys):
    extract_calls = []

    monkeypatch.setattr(cli, "determine_invoice_period", lambda *_args: "2026-04")
    monkeypatch.setattr(cli.run_log, "log_ok", lambda *_args: None)

    def fake_extract(*args, **kwargs):
        extract_calls.append((args, kwargs))
        return InvoiceData(
            provider_name="Edenor",
            amount=Decimal("1234.56"),
            current_due_date="2026-11-05",
            next_due_date="2026-11-20",
            text_layer_available=True,
            read_error=False,
            bank_name="BBVA",
            current_closing_date="2026-10-18",
            next_closing_date="2026-11-18",
            amount_ars=Decimal("1234.56"),
            amount_usd=Decimal("0.00"),
        )

    monkeypatch.setattr(
        cli,
        "extract_invoice_data",
        fake_extract,
    )
    provider = SimpleNamespace(
        name="edenor",
        display_name="Edenor",
        extract_invoice_date=lambda _text: None,
    )
    account = SimpleNamespace(
        client_number="123", extra={"banco": "Banco de la cuenta"}
    )
    path = tmp_path / "invoice.pdf"
    invoice_data_rows = []

    cli._record_download_success(
        provider,
        account,
        path,
        drive_uploader=None,
        drive_root_id="",
        invoice_data_rows=invoice_data_rows,
    )

    output = capsys.readouterr().out
    assert "proveedor=Edenor" in output
    assert "importe=1234.56" in output
    assert "vencimiento_actual=2026-11-05" in output
    assert "proximo_vto=2026-11-20" in output
    assert "texto=disponible" in output
    assert "banco=BBVA" in output
    assert "cierre_actual=2026-10-18" in output
    assert "importe_dolares=0.00" in output
    assert invoice_data_rows[0]["archivo"] == "invoice.pdf"
    assert invoice_data_rows[0]["importe"] == "1234.56"
    assert invoice_data_rows[0]["cierre_actual"] == "2026-10-18"
    assert extract_calls[0][1]["bank_name"] == "Banco de la cuenta"
