from __future__ import annotations

import calendar
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
    holder_name: str | None = None
    account_identifier: str | None = None


_DATE = r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})"
_DEFAULT_PATTERNS: dict[str, tuple[str, ...]] = {
    "account_identifier": (
        r"\bcuenta\s+de\s+servicios?\s*[:#\-]?\s*(\d[\d ./\-]*)",
        r"\b(?:n[uú]mero|nro\.?|n[°º])\s*(?:de\s*)?"
        r"(?:cliente|cuenta|servicio|socio)\s*[:#\-]?\s*(\d[\d ./\-]*)",
        r"\bcliente\s+n[°ºo.]?\s*[:#\-]?\s*(\d[\d ./\-]*)",
    ),
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
        **{
            field: (
                *provider_patterns,
                *_DEFAULT_PATTERNS.get(field, ()),
            )
            for field, provider_patterns in provider.invoice_data_patterns.items()
        },
    }
    card_data: CardStatementData | None = provider.extract_card_statement_data(
        text
    )
    amount = _extract_amount(text, patterns.get("amount", ()))
    if amount is None and card_data is not None:
        amount = card_data.amount_ars
    current_due_date = (
        _extract_date(text, patterns.get("current_due_date", ()))
        or (card_data.current_due_date if card_data else None)
    )
    next_due_date = (
        _extract_date(text, patterns.get("next_due_date", ()))
        or (card_data.next_due_date if card_data else None)
    )
    estimate_months = getattr(
        provider, "estimated_next_due_date_months", None
    )
    if next_due_date is None and current_due_date and estimate_months is not None:
        next_due_date = _estimate_next_due_date(
            current_due_date, estimate_months
        )
    return InvoiceData(
        provider_name=provider.display_name,
        amount=amount,
        current_due_date=current_due_date,
        next_due_date=next_due_date,
        text_layer_available=bool(text.strip()),
        read_error=read_error,
        bank_name=bank_name or (card_data.bank_name if card_data else None),
        current_closing_date=(
            card_data.current_closing_date if card_data else None
        ),
        next_closing_date=card_data.next_closing_date if card_data else None,
        amount_ars=card_data.amount_ars if card_data else None,
        amount_usd=card_data.amount_usd if card_data else None,
        holder_name=_extract_holder_name(
            text, patterns.get("holder_name", ())
        ),
        account_identifier=_extract_account_identifier(
            text, patterns.get("account_identifier", ())
        ),
    )


def _estimate_next_due_date(current_due_date: str, months: int) -> str:
    if months < 1:
        raise ValueError("estimated_next_due_date_months debe ser positivo.")
    current = date.fromisoformat(current_due_date)
    month_index = current.year * 12 + current.month - 1 + months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    day = min(current.day, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()


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


_HOLDER_NAME_PATTERNS = (
    r"\b(?:titular(?:\s+de\s+(?:la\s+)?(?:cuenta|servicio))?|"
    r"nombre\s+del\s+titular|receptor)\s*[:\-]\s*([^\r\n]+)",
    r"(?<!de )\bcliente\s*[:\-]\s*([^\r\n]+)",
)
_HOLDER_TRAILING_LABELS = re.compile(
    r"\s+(?:CIERRE\s+ACTUAL|VENCIMIENTO|N[°º]\s*DE\s*CUENTA|"
    r"NRO\.?\s*DE\s*CUENTA|CUIT|DNI)\b.*$",
    re.IGNORECASE,
)


def _extract_holder_name(
    text: str, provider_patterns: tuple[str, ...] = ()
) -> str | None:
    for pattern in (*provider_patterns, *_HOLDER_NAME_PATTERNS):
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match is None:
            continue
        holder_name = _HOLDER_TRAILING_LABELS.sub("", match.group(1))
        holder_name = re.sub(r"\s+", " ", holder_name).strip(" \t:;,-")
        if holder_name and re.search(r"[^\W\d_]", holder_name):
            return holder_name
    return None


def _extract_account_identifier(
    text: str, patterns: tuple[str, ...]
) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match is None:
            continue
        identifier = re.sub(r"\s+", " ", match.group(1)).strip(
            " \t:;,#./-"
        )
        if identifier and any(character.isdigit() for character in identifier):
            return identifier
    return None
