from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .parsing import parse_amount


@dataclass(frozen=True)
class CardStatementData:
    bank_name: str | None
    current_due_date: str
    next_due_date: str
    current_closing_date: str
    next_closing_date: str
    amount_ars: Decimal
    amount_usd: Decimal


_SPANISH_MONTHS = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}
_DATE_WORD = r"\d{2}\s+[A-Za-z]{3}\.?\s+\d{2}"
_DATE_NUMERIC = r"\d{1,2}[/.-]\d{1,2}[/.-]\d{4}"
_FLEX_DATE_WORD = (
    r"\d(?:[ \t]*\d)?[ \t]+(?:[A-Za-z][ \t]*){3}\.?[ \t]+\d[ \t]*\d"
)
_DATE_DASHED = r"\d{2}-[A-Za-z]{3}\.?-\d{2}"
_ICBC_LABELLED_DATE = rf"(?:{_DATE_NUMERIC}|{_DATE_DASHED})"
_VISA_CURRENT_CLOSE = re.compile(
    rf"CIERRE\s+ACTUAL:\s*({_DATE_WORD})", re.IGNORECASE
)
_VISA_CURRENT_DUE_AND_BALANCES = re.compile(
    rf"^({_DATE_WORD})\s+([\d.,]+)\s+([\d.,]+-?)\s+[\d.,]+"
    r"(?:\s+(-,--|[\d.,]+))?",
    re.IGNORECASE | re.MULTILINE,
)
_VISA_NEXT_CLOSE = re.compile(
    rf"(?:VTO\.\s+ANTERIOR\s+({_DATE_WORD})\b.*?"
    rf"PR[ÓO]XIMO\s+CIERRE\s+({_DATE_WORD}))"
    rf"|(?:^({_DATE_WORD})\s+[\d.,-]+\s+[\d.,]+\s+({_DATE_WORD}))",
    re.IGNORECASE | re.MULTILINE,
)
_VISA_NEXT_DUE = re.compile(
    rf"(?:CIERRE\s+ANTERIOR\s+({_DATE_WORD})\b.*?"
    rf"PR[ÓO]XIMO\s+VTO\.?\s+({_DATE_WORD}))"
    rf"|(?:^({_DATE_WORD})\s+[\d.,]+\s+({_DATE_WORD}))",
    re.IGNORECASE | re.MULTILINE,
)
_VISA_FLEX_CURRENT_CLOSE = re.compile(
    rf"CIERRE\s+ACTUAL:\s*({_FLEX_DATE_WORD})", re.IGNORECASE
)
_VISA_FLEX_CURRENT_DUE_AND_BALANCES = re.compile(
    rf"^\s*.*?\b({_FLEX_DATE_WORD})\s*([\d.,]+)\s+([\d.,]+-?)\s+[\d.,]+"
    r"(?:\s+(-,--|[\d.,]+))?",
    re.IGNORECASE | re.MULTILINE,
)
_VISA_FLEX_NEXT_CLOSE = re.compile(
    rf"VTO\.\s+ANTERIOR\s+({_FLEX_DATE_WORD})\b.*?"
    rf"PR[ÓO]XIMO\s+CIERRE\s+({_FLEX_DATE_WORD})",
    re.IGNORECASE,
)
_VISA_FLEX_NEXT_DUE = re.compile(
    rf"CIERRE\s+ANTERIOR\s+({_FLEX_DATE_WORD})\b.*?"
    rf"PR[ÓO]XIMO\s+VTO\.?\s+({_FLEX_DATE_WORD})",
    re.IGNORECASE,
)
_BBVA_PATTERNS = {
    "current_closing_date": rf"CIERRE\s+ACTUAL\s+({_DATE_DASHED})",
    "current_due_date": rf"VENCIMIENTO\s+ACTUAL\s+({_DATE_DASHED})",
    "amount_ars": r"SALDO\s+ACTUAL\s+\$\s+([\d.,]+)",
    "amount_usd": r"SALDO\s+ACTUAL\s+U\$S\s+([\d.,]+)",
    "next_closing_date": rf"PR[ÓO]XIMO\s+CIERRE\s+({_DATE_DASHED})",
    "next_due_date": rf"PR[ÓO]XIMO\s+VENCIMIENTO\s+({_DATE_DASHED})",
}
_ICBC_PATTERN = re.compile(
    rf"U\$S\s*([\d.,]+?)({_DATE_DASHED})\s+"
    rf"({_DATE_DASHED})\s+([\d.,]+)\s+([\d.,]+)"
    rf".*?[\d.,]+\s+({_DATE_DASHED})\s+({_DATE_DASHED})",
    re.IGNORECASE | re.DOTALL,
)
_ICBC_LABELLED_STATE = re.compile(
    rf"ESTADO\s+DE\s+CUENTA\s+AL\s*:\s*({_ICBC_LABELLED_DATE})\s+"
    r"SALDO\s+ACTUAL\s*:\s*\$?\s*(-?[\d.,]+)\s+"
    r"U\$S\s*(-?[\d.,]+)",
    re.IGNORECASE,
)
_ICBC_LABELLED_DUE = re.compile(
    rf"VENCIMIENTO\s+ACTUAL\s*:\s*({_ICBC_LABELLED_DATE})", re.IGNORECASE
)
_ICBC_LABELLED_NEXT_CLOSE = re.compile(
    rf"PR[ÓO]XIMO\s+CIERRE\s*:\s*({_ICBC_LABELLED_DATE})", re.IGNORECASE
)
_ICBC_LABELLED_NEXT_DUE = re.compile(
    rf"PR[ÓO]XIMO\s+VENCIMIENTO\s*:\s*({_ICBC_LABELLED_DATE})",
    re.IGNORECASE,
)


