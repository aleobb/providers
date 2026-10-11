from __future__ import annotations

import re
from datetime import datetime

from playwright.async_api import Page


async def extract_period(page: Page) -> str:
    """Extract the statement period from the current Visa page."""
    try:
        text = await page.inner_text("body")

        cierre_patterns = [
            r'fecha\s+de\s+cierre\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})',
            r'f\.?\s*cierre\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})',
            r'cierre\s*[:\-]\s*(\d{2})[/\-](\d{2})[/\-](\d{4})',
        ]
        for pattern in cierre_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                day, month, year = match.group(1), match.group(2), match.group(3)
                return f"{year}-{month}-{day}"

        meses = {
            "enero": "01",
            "febrero": "02",
            "marzo": "03",
            "abril": "04",
            "mayo": "05",
            "junio": "06",
            "julio": "07",
            "agosto": "08",
            "septiembre": "09",
            "octubre": "10",
            "noviembre": "11",
            "diciembre": "12",
        }
        match = re.search(
            r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
            r'septiembre|octubre|noviembre|diciembre)\s+(\d{4})',
            text,
            re.IGNORECASE,
        )
        if match:
            month = meses.get(match.group(1).lower(), "01")
            return f"{match.group(2)}-{month}"

        match = re.search(r"(\d{2})/(\d{4})", text)
        if match:
            return f"{match.group(2)}-{match.group(1)}"

        match = re.search(r"20\d\d-\d\d", text)
        if match:
            return match.group(0)
    except Exception:
        pass
    return datetime.now().strftime("%Y-%m")
