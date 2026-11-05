from decimal import Decimal
from types import SimpleNamespace

from integrations.pdf_extractor import invoice_data
from integrations.pdf_extractor.card_statement import (
    parse_mastercard_icbc,
    parse_visa_nacion,
    parse_visa_statement,
)


def _provider(patterns=None):
    return SimpleNamespace(
        display_name="Proveedor de prueba",
        invoice_data_patterns=patterns or {},
        extract_card_statement_data=lambda _text: None,
    )


def test_extracts_common_invoice_fields_from_pdf_text(monkeypatch, tmp_path):
    monkeypatch.setattr(
        invoice_data,
        "_read_text",
        lambda _path: (
            "TOTAL A PAGAR: $ 1.234,56\n"
            "Vencimiento actual: 05/11/2026\n"
            "Próximo vencimiento: 20/11/2026"
        ),
    )

    data = invoice_data.extract_invoice_data(
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
        invoice_data,
        "_read_text",
        lambda _path: "Importe total: $1,234.56 Vencimiento: 05-11-2026",
    )

    data = invoice_data.extract_invoice_data(
        tmp_path / "factura.pdf", _provider()
    )

    assert data.amount == Decimal("1234.56")
    assert data.current_due_date == "2026-11-05"


def test_provider_patterns_override_generic_patterns(monkeypatch, tmp_path):
    monkeypatch.setattr(
        invoice_data,
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

    data = invoice_data.extract_invoice_data(
        tmp_path / "factura.pdf", provider
    )

    assert data.amount == Decimal("99.50")
    assert data.current_due_date == "2026-12-07"


def test_missing_or_invalid_fields_are_reported_as_unavailable(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        invoice_data,
        "_read_text",
        lambda _path: "Vencimiento actual: 31/02/2026",
    )

    data = invoice_data.extract_invoice_data(
        tmp_path / "factura.pdf", _provider()
    )

    assert data.amount is None
    assert data.current_due_date is None
    assert data.next_due_date is None
    assert data.text_layer_available is True


def test_unreadable_pdf_returns_provider_and_empty_fields(monkeypatch, tmp_path):
    def fail_read(_path):
        raise OSError("invalid PDF")

    monkeypatch.setattr(invoice_data, "_read_text", fail_read)

    data = invoice_data.extract_invoice_data(
        tmp_path / "factura.pdf", _provider()
    )

    assert data.provider_name == "Proveedor de prueba"
    assert data.amount is None
    assert data.current_due_date is None
    assert data.next_due_date is None
    assert data.text_layer_available is False
    assert data.read_error is True


def test_card_statement_fields_are_optional_and_additive():
    text = (
        "VISA\n"
        "CIERRE ACTUAL: 18 Sep 26\n"
        "18 Sep 26 776.977,92 0,00 47.602,00 -,--\n"
        "VTO. ANTERIOR 10 Jun 26 SALDO ANTERIOR $ 56.000,00 "
        "U$S 0,00 PROXIMO CIERRE 30 Jul 26\n"
        "CIERRE ANTERIOR 28 May 26 PAGO MIN. ANT. $ 5.596,00 "
        "PROXIMO VTO. 12 Ago 26"
    )
    provider = _provider()
    provider.name = "visa"
    provider.extract_card_statement_data = parse_visa_nacion

    data = invoice_data.extract_invoice_data_from_text(text, provider)

    assert data.amount == Decimal("776977.92")
    assert data.amount_ars == Decimal("776977.92")
    assert data.amount_usd == Decimal("0.00")
    assert data.current_due_date == "2026-09-18"
    assert data.next_due_date == "2026-08-12"
    assert data.current_closing_date == "2026-09-18"
    assert data.next_closing_date == "2026-07-30"


def test_extracts_visa_statement_with_spaced_pdf_text():
    text = (
        "VISA SIGNATURE\n"
        "CIERRE ACTUAL: 29 Oct 26\n"
        "VENCIMIENTO SALDO $ SALDO U$S PAGO MIN.$ PAGO MIN.U$S\n"
        "CAPITAL 11 Nov 26 123.456,78 0,00 12.345,00 -,--\n"
        "VTO. ANTERIOR 0 9 O c t 2 6 SALDO ANTERIOR $ 100,00 "
        "PROXIMO CIERRE 26 Nov 26\n"
        "CIERRE ANTERIOR 0 1 O c t 2 6 PAGO MIN. ANT. $ 10,00 "
        "PROXIMO VTO. 04 Dic 26"
    )
    provider = _provider()
    provider.extract_card_statement_data = parse_visa_statement

    data = invoice_data.extract_invoice_data_from_text(text, provider)

    assert data.amount == Decimal("123456.78")
    assert data.amount_ars == Decimal("123456.78")
    assert data.amount_usd == Decimal("0.00")
    assert data.current_due_date == "2026-11-11"
    assert data.next_due_date == "2026-12-04"
    assert data.current_closing_date == "2026-10-29"
    assert data.next_closing_date == "2026-11-26"
    assert data.bank_name is None


def test_extracts_negative_usd_amount_from_visa_bbva_statement():
    text = (
        "VISA BBVA\n"
        "CIERRE ACTUAL: 18 Oct 26\n"
        "VENCIMIENTO SALDO $ SALDO U$S PAGO MIN.$ PAGO MIN.U$S\n"
        "CAPITAL 18 Oct 26 123.456,78 0.03- 12.345,00 -,--\n"
        "VTO. ANTERIOR 10 Sep 26 SALDO ANTERIOR $ 100,00 "
        "PROXIMO CIERRE 29 Nov 26\n"
        "CIERRE ANTERIOR 28 Ago 26 PAGO MIN. ANT. $ 10,00 "
        "PROXIMO VTO. 10 Dic 26"
    )
    provider = _provider()
    provider.extract_card_statement_data = parse_visa_statement

    data = invoice_data.extract_invoice_data_from_text(text, provider)

    assert data.amount_usd == Decimal("-0.03")


def test_account_bank_overrides_layout_bank():
    text = (
        "VISA\n"
        "CIERRE ACTUAL: 18 Sep 26\n"
        "18 Sep 26 776.977,92 0,00 47.602,00 -,--\n"
        "VTO. ANTERIOR 10 Jun 26 SALDO ANTERIOR $ 56.000,00 "
        "U$S 0,00 PROXIMO CIERRE 30 Jul 26\n"
        "CIERRE ANTERIOR 28 May 26 PAGO MIN. ANT. $ 5.596,00 "
        "PROXIMO VTO. 12 Ago 26"
    )
    provider = _provider()
    provider.extract_card_statement_data = parse_visa_nacion

    data = invoice_data.extract_invoice_data_from_text(
        text, provider, bank_name="Banco de la cuenta"
    )

    assert data.bank_name == "Banco de la cuenta"


def test_extracts_labelled_mastercard_icbc_data_from_text():
    text = (
        "MASTERCARD INTERNACIONAL\n"
        "Estado de cuenta al: 25-jun.-26 "
        "Saldo actual: $ 123.456,78 U$S 12,25\n"
        "Vencimiento actual: 10-jul.-26 Pago Minimo: $ 5.000,00\n"
        "Cierre Anterior: 28-may.-26 Compras Anteriores: $ 100,00 "
        "U$S 1,00 Proximo Cierre: 25-jul.-26\n"
        "Vencimiento Anterior: 10-jun.-26 Pago Minimo Anterior: $ 4.000,00 "
        "Proximo Vencimiento: 10-ago.-26\n"
        "Industrial and Commercial Bank of China (Argentina) S.A.U."
    )
    provider = _provider()
    provider.extract_card_statement_data = parse_mastercard_icbc

    data = invoice_data.extract_invoice_data_from_text(text, provider)

    assert data.bank_name == "ICBC"
    assert data.amount == Decimal("123456.78")
    assert data.amount_ars == Decimal("123456.78")
    assert data.amount_usd == Decimal("12.25")
    assert data.current_due_date == "2026-07-10"
    assert data.next_due_date == "2026-08-10"
    assert data.current_closing_date == "2026-06-25"
    assert data.next_closing_date == "2026-07-25"


def test_common_provider_data_has_no_card_only_fields():
    provider = _provider()

    data = invoice_data.extract_invoice_data_from_text(
        "TOTAL A PAGAR: $ 250,00\nVencimiento actual: 05/11/2026",
        provider,
    )

    assert data.amount == Decimal("250.00")
    assert data.current_due_date == "2026-11-05"
    assert data.current_closing_date is None
    assert data.next_closing_date is None
    assert data.amount_ars is None
    assert data.amount_usd is None
