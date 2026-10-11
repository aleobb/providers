from decimal import Decimal
from types import SimpleNamespace

from core import cli
from integrations.invoice_data_extractor import InvoiceData


def test_success_report_includes_extracted_invoice_data(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "determine_invoice_period", lambda *_args: "2026-04")
    monkeypatch.setattr(cli.run_log, "log_ok", lambda *_args: None)
    monkeypatch.setattr(
        cli,
        "extract_invoice_data",
        lambda *_args: InvoiceData(
            provider_name="Edenor",
            amount=Decimal("1234.56"),
            current_due_date="2026-11-05",
            next_due_date="2026-11-20",
            text_layer_available=True,
            read_error=False,
        ),
    )
    provider = SimpleNamespace(
        name="edenor",
        display_name="Edenor",
        extract_invoice_date=lambda _text: None,
    )
    account = SimpleNamespace(client_number="123")
    path = tmp_path / "invoice.pdf"

    cli._record_download_success(
        provider, account, path, drive_uploader=None, drive_root_id=""
    )

    output = capsys.readouterr().out
    assert "proveedor=Edenor" in output
    assert "importe=1234.56" in output
    assert "vencimiento_actual=2026-11-05" in output
    assert "proximo_vto=2026-11-20" in output
    assert "texto=disponible" in output
