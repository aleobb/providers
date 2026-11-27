from decimal import Decimal

import pytest

from integrations.pdf_extractor.invoice_data import InvoiceData
from integrations.supabase_sync.client import SupabaseError
from integrations.supabase_sync.sync import SupabaseInvoiceSync, SupabaseSyncError


class FakeClient:
    def __init__(self, concepts, comprobantes=None, storage_fails=False):
        self.concepts = concepts
        self.comprobantes = comprobantes or []
        self.storage_fails = storage_fails
        self.uploads, self.updates, self.inserts = [], [], []

    def select(self, table, params=None):
        if table == "conceptos":
            return self.concepts
        if table == "comprobantes":
            return self.comprobantes
        raise AssertionError(table)

    def insert_one(self, table, row):
        self.inserts.append((table, row))
        return {"id": 99}

    def update(self, table, filters, patch):
        self.updates.append((filters, patch))
        return [{"id": 1}]

    def upload(self, bucket, path, data, content_type, upsert=True):
        if self.storage_fails:
            raise SupabaseError("sin espacio")
        self.uploads.append((bucket, path))


def concept(id_, providers, sub=None, ident=None):
    return {
        "id": id_,
        "sub_concepto": sub,
        "Identificador": ident,
        "conceptos__proveed_r": [{"proveedores": {"nombre": n}} for n in providers],
    }


def data(**kw):
    base = dict(
        provider_name="Visa", amount=None, current_due_date="2026-11-10",
        next_due_date="2026-12-10", text_layer_available=True, read_error=False,
        bank_name="Nación", amount_ars=Decimal("1500.50"), amount_usd=None,
        account_identifier="123",
    )
    base.update(kw)
    return InvoiceData(**base)


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "Visa 2026-11.pdf"
    path.write_bytes(b"%PDF-1.4")
    return path


def test_crea_comprobante_y_sube_documento(pdf):
    client = FakeClient([concept(22, ["Nacion", "Visa"]), concept(14, ["Mastercard", "Nacion"])])
    result = SupabaseInvoiceSync(client).sync_invoice(
        pdf, data(), {"file_id": "abc", "link": "https://drive/abc"}
    )
    assert result.created and result.comprobante_id == 99
    table, row = client.inserts[0]
    assert row["concepto_id"] == 22 and row["importe_pesos"] == "1500.50"
    assert "importe_usd" not in row
    assert client.uploads == [("Comprobantes", "99/Visa_2026-11.pdf")]
    patch = client.updates[-1][1]
    assert patch["doc_drive_file_id"] == "abc" and patch["doc_storage_path"] == "99/Visa_2026-11.pdf"


def test_actualiza_y_no_duplica_documento(pdf):
    client = FakeClient(
        [concept(22, ["Nacion", "Visa"])],
        [{"id": 7, "doc_storage_path": "7/x.pdf", "doc_drive_file_id": None}],
    )
    result = SupabaseInvoiceSync(client).sync_invoice(pdf, data())
    assert not result.created and not result.documento_subido
    assert client.uploads == [] and len(client.updates) == 1


def test_varios_conceptos_sin_identificador_detiene(pdf):
    client = FakeClient([concept(22, ["Nacion", "Visa"]), concept(43, ["Nacion", "Visa"])])
    with pytest.raises(SupabaseSyncError, match="varios conceptos"):
        SupabaseInvoiceSync(client).sync_invoice(pdf, data())
    assert client.inserts == []


def test_identificador_desambigua(pdf):
    client = FakeClient([
        concept(22, ["Nacion", "Visa"], ident="111"),
        concept(43, ["Nacion", "Visa"], ident="123"),
    ])
    SupabaseInvoiceSync(client).sync_invoice(pdf, data())
    assert client.inserts[0][1]["concepto_id"] == 43


def test_storage_falla_pero_drive_ok_guarda_enlace(pdf, capsys):
    client = FakeClient([concept(22, ["Nacion", "Visa"])], storage_fails=True)
    result = SupabaseInvoiceSync(client).sync_invoice(pdf, data(), {"file_id": "abc", "link": "l"})
    assert result.drive_file_id == "abc" and result.storage_path is None


def test_storage_falla_sin_drive_es_error(pdf):
    client = FakeClient([concept(22, ["Nacion", "Visa"])], storage_fails=True)
    with pytest.raises(SupabaseSyncError, match="Storage"):
        SupabaseInvoiceSync(client).sync_invoice(pdf, data())


def test_sin_vencimiento(pdf):
    client = FakeClient([concept(22, ["Nacion", "Visa"])])
    with pytest.raises(SupabaseSyncError, match="vencimiento"):
        SupabaseInvoiceSync(client).sync_invoice(pdf, data(current_due_date=None))


def _duplicados(*amounts):
    return [
        {"id": i, "doc_storage_path": None, "doc_drive_file_id": None,
         "importe_pesos": amount, "importe_usd": None, "nro_doc": n}
        for n, (i, amount) in enumerate(zip((10, 11, 12), amounts), start=1)
    ]


def test_duplicados_se_desempatan_por_el_importe(pdf):
    client = FakeClient(
        [concept(22, ["Nacion", "Visa"])], comprobantes=_duplicados("695.00", "1500.50")
    )
    result = SupabaseInvoiceSync(client).sync_invoice(pdf, data())
    assert not result.created and result.comprobante_id == 11
    assert client.updates[0][0] == {"id": "eq.11"} and not client.inserts


def test_duplicados_con_el_mismo_importe_detienen_y_nombran_los_candidatos(pdf):
    client = FakeClient(
        [concept(22, ["Nacion", "Visa"])], comprobantes=_duplicados("1500.50", "1500.50")
    )
    with pytest.raises(SupabaseSyncError, match=r"#10 \(nro_doc 1\), #11 \(nro_doc 2\)"):
        SupabaseInvoiceSync(client).sync_invoice(pdf, data())
    assert not client.updates and not client.inserts


def test_duplicados_sin_importe_coincidente_no_se_adivina(pdf):
    client = FakeClient(
        [concept(22, ["Nacion", "Visa"])], comprobantes=_duplicados("695.00", None)
    )
    with pytest.raises(SupabaseSyncError, match="no permite elegir"):
        SupabaseInvoiceSync(client).sync_invoice(pdf, data())
    assert not client.updates and not client.inserts


def test_los_conceptos_se_leen_una_sola_vez_por_corrida(pdf, tmp_path):
    class Counting(FakeClient):
        concept_reads = 0

        def select(self, table, params=None):
            if table == "conceptos":
                Counting.concept_reads += 1
            return super().select(table, params)

    client = Counting([concept(22, ["Nacion", "Visa"])])
    sync = SupabaseInvoiceSync(client)
    sync.sync_invoice(pdf, data())
    sync.sync_invoice(pdf, data(current_due_date="2026-12-10"))
    assert Counting.concept_reads == 1
