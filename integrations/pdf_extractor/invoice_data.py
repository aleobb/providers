from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from integrations.pdf_extractor.card_statement import CardStatementData
from integrations.pdf_extractor.extractor import _read_text
from integrations.pdf_extractor.parsing import parse_amount

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
    bank_name: str | None = None
    current_closing_date: str | None = None
    next_closing_date: str | None = None
    amount_ars: Decimal | None = None
    amount_usd: Decimal | None = None


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


def extract_invoice_data(
    pdf_path: Path,
    provider: Provider,
    *,
    max_pages: int | None = 2,
    bank_name: str | None = None,
) -> InvoiceData:
    """Extract common invoice fields from a PDF's selectable text layer."""
    read_error = False
    try:
        text = (
            _read_text(pdf_path)
            if max_pages == 2
            else _read_text(pdf_path, max_pages=max_pages)
        )
    except Exception:
        text = ""
        read_error = True

    return extract_invoice_data_from_text(
        text, provider, read_error=read_error, bank_name=bank_name
    )


def extract_invoice_data_from_text(
    text: str,
    provider: Provider,
    *,
    read_error: bool = False,
    bank_name: str | None = None,
) -> InvoiceData:
    """Extract invoice fields from already-read PDF text."""
    patterns = {
        **_DEFAULT_PATTERNS,
        **provider.invoice_data_patterns,
    }
    card_data: CardStatementData | None = provider.extract_card_statement_data(
        text
    )
    amount = _extract_amount(text, patterns.get("amount", ()))
    if amount is None and card_data is not None:
        amount = card_data.amount_ars
    return InvoiceData(
        provider_name=provider.display_name,
        amount=amount,
        current_due_date=(
            _extract_date(text, patterns.get("current_due_date", ()))
            or (card_data.current_due_date if card_data else None)
        ),
        next_due_date=(
            _extract_date(text, patterns.get("next_due_date", ()))
            or (card_data.next_due_date if card_data else None)
        ),
        text_layer_available=bool(text.strip()),
        read_error=read_error,
        bank_name=bank_name or (card_data.bank_name if card_data else None),
        current_closing_date=(
            card_data.current_closing_date if card_data else None
        ),
        next_closing_date=card_data.next_closing_date if card_data else None,
        amount_ars=card_data.amount_ars if card_data else None,
        amount_usd=card_data.amount_usd if card_data else None,
    )


def _extract_amount(text: str, patterns: tuple[str, ...]) -> Decimal | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount = parse_amount(match.group(1))
            if amount is not None:
                return amount
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
