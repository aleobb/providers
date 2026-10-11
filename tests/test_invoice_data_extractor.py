from decimal import Decimal
from types import SimpleNamespace

from integrations import invoice_data_extractor


def _provider(patterns=None):
    return SimpleNamespace(
        display_name="Proveedor de prueba",
        invoice_data_patterns=patterns or {},
    )


def test_extracts_common_invoice_fields_from_pdf_text(monkeypatch, tmp_path):
    monkeypatch.setattr(
        invoice_data_extractor,
        "_read_text",
        lambda _path: (
            "TOTAL A PAGAR: $ 1.234,56\n"
            "Vencimiento actual: 05/11/2026\n"
            "Próximo vencimiento: 20/11/2026"
        ),
    )

    data = invoice_data_extractor.extract_invoice_data(
        tmp_path / "factura.pdf", _provider()
    )

    assert data.provider_name == "Proveedor de prueba"
    assert data.amount == Decimal("1234.56")
    assert data.current_due_date == "2026-11-05"
    assert data.next_due_date == "2026-11-20"
    assert data.text_layer_available is True
    assert data.read_error is False


def test_extracts_us_style_amount_and_plain_current_due_date(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        invoice_data_extractor,
        "_read_text",
        lambda _path: "Importe total: $1,234.56 Vencimiento: 05-11-2026",
    )

    data = invoice_data_extractor.extract_invoice_data(
        tmp_path / "factura.pdf", _provider()
    )

    assert data.amount == Decimal("1234.56")
    assert data.current_due_date == "2026-11-05"


def test_provider_patterns_override_generic_patterns(monkeypatch, tmp_path):
    monkeypatch.setattr(
        invoice_data_extractor,
        "_read_text",
        lambda _path: (
            "Importe especial: $ 99,50\n"
            "Corte de pago: 07/12/2026"
        ),
    )
    provider = _provider(
        {
            "amount": (r"importe especial:\s*\$?\s*([\d.,]+)",),
            "current_due_date": (
                r"corte de pago:\s*(\d{2})/(\d{2})/(\d{4})",
            ),
        }
    )

    data = invoice_data_extractor.extract_invoice_data(
        tmp_path / "factura.pdf", provider
    )

    assert data.amount == Decimal("99.50")
    assert data.current_due_date == "2026-12-07"


def test_missing_or_invalid_fields_are_reported_as_unavailable(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        invoice_data_extractor,
        "_read_text",
        lambda _path: "Vencimiento actual: 31/02/2026",
    )

    data = invoice_data_extractor.extract_invoice_data(
        tmp_path / "factura.pdf", _provider()
    )

    assert data.amount is None
    assert data.current_due_date is None
    assert data.next_due_date is None
    assert data.text_layer_available is True


def test_unreadable_pdf_returns_provider_and_empty_fields(monkeypatch, tmp_path):
    def fail_read(_path):
        raise OSError("invalid PDF")

    monkeypatch.setattr(invoice_data_extractor, "_read_text", fail_read)

    data = invoice_data_extractor.extract_invoice_data(
        tmp_path / "factura.pdf", _provider()
    )

    assert data.provider_name == "Proveedor de prueba"
    assert data.amount is None
    assert data.current_due_date is None
    assert data.next_due_date is None
    assert data.text_layer_available is False
    assert data.read_error is True
