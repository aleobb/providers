import csv
from decimal import Decimal

from integrations.pdf_extractor.csv_export import (
    invoice_data_to_csv_row,
    write_invoice_data_csv,
)
from integrations.pdf_extractor.invoice_data import InvoiceData


def test_card_fields_are_written_to_stable_csv_columns(tmp_path):
    data = InvoiceData(
        provider_name="Visa (Prisma)",
        amount=Decimal("1000.50"),
        current_due_date="2026-09-30",
        next_due_date="2026-11-01",
        text_layer_available=True,
        read_error=False,
        bank_name="BBVA",
        current_closing_date="2026-09-18",
        next_closing_date="2026-10-20",
        amount_ars=Decimal("1000.50"),
        amount_usd=Decimal("12.25"),
        account_identifier="12345678",
    )
    csv_path = tmp_path / "facturas.csv"

    write_invoice_data_csv(
        csv_path, [invoice_data_to_csv_row(tmp_path / "resumen.pdf", data)]
    )

    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows == [
        {
            "archivo": "resumen.pdf",
            "proveedor": "Visa (Prisma)",
            "banco": "BBVA",
            "identificador": "12345678",
            "importe": "1000.50",
            "vencimiento_actual": "2026-09-30",
            "proximo_vencimiento": "2026-11-01",
            "cierre_actual": "2026-09-18",
            "proximo_cierre": "2026-10-20",
            "importe_pesos": "1000.50",
            "importe_dolares": "12.25",
            "texto_disponible": "true",
            "error_lectura": "false",
        }
    ]
