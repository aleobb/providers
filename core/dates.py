from __future__ import annotations

import re


def extract_date_from_patterns(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            result = to_iso(match.group(1), match.group(2), match.group(3))
            if result:
                return result
    return None


def to_iso(day: str, month: str, year: str) -> str | None:
    try:
        day_number, month_number, year_number = int(day), int(month), int(year)
        if (
            1 <= month_number <= 12
            and 1 <= day_number <= 31
            and 2000 <= year_number <= 2100
        ):
            return f"{year_number:04d}-{month_number:02d}-{day_number:02d}"
    except (ValueError, TypeError):
        pass
    return None