def _parse_spanish_date(value: str) -> str | None:
    normalized = re.sub(r"(?<=\d)\s+(?=\d)", "", value.strip())
    normalized = re.sub(r"(?<=[A-Za-z])\s+(?=[A-Za-z])", "", normalized)
    parts = re.split(r"[\s-]+", normalized)
    if len(parts) < 3:
        return None
    try:
        day = int(parts[0])
        month_name = "".join(parts[1:-1]).rstrip(".").lower()
        month = _SPANISH_MONTHS[month_name]
        year = 2000 + int(parts[-1])
        return date(year, month, day).isoformat()
    except (KeyError, ValueError):
        return None


def _parse_statement_date(value: str) -> str | None:
    numeric_date = re.fullmatch(
        r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", value.strip()
    )
    if numeric_date is not None:
        try:
            return date(
                int(numeric_date.group(3)),
                int(numeric_date.group(2)),
                int(numeric_date.group(1)),
            ).isoformat()
        except ValueError:
            return None
    if "-" not in value:
        return _parse_spanish_date(value)
    return _parse_spanish_date(value.replace("-", " "))


def _build_statement(
    bank_name: str | None,
    current_due_date: str,
    next_due_date: str,
    current_closing_date: str,
    next_closing_date: str,
    amount_ars: str,
    amount_usd: str,
) -> CardStatementData | None:
    current_due = _parse_statement_date(current_due_date)
    next_due = _parse_statement_date(next_due_date)
    current_close = _parse_statement_date(current_closing_date)
    next_close = _parse_statement_date(next_closing_date)
    ars = parse_amount(amount_ars)
    usd = parse_amount(amount_usd)
    if (
        current_due is None
        or next_due is None
        or current_close is None
        or next_close is None
        or ars is None
        or usd is None
    ):
        return None
    return CardStatementData(
        bank_name=bank_name,
        current_due_date=current_due,
        next_due_date=next_due,
        current_closing_date=current_close,
        next_closing_date=next_close,
        amount_ars=ars,
        amount_usd=usd,
    )


