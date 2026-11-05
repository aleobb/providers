from decimal import Decimal
from pathlib import Path

import pytest

from integrations.airtable.sync import (
    AirtableConfig,
    AirtableConfigurationError,
    AirtableInvoiceSync,
    AirtableSyncError,
)
from integrations.pdf_extractor.invoice_data import InvoiceData


class FakeTable:
    def __init__(self, records=None):
        self.records = records or []
        self.created = []
        self.updated = []
        self.formulas = []
        self.uploaded_attachments = []

    def all(self, *, formula=None, fields=None):
        self.formulas.append(formula)
        return self.records

    def create(self, fields, *, typecast):
        assert typecast is True
        self.created.append(fields)
        return {"id": "rec-new"}

    def update(self, record_id, fields, *, typecast):
        assert typecast is True
        self.updated.append((record_id, fields))
        return {"id": record_id, "fields": fields}

    def upload_attachment(
        self, record_id, field, filename, *, content_type
    ):
        self.uploaded_attachments.append(
            (record_id, field, Path(filename), content_type)
        )


class FakeApi:
    def __init__(self, tables):
        self.tables = tables

    def table(self, _base_id, name):
        return self.tables[name]


def _data(**overrides):
    values = {
        "provider_name": "Visa (Prisma)",
        "amount": Decimal("1234.50"),
        "current_due_date": "2026-11-05",
        "next_due_date": None,
        "text_layer_available": True,
        "read_error": False,
        "bank_name": "Banco Galicia",
        "current_closing_date": "2026-10-18",
        "next_closing_date": None,
        "amount_ars": Decimal("1234.50"),
        "amount_usd": None,
    }
    return InvoiceData(**(values | overrides))


def _pdf(tmp_path, filename="invoice.pdf"):
    path = tmp_path / filename
    path.write_bytes(b"%PDF-1.4\n% test document\n")
    return path


def _sync(concept_records=None, invoice_records=None):
    invoices = FakeTable(invoice_records)
    concepts = FakeTable(concept_records)
    config = AirtableConfig(token="token", base_id="base")
    sync = AirtableInvoiceSync(
        config,
        api=FakeApi({"Comprobantes": invoices, "Conceptos": concepts}),
    )
    return sync, invoices, concepts


def test_create_invoice_with_concept_and_extracted_fields(tmp_path):
    sync, invoices, concepts = _sync(
        concept_records=[
            {"id": "rec-concept", "fields": {"Nombre": "Visa Galicia"}}
        ]
    )
    path = _pdf(tmp_path, "visa_resumen.pdf")

    result = sync.sync_invoice(path, _data())

    assert result.record_id == "rec-new"
    assert result.created is True
    fields = invoices.created[0]
    assert fields == {
        "Concepto": ["rec-concept"],
        "Fecha Vto.": "2026-11-05",
        "Cierre Actual": "2026-10-18",
        "Importe Pesos": "1234.50",
    }
    assert concepts.formulas
    assert invoices.uploaded_attachments == [
        ("rec-new", "Doc.", path, "application/pdf")
    ]
    assert result.attachment_uploaded is True


def test_update_existing_invoice_without_clearing_missing_values(tmp_path):
    sync, invoices, _ = _sync(
        concept_records=[
            {"id": "rec-concept", "fields": {"Nombre": "Visa Galicia"}}
        ],
        invoice_records=[
            {
                "id": "rec-existing",
                "fields": {
                    "Concepto": ["rec-concept"],
                    "Fecha Vto.": "2026-11-05",
                },
            }
        ],
    )

    path = _pdf(tmp_path)
    result = sync.sync_invoice(path, _data())

    assert result.record_id == "rec-existing"
    assert result.created is False
    assert invoices.created == []
    assert invoices.updated[0][0] == "rec-existing"
    assert "Prox.Vto." not in invoices.updated[0][1]
    assert invoices.uploaded_attachments == [
        ("rec-existing", "Doc.", path, "application/pdf")
    ]


def test_existing_attachment_is_not_replaced_on_update(tmp_path):
    path = _pdf(tmp_path)
    sync, invoices, _ = _sync(
        concept_records=[
            {"id": "rec-concept", "fields": {"Nombre": "Visa Galicia"}}
        ],
        invoice_records=[
            {
                "id": "rec-existing",
                "fields": {
                    "Concepto": ["rec-concept"],
                    "Fecha Vto.": "2026-11-05",
                    "Doc.": [{"filename": "previous_document.pdf"}],
                },
            }
        ],
    )

    result = sync.sync_invoice(path, _data())

    assert result.attachment_uploaded is False
    assert invoices.uploaded_attachments == []


