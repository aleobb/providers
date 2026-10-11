from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from integrations.pdf_extractor import _read_text

if TYPE_CHECKING:
    from core.provider import Provider


@dataclass(frozen=True)
class InvoiceData:
    provider_name: str
    amount: Decimal | None
    current_due_date: str | None
    next_due_date: str | None
    text_layer_available: bool
    read_error: bool


_DATE = r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})"
_DEFAULT_PATTERNS: dict[str, tuple[str, ...]] = {
    "amount": (
        r"(?:importe\s+total|total\s+a\s+pagar|monto\s+total|"
        r"importe\s+a\s+pagar|total\s+factura)\s*[:\-]?\s*"
        r"(?:ARS\s*)?\$?\s*(-?[\d.,]+)",
    ),
    "current_due_date": (
        rf"(?:primer\s+vencimiento|1(?:er|ro)\.?\s+vencimiento|"
        rf"vencimiento\s+actual|vto\.?\s+actual|"
        rf"(?<!pr[oó]ximo )vencimiento|fecha\s+de\s+vencimiento)"
        rf"\s*[:\-]?\s*{_DATE}",
    ),
    "next_due_date": (
        rf"(?:pr[oó]ximo\s+(?:vencimiento|vto\.?)|"
        rf"segundo\s+vencimiento|2do\.?\s+(?:vencimiento|vto\.?)|"
        rf"segunda\s+fecha\s+de\s+pago)\s*[:\-]?\s*{_DATE}",
    ),
}


def extract_invoice_data(pdf_path: Path, provider: Provider) -> InvoiceData:
    """Extract common invoice fields from a PDF's selectable text layer."""
    read_error = False
    try:
        text = _read_text(pdf_path)
    except Exception:
        text = ""
        read_error = True

    patterns = {
        **_DEFAULT_PATTERNS,
        **provider.invoice_data_patterns,
    }
    return InvoiceData(
        provider_name=provider.display_name,
        amount=_extract_amount(text, patterns.get("amount", ())),
        current_due_date=_extract_date(
            text, patterns.get("current_due_date", ())
        ),
        next_due_date=_extract_date(text, patterns.get("next_due_date", ())),
        text_layer_available=bool(text.strip()),
        read_error=read_error,
    )


def _extract_amount(text: str, patterns: tuple[str, ...]) -> Decimal | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount = _parse_amount(match.group(1))
            if amount is not None:
                return amount
    return None


def _parse_amount(value: str) -> Decimal | None:
    normalized = value.strip().replace(" ", "")
    if "," in normalized and "." in normalized:
        decimal_separator = "," if normalized.rfind(",") > normalized.rfind(".") else "."
        grouping_separator = "." if decimal_separator == "," else ","
        normalized = normalized.replace(grouping_separator, "")
        if decimal_separator == ",":
            normalized = normalized.replace(",", ".")
    elif "," in normalized:
        trailing_digits = len(normalized) - normalized.rfind(",") - 1
        normalized = (
            normalized.replace(",", ".")
            if trailing_digits in (1, 2)
            else normalized.replace(",", "")
        )
    elif "." in normalized:
        trailing_digits = len(normalized) - normalized.rfind(".") - 1
        if trailing_digits not in (1, 2):
            normalized = normalized.replace(".", "")

    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _extract_date(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        try:
            result = date(
                int(match.group(3)),
                int(match.group(2)),
                int(match.group(1)),
            ).isoformat()
        except (IndexError, ValueError):
            continue
        return result
    return None