def parse_visa_nacion(text: str) -> CardStatementData | None:
    if "VISA" not in text.upper():
        return None
    current_close = _VISA_CURRENT_CLOSE.search(text)
    current_due = _VISA_CURRENT_DUE_AND_BALANCES.search(text)
    next_close = _VISA_NEXT_CLOSE.search(text)
    next_due = _VISA_NEXT_DUE.search(text)
    if (
        current_close is None
        or current_due is None
        or next_close is None
        or next_due is None
    ):
        return None
    next_close_date = next_close.group(2) or next_close.group(4)
    next_due_date = next_due.group(2) or next_due.group(4)
    return _build_statement(
        "Nación",
        current_due.group(1),
        next_due_date,
        current_close.group(1),
        next_close_date,
        current_due.group(2),
        current_due.group(3),
    )


def parse_visa_statement(text: str) -> CardStatementData | None:
    """Parse the shared Visa statement layout without guessing its issuing bank."""
    statement = parse_visa_nacion(text)
    if statement is not None:
        return statement
    if "VISA" not in text.upper():
        return None

    current_close = _VISA_FLEX_CURRENT_CLOSE.search(text)
    current_due = _VISA_FLEX_CURRENT_DUE_AND_BALANCES.search(text)
    next_close = _VISA_FLEX_NEXT_CLOSE.search(text)
    next_due = _VISA_FLEX_NEXT_DUE.search(text)
    if (
        current_close is None
        or current_due is None
        or next_close is None
        or next_due is None
    ):
        return None

    return _build_statement(
        None,
        current_due.group(1),
        next_due.group(2),
        current_close.group(1),
        next_close.group(2),
        current_due.group(2),
        current_due.group(3),
    )


def parse_mastercard_bbva(text: str) -> CardStatementData | None:
    if "MASTERCARD" not in text.upper() or "BANCO BBVA" not in text.upper():
        return None
    values: dict[str, str] = {}
    for field, pattern in _BBVA_PATTERNS.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match is None:
            return None
        values[field] = match.group(1)
    return _build_statement(
        "BBVA",
        values["current_due_date"],
        values["next_due_date"],
        values["current_closing_date"],
        values["next_closing_date"],
        values["amount_ars"],
        values["amount_usd"],
    )


def parse_mastercard_icbc(text: str) -> CardStatementData | None:
    upper_text = text.upper()
    if "MASTERCARD" not in upper_text:
        return None

    is_icbc = (
        "ENTIDAD:" in upper_text
        or "INDUSTRIAL AND COMMERCIAL BANK OF CHINA" in upper_text
        or "MASTERCARD ICBC" in upper_text
    )
    if not is_icbc:
        return None

    labelled_state = _ICBC_LABELLED_STATE.search(text)
    labelled_due = _ICBC_LABELLED_DUE.search(text)
    labelled_next_close = _ICBC_LABELLED_NEXT_CLOSE.search(text)
    labelled_next_due = _ICBC_LABELLED_NEXT_DUE.search(text)
    if all(
        match is not None
        for match in (
            labelled_state,
            labelled_due,
            labelled_next_close,
            labelled_next_due,
        )
    ):
        assert labelled_state is not None
        assert labelled_due is not None
        assert labelled_next_close is not None
        assert labelled_next_due is not None
        return _build_statement(
            "ICBC",
            labelled_due.group(1),
            labelled_next_due.group(1),
            labelled_state.group(1),
            labelled_next_close.group(1),
            labelled_state.group(2),
            labelled_state.group(3),
        )

    if "ENTIDAD:" not in upper_text:
        return None
    match = _ICBC_PATTERN.search(text)
    if match is None:
        return None
    return _build_statement(
        "ICBC",
        match.group(3),
        match.group(7),
        match.group(2),
        match.group(6),
        match.group(4),
        match.group(1),
    )


def detect_card_provider(text: str) -> str | None:
    if parse_mastercard_bbva(text) or parse_mastercard_icbc(text):
        return "mastercard"
    if parse_visa_statement(text):
        return "visa"
    return None