def test_missing_concept_does_not_create_invoice(tmp_path):
    sync, invoices, _ = _sync()

    with pytest.raises(AirtableSyncError, match="No se encontró un concepto"):
        sync.sync_invoice(_pdf(tmp_path), _data())

    assert invoices.created == []
    assert invoices.updated == []


def test_ambiguous_concept_does_not_create_invoice(tmp_path):
    sync, invoices, _ = _sync(
        concept_records=[
            {"id": "rec-one", "fields": {"Nombre": "Visa Galicia"}},
            {"id": "rec-two", "fields": {"Nombre": "Visa Galicia Compartida"}},
        ]
    )

    with pytest.raises(AirtableSyncError, match="varios conceptos"):
        sync.sync_invoice(_pdf(tmp_path), _data())

    assert invoices.created == []


def test_ambiguous_invoice_is_not_updated(tmp_path):
    sync, invoices, _ = _sync(
        concept_records=[
            {"id": "rec-concept", "fields": {"Nombre": "Visa Galicia"}}
        ],
        invoice_records=[
            {
                "id": "rec-one",
                "fields": {
                    "Concepto": ["rec-concept"],
                    "Fecha Vto.": "2026-11-05",
                },
            },
            {
                "id": "rec-two",
                "fields": {
                    "Concepto": ["rec-concept"],
                    "Fecha Vto.": "2026-11-05",
                },
            },
        ],
    )

    with pytest.raises(AirtableSyncError, match="varios comprobantes"):
        sync.sync_invoice(_pdf(tmp_path), _data())

    assert invoices.created == []
    assert invoices.updated == []


def test_config_requires_token_and_base_id(monkeypatch):
    monkeypatch.delenv("AIRTABLE_TOKEN", raising=False)
    monkeypatch.delenv("AIRTABLE_BASE_ID", raising=False)

    with pytest.raises(AirtableConfigurationError, match="AIRTABLE_TOKEN"):
        AirtableConfig.from_env()


def test_sync_accepts_pathlike_pdf_path(tmp_path):
    sync, _, _ = _sync(
        concept_records=[
            {"id": "rec-concept", "fields": {"Nombre": "Visa Galicia"}}
        ]
    )

    result = sync.sync_invoice(_pdf(tmp_path), _data())

    assert result.created is True


def test_concept_match_requires_both_provider_and_bank(tmp_path):
    sync, invoices, _ = _sync(
        concept_records=[
            {"id": "rec-other-bank", "fields": {"Nombre": "Visa BBVA"}},
        ]
    )

    with pytest.raises(AirtableSyncError, match="No se encontró un concepto"):
        sync.sync_invoice(_pdf(tmp_path, "visa.pdf"), _data())

    assert invoices.created == []


def test_provider_parenthetical_qualifier_is_not_required_in_concept_name(
    tmp_path,
):
    sync, invoices, _ = _sync(
        concept_records=[
            {"id": "rec-concept", "fields": {"Nombre": "Mastercard ICBC"}}
        ]
    )
    data = _data(
        provider_name="Mastercard (Mis Consultas)",
        bank_name="ICBC",
    )

    result = sync.sync_invoice(_pdf(tmp_path, "mastercard.pdf"), data)

    assert result.created is True
    assert invoices.created[0]["Concepto"] == ["rec-concept"]


def test_missing_due_date_does_not_write_to_airtable(tmp_path):
    sync, invoices, concepts = _sync(
        concept_records=[
            {"id": "rec-concept", "fields": {"Nombre": "Visa Galicia"}}
        ]
    )

    with pytest.raises(AirtableSyncError, match="No se encontró el vencimiento"):
        sync.sync_invoice(
            _pdf(tmp_path), _data(current_due_date=None)
        )

    assert invoices.created == []
    assert concepts.formulas == []


def test_missing_document_does_not_create_comprobante(tmp_path):
    sync, invoices, concepts = _sync(
        concept_records=[
            {"id": "rec-concept", "fields": {"Nombre": "Visa Galicia"}}
        ]
    )

    with pytest.raises(AirtableSyncError, match="No se encontró el PDF"):
        sync.sync_invoice(tmp_path / "missing.pdf", _data())

    assert invoices.created == []
    assert invoices.updated == []
    assert concepts.formulas == []


def test_non_pdf_document_does_not_create_comprobante(tmp_path):
    sync, invoices, concepts = _sync(
        concept_records=[
            {"id": "rec-concept", "fields": {"Nombre": "Visa Galicia"}}
        ]
    )
    path = tmp_path / "invoice.txt"
    path.write_text("not a PDF")

    with pytest.raises(AirtableSyncError, match="no es un PDF"):
        sync.sync_invoice(path, _data())

    assert invoices.created == []
    assert concepts.formulas == []
