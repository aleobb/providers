from integrations import pdf_extractor
from integrations.drive_naming import get_drive_target
from providers.edenor import EdenorProvider
from providers.mastercard import MastercardProvider
from providers.visa import VisaProvider


def test_invoice_period_prefers_date_extracted_from_pdf(monkeypatch, tmp_path):
    pdf_path = tmp_path / "invoice_2026-04.pdf"
    monkeypatch.setattr(
        pdf_extractor, "extract_invoice_date", lambda *_: "2026-04-15"
    )

    assert (
        pdf_extractor.determine_invoice_period(
            pdf_path, EdenorProvider().extract_invoice_date
        )
        == "2026-04-15"
    )


def test_invoice_period_falls_back_to_filename(monkeypatch, tmp_path):
    pdf_path = tmp_path / "invoice_2026-04.pdf"
    monkeypatch.setattr(pdf_extractor, "extract_invoice_date", lambda *_: None)

    assert (
        pdf_extractor.determine_invoice_period(
            pdf_path, EdenorProvider().extract_invoice_date
        )
        == "2026-04_pdf_read_error"
    )


def test_invoice_period_marks_missing_date(monkeypatch, tmp_path):
    pdf_path = tmp_path / "invoice.pdf"
    monkeypatch.setattr(pdf_extractor, "extract_invoice_date", lambda *_: None)

    assert (
        pdf_extractor.determine_invoice_period(
            pdf_path, EdenorProvider().extract_invoice_date
        )
        == "sin_fecha_pdf_read_error"
    )


def test_drive_target_uses_generic_service_naming():
    target = get_drive_target(EdenorProvider(), "2026-04")

    assert target.subfolder_parts == ["Facturas de Productos y Servicios", "Edenor"]
    assert target.filename == "Fra. Edenor - 2026-04-01.pdf"


def test_visa_owns_its_invoice_date_format():
    provider = VisaProvider()

    assert provider.extract_invoice_date("CIERRE ACTUAL: 26 Mar 26") == (
        "2026-03-26"
    )


def test_card_provider_owns_its_drive_naming():
    visa_target = get_drive_target(
        VisaProvider(), "2026-03", banco="Banco de prueba"
    )
    mastercard_target = get_drive_target(
        MastercardProvider(), "2026-04", banco="Banco de prueba"
    )

    assert visa_target.subfolder_parts == [
        "Tarjetas de Credito",
        "Visa",
        "Banco de prueba",
    ]
    assert visa_target.filename == (
        "Visa Banco de prueba - Resumen F.Cierre 2026-03-01.pdf"
    )
    assert mastercard_target.subfolder_parts == [
        "Tarjetas de Credito",
        "Mastercard",
        "Banco de prueba",
    ]
    assert mastercard_target.filename == (
        "Mastercard Banco de prueba - Resumen F.Cierre 2026-04-01.pdf"
    )
