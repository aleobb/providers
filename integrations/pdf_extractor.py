from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from core.dates import to_iso

try:
    import pdfplumber

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_FALLBACK = re.compile(r"(\d{2})[/\-](\d{2})[/\-](\d{4})")
InvoiceDateExtractor = Callable[[str], str | None]


def extract_invoice_date(
    pdf_path: Path,
    provider_extractor: InvoiceDateExtractor,
) -> str | None:
    """Extract a date using the provider's parser, then a generic fallback."""
    if not _AVAILABLE:
        return None

    try:
        text = _read_text(pdf_path)
    except Exception:
        return None

    if not text or not text.strip():
        return None

    try:
        date = provider_extractor(text)
    except Exception:
        date = None
    if date:
        return date

    for match in _FALLBACK.finditer(text):
        result = to_iso(match.group(1), match.group(2), match.group(3))
        if result:
            return result
    return None


def determine_invoice_period(
    pdf_path: Path,
    provider_extractor: InvoiceDateExtractor,
) -> str:
    """Return a provider-extracted period or a filename-derived fallback."""
    date = extract_invoice_date(pdf_path, provider_extractor)
    if date:
        return date

    period = _extract_period_from_filename(pdf_path)
    if period == "-":
        return "sin_fecha_pdf_read_error"
    return f"{period}_pdf_read_error"


def _extract_period_from_filename(path: Path) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    if match:
        return match.group(1)
    match = re.search(r"(\d{4}-\d{2})", path.name)
    return match.group(1) if match else "-"


def _read_text(pdf_path: Path, max_pages: int = 2) -> str:
    """Read and join text from the first pages of a PDF."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        parts: list[str] = []
        for page in pdf.pages[:max_pages]:
            text = page.extract_text()
            if text:
                parts.append(text)
        return "\n".join(parts)
