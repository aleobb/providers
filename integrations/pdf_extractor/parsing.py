from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_amount(value: str) -> Decimal | None:
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
