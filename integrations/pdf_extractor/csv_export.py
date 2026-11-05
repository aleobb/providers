from __future__ import annotations

import csv
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

from .invoice_data import InvoiceData

CSV_FIELDS = (
    "archivo",
    "proveedor",
    "banco",
    "importe",
    "vencimiento_actual",
    "proximo_vencimiento",
    "cierre_actual",
    "proximo_cierre",
    "importe_pesos",
    "importe_dolares",
    "texto_disponible",
    "error_lectura",
)


def invoice_data_to_csv_row(path: Path, data: InvoiceData) -> dict[str, str]:
    return {
        "archivo": path.name,
        "proveedor": data.provider_name,
        "banco": data.bank_name or "",
        "importe": _format_amount(data.amount),
        "vencimiento_actual": data.current_due_date or "",
        "proximo_vencimiento": data.next_due_date or "",
        "cierre_actual": data.current_closing_date or "",
        "proximo_cierre": data.next_closing_date or "",
        "importe_pesos": _format_amount(data.amount_ars),
        "importe_dolares": _format_amount(data.amount_usd),
        "texto_disponible": str(data.text_layer_available).lower(),
        "error_lectura": str(data.read_error).lower(),
    }


def write_invoice_data_csv(
    csv_path: Path, rows: Iterable[dict[str, str]]
) -> None:
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _format_amount(amount: Decimal | None) -> str:
    return format(amount, "f") if amount is not None else ""
