from integrations import pdf_extractor
from integrations.drive_naming import get_drive_target
from providers.edenor import EdenorProvider


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
