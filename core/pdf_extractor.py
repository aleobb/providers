from __future__ import annotations

import re
from pathlib import Path

try:
    import pdfplumber
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

# ---------------------------------------------------------------------------
# Meses abreviados que usa Visa en el resumen (ej. "26 Mar 26")
# ---------------------------------------------------------------------------
_MES_ABBR: dict[str, str] = {
    'ene': '01', 'feb': '02', 'mar': '03', 'abr': '04',
    'may': '05', 'jun': '06', 'jul': '07', 'ago': '08',
    'sep': '09', 'oct': '10', 'nov': '11', 'dic': '12',
}

# ---------------------------------------------------------------------------
# Patrones estándar DD/MM/YYYY.
# Nota sobre encoding: los PDFs argentinos codifican mal los caracteres
# acentuados — la 'ó' puede aparecer como espacio, 'n', 'N', o simplemente
# desaparecer. Se usa '.' para tolerar cualquier carácter en esa posición.
# Cada patrón captura (DD, MM, YYYY) en grupos 1, 2, 3.
# ---------------------------------------------------------------------------
_PATTERNS: dict[str, list[str]] = {
    "edenor": [
        # "Emisi n 27/03/2026"  o  "Emisión 27/03/2026"
        r"emisi.n\s+(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"fecha.+?vencimiento\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    "edesur": [
        r"emisi.n\s+(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"fecha.+?vencimiento\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        # Edesur no siempre etiqueta la emisión — cae al fallback general
    ],
    "metrogas": [
        # "FECHA DE EMISI N: 24/04/2026"
        r"fecha\s+de\s+emisi.n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"emisi.n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    "telecentro": [
        # "VENCIMIENTO 04/05/2026" — la Fecha del JSON está corrupta
        r"vencimiento\s+(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"fecha.+?vencimiento\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    "claro": [
        r"emisi.n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"fecha\s+factura\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"per[ií]odo\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    "aysa": [
        # "Fechadeemisi n:11/04/2026" — sin espacios entre palabras
        r"fechadeemisi.n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"emisi.n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"vencimiento\s+(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    "mastercard": [
        r"fecha\s+de\s+cierre\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"cierre\s*[:\-]\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"resumen\s+al\s+(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    # Visa tiene su propio extractor por el formato "DD Mes YY"
}

# Fallback: primer DD/MM/YYYY en el documento
_FALLBACK = re.compile(r"(\d{2})[/\-](\d{2})[/\-](\d{4})")


def extract_invoice_date(pdf_path: Path, provider_name: str) -> str | None:
    """
    Extrae la fecha relevante del PDF y la devuelve como YYYY-MM-DD.

    Orden de intento:
      1. Extractor específico del proveedor.
      2. Primer DD/MM/YYYY válido en el documento (fallback general).

    Devuelve None si el PDF no tiene texto extraíble, no se encuentra ninguna
    fecha válida, o pdfplumber no está instalado.
    """
    if not _AVAILABLE:
        return None

    try:
        text = _read_text(pdf_path)
    except Exception:
        return None

    if not text or not text.strip():
        return None

    name = provider_name.lower()

    # Visa usa formato "DD Mes YY" — extractor dedicado
    if name == "visa":
        return _extract_visa_cierre(text)

    # Patrones estándar DD/MM/YYYY
    for pat in _PATTERNS.get(name, []):
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            result = _to_iso(m.group(1), m.group(2), m.group(3))
            if result:
                return result

    # Fallback general: primer DD/MM/YYYY válido en el documento
    for m in _FALLBACK.finditer(text):
        result = _to_iso(m.group(1), m.group(2), m.group(3))
        if result:
            return result

    return None


# ---------------------------------------------------------------------------
# Extractor dedicado para Visa
# ---------------------------------------------------------------------------

def _extract_visa_cierre(text: str) -> str | None:
    """
    Extrae la fecha de cierre del resumen Visa.

    El PDF de Visa/Prisma usa el formato  "CIERRE ACTUAL: 26 Mar 26"
    (día entero, mes abreviado en español, año de 2 dígitos).
    """
    m = re.search(
        r"cierre\s+actual\s*[:\-]?\s*(\d{1,2})\s+"
        r"(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\s+(\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if m:
        day = int(m.group(1))
        month = _MES_ABBR.get(m.group(2).lower())
        year = 2000 + int(m.group(3))
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month}-{day:02d}"
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_text(pdf_path: Path, max_pages: int = 2) -> str:
    """Lee las primeras N páginas del PDF y devuelve el texto unido."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        parts: list[str] = []
        for page in pdf.pages[:max_pages]:
            t = page.extract_text()
            if t:
                parts.append(t)
        return "\n".join(parts)


def _to_iso(dd: str, mm: str, yyyy: str) -> str | None:
    """Convierte DD, MM, YYYY a 'YYYY-MM-DD'. Devuelve None si los valores no son válidos."""
    try:
        d, mo, y = int(dd), int(mm), int(yyyy)
        if 1 <= mo <= 12 and 1 <= d <= 31 and 2000 <= y <= 2100:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    except (ValueError, TypeError):
        pass
    return None
