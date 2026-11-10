from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations.pdf_extractor import invoice_data
from integrations.pdf_extractor.card_statement import (
    parse_mastercard_icbc,
    parse_visa_nacion,
    parse_visa_statement,
)
from providers.aysa import AysaProvider
from providers.claro import ClaroProvider
from providers.edesur import EdesurProvider
from providers.edenor import EdenorProvider
from providers.metrogas import MetrogasProvider
from providers.mastercard import MastercardProvider
from providers.medife import MedifeProvider
from providers.telecentro import TelecentroProvider
from providers.visa import VisaProvider


def _provider(patterns=None, estimated_next_due_date_months=None):
    return SimpleNamespace(
        display_name="Proveedor de prueba",
        invoice_data_patterns=patterns or {},
        estimated_next_due_date_months=estimated_next_due_date_months,
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


def test_estimates_next_due_date_by_month_without_overwriting_explicit_date():
    provider = _provider(estimated_next_due_date_months=1)
    data = invoice_data.extract_invoice_data_from_text(
        "Vencimiento actual: 31/01/2026", provider
    )
    explicit = invoice_data.extract_invoice_data_from_text(
        "Vencimiento actual: 31/01/2026\n"
        "Próximo vencimiento: 15/02/2026",
        provider,
    )

    assert data.next_due_date == "2026-02-28"
    assert explicit.next_due_date == "2026-02-15"


def test_provider_patterns_are_prioritized_over_generic_patterns(
    monkeypatch, tmp_path
):
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


def test_generic_patterns_remain_fallbacks_for_providers(monkeypatch, tmp_path):
    monkeypatch.setattr(
        invoice_data,
        "_read_text",
        lambda _path: (
            "Total a pagar: $ 99,50\n"
            "Vencimiento actual: 07/12/2026"
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


def test_extracts_holder_from_statement_holder_label():
    data = invoice_data.extract_invoice_data_from_text(
        "TITULAR DE CUENTA: BEN ALEJANDRO OSVALDO\n"
        "BEN ALEJANDRO OSVALDO CIERRE ACTUAL: 22 Oct 26",
        _provider(),
    )

    assert data.holder_name == "BEN ALEJANDRO OSVALDO"


def test_extracts_holder_from_customer_label():
    data = invoice_data.extract_invoice_data_from_text(
        "Cliente: María Pérez\nTotal a pagar: $ 10,00",
        _provider(),
    )

    assert data.holder_name == "María Pérez"


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


def test_extracts_aysa_compact_amount_and_second_due_date():
    data = invoice_data.extract_invoice_data_from_text(
        "Vencimiento 05/11/2026 Totalapagar $ 1.234,56\n"
        "Totalapagarconrecargohastael21/11/2026 (2do.Vencimiento)",
        AysaProvider(),
    )

    assert data.amount == Decimal("1234.56")
    assert data.current_due_date == "2026-11-05"
    assert data.next_due_date == "2026-11-21"


def test_extracts_claro_due_date_without_using_cae_expiration():
    data = invoice_data.extract_invoice_data_from_text(
        "TOTAL A PAGAR $ 123,45\n"
        "Próximo vencimiento: 20/11/2026\n"
        "10 Vence: 05/11/2026\n"
        "C.A.E. N°: 123 Fecha de Vto.: 01/01/2027",
        ClaroProvider(),
    )

    assert data.amount == Decimal("123.45")
    assert data.current_due_date == "2026-11-05"
    assert data.next_due_date == "2026-11-20"


def test_extracts_edenor_compact_labels():
    data = invoice_data.extract_invoice_data_from_text(
        "FechadeVencimiento:05/11/2026\n"
        "TOTALAPAGAR $ 1.234,56\n"
        "Lapr\u00f3ximaliquidaci\u00f3nvenceel10/12/2026",
        EdenorProvider(),
    )

    assert data.amount == Decimal("1234.56")
    assert data.current_due_date == "2026-11-05"
    assert data.next_due_date == "2026-12-10"


def test_edenor_current_due_date_prefers_payment_deadline_over_cesp_date():
    data = invoice_data.extract_invoice_data_from_text(
        "C.E.S.P. N° 123 FechadeVencimiento:31/10/2026\n"
        "Hastael09/11/2026\n"
        "Hastael20/11/2026puedeabonarenentidades\n"
        "La próxima liquidación vence el 10/12/2026",
        EdenorProvider(),
    )

    assert data.current_due_date == "2026-11-09"
    assert data.next_due_date == "2026-12-10"


def test_extracts_edesur_payment_data_and_holder_not_client_number():
    data = invoice_data.extract_invoice_data_from_text(
        "CATALANO ANA MARIA Cliente: 12345\n"
        "C\u00f3digo CESP: 123 F. Vto. CESP: 31/10/2026\n"
        "1\u00b0 Vencimiento: 05/11/2026\n"
        "2\u00b0 Vencimiento: 12/11/2026\n"
        "TOTAL A PAGAR (1\u00b0 vencimiento) $ 1.234,56\n"
        "Tu pr\u00f3xima liquidaci\u00f3n vence el 10/12/2026",
        EdesurProvider(),
    )

    assert data.amount == Decimal("1234.56")
    assert data.current_due_date == "2026-11-05"
    assert data.next_due_date == "2026-12-10"
    assert data.holder_name == "CATALANO ANA MARIA"


def test_edesur_current_due_date_prefers_first_payment_deadline():
    data = invoice_data.extract_invoice_data_from_text(
        "F. Vto. CESP: 31/10/2026\n"
        "1° Vencimiento: 05/11/2026\n"
        "2° Vencimiento: 12/11/2026",
        EdesurProvider(),
    )

    assert data.current_due_date == "2026-11-05"


def test_extracts_metrogas_cesp_dates_and_ignores_customer_type_as_holder():
    data = invoice_data.extract_invoice_data_from_text(
        "TOTAL A PAGAR\n1.234,56\n"
        "06/11/2026\n"
        "FECHA DE VENCIMIENTO: PERIODO DE LIQUIDACI\u00d3N: "
        "26/08/2026 A 24/09/2026\n"
        "PR\u00d3XIMO VENCIMIENTO ESTIMADO 10/12/2026\n"
        "TIPO DE CLIENTE: Dom\u00e9stico\n"
        "CESP N\u00b0: 123 Fecha de Vencimiento CESP: 31/10/2026",
        MetrogasProvider(),
    )

    assert data.amount == Decimal("1234.56")
    assert data.current_due_date == "2026-11-06"
    assert data.next_due_date == "2026-12-10"
    assert data.holder_name is None


def test_extracts_metrogas_payment_due_date_from_sample_documents():
    samples = (
        ("metrogas.pdf", "2026-10-05"),
        ("metrogas2.pdf", "2026-11-06"),
    )
    samples_dir = Path(__file__).parents[1] / "facturas" / "samples"
    available = [
        (name, due)
        for name, due in samples
        if (samples_dir / name).is_file()
    ]
    if not available:
        pytest.skip("PDFs de muestra de Metrogas no disponibles")

    for filename, expected_due_date in available:
        data = invoice_data.extract_invoice_data(
            samples_dir / filename, MetrogasProvider()
        )

        assert data.current_due_date == expected_due_date


def test_medife_current_due_date_comes_from_vencimiento_block():
    data = invoice_data.extract_invoice_data_from_text(
        "VENCIMIENTO\n"
        "Nro.: 00568754\n"
        "19/11/2026\n"
        "F.Vto: 9/11/2026",
        MedifeProvider(),
    )

    assert data.current_due_date == "2026-11-19"


def test_medife_estimates_next_due_date_from_sample():
    path = Path(__file__).parents[1] / "facturas" / "samples" / "medife.pdf"
    if not path.is_file():
        pytest.skip("PDF de muestra de Medifé no disponible")

    data = invoice_data.extract_invoice_data(path, MedifeProvider())

    assert data.current_due_date == "2026-11-19"
    assert data.next_due_date == "2026-12-19"


def test_medife_account_identifier_uses_associated_member_number():
    data = invoice_data.extract_invoice_data_from_text(
        "RAZON SOCIAL / APELLIDOS Y NOMBRES VENCIMIENTO\n"
        "CATALANO ANA MARIA Nro.: 00568754\n"
        "Clave de pago Banelco Nro.:0000000568754\n"
        "Nro. ASOCIADO / EMPRESA: 568754",
        MedifeProvider(),
    )

    assert data.account_identifier == "568754"


def test_metrogas_account_identifier_prefers_customer_number_to_interlocutor():
    data = invoice_data.extract_invoice_data_from_text(
        "Número de cliente\nCalle Uno 123\nBarrio Centro\n00123456789\n"
        "INTERLOCUTOR: 12345678 TIPO DE CLIENTE: Doméstico",
        MetrogasProvider(),
    )

    assert data.account_identifier == "00123456789"


def test_extracts_telecentro_generic_invoice_labels():
    data = invoice_data.extract_invoice_data_from_text(
        "TOTAL A PAGAR $ 123,45\nVENCIMIENTO 05/11/2026",
        TelecentroProvider(),
    )

    assert data.amount == Decimal("123.45")
    assert data.current_due_date == "2026-11-05"


@pytest.mark.parametrize(
    ("provider", "text", "expected"),
    [
        (AysaProvider, "Cuenta de Servicios 001234", "001234"),
        (ClaroProvider, "Cuenta: 1/0012345678", "1/0012345678"),
        (EdenorProvider, "Cuenta N° 001 234 567", "001 234 567"),
        (EdesurProvider, "Cliente N°: 00123456", "00123456"),
        (MetrogasProvider, "INTERLOCUTOR: 00123456", "00123456"),
        (TelecentroProvider, "N° DE CLIENTE 0012345", "0012345"),
    ],
)
def test_extracts_account_identifier_for_service_providers(
    provider, text, expected
):
    data = invoice_data.extract_invoice_data_from_text(text, provider())

    assert data.account_identifier == expected


def test_extracts_mastercard_account_identifier():
    data = invoice_data.extract_invoice_data_from_text(
        "Mastercard Internacional Consolidado\nCuenta 0012345678",
        MastercardProvider(),
    )

    assert data.account_identifier == "0012345678"


@pytest.mark.parametrize(
    ("filename", "provider"),
    [
        ("aysa.pdf", AysaProvider),
        ("aysa2.pdf", AysaProvider),
        ("claro.pdf", ClaroProvider),
        ("edenor.pdf", EdenorProvider),
        ("edesur.pdf", EdesurProvider),
        ("metrogas.pdf", MetrogasProvider),
        ("metrogas2.pdf", MetrogasProvider),
        ("telecentro.pdf", TelecentroProvider),
        ("master_bbva.pdf", MastercardProvider),
        ("medife.pdf", MedifeProvider),
        ("visa_ana.pdf", VisaProvider),
        ("visa_bbva.pdf", VisaProvider),
        ("visa_nac.pdf", VisaProvider),
    ],
)
def test_extracts_account_identifier_from_sample_documents(filename, provider):
    path = Path(__file__).parents[1] / "facturas" / "samples" / filename
    if not path.is_file():
        pytest.skip(f"PDF de muestra no disponible: {filename}")

    data = invoice_data.extract_invoice_data(path, provider())

    assert data.text_layer_available
    assert data.account_identifier
    assert any(character.isdigit() for character in data.account_identifier)
    if filename.startswith("metrogas"):
        assert sum(char.isdigit() for char in data.account_identifier) == 11


@pytest.mark.parametrize(
    ("filename", "provider", "expected_due_date"),
    [
        ("aysa.pdf", AysaProvider, "2026-10-06"),
        ("aysa2.pdf", AysaProvider, "2026-11-19"),
        ("claro.pdf", ClaroProvider, "2026-10-16"),
        ("edenor.pdf", EdenorProvider, "2026-10-09"),
        ("edenor2.pdf", EdenorProvider, "2026-11-09"),
        ("edesur.pdf", EdesurProvider, "2026-11-05"),
        ("master_bbva.pdf", MastercardProvider, "2026-11-11"),
        ("master_icbc.pdf", MastercardProvider, "2026-07-08"),
        ("medife.pdf", MedifeProvider, "2026-11-19"),
        ("metrogas.pdf", MetrogasProvider, "2026-10-05"),
        ("metrogas2.pdf", MetrogasProvider, "2026-11-06"),
        ("telecentro.pdf", TelecentroProvider, "2026-10-01"),
        ("visa_ana.pdf", VisaProvider, "2026-10-14"),
        ("visa_bbva.pdf", VisaProvider, "2026-11-11"),
        ("visa_nac.pdf", VisaProvider, "2026-11-04"),
    ],
)
def test_current_due_date_matches_sample_payment_deadline(
    filename, provider, expected_due_date
):
    path = Path(__file__).parents[1] / "facturas" / "samples" / filename
    if not path.is_file():
        pytest.skip(f"PDF de muestra no disponible: {filename}")
    data = invoice_data.extract_invoice_data(path, provider())

    assert data.current_due_date == expected_due_date
