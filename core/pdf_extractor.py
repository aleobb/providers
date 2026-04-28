from __future__ import annotations

import re
from pathlib import Path

try:
    import pdfplumber
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

# ---------------------------------------------------------------------------
# Patrones específicos por proveedor.
# Cada patrón captura (DD, MM, YYYY) en grupos 1, 2, 3.
# Se prueban en orden; el primero que matchee gana.
# ---------------------------------------------------------------------------
_PATTERNS: dict[str, list[str]] = {
    "edenor": [
        r"fecha\s+de\s+emisi[oó]n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"per[ií]odo\s+facturado.*?(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"per[ií]odo\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    "edesur": [
        r"fecha\s+de\s+emisi[oó]n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"per[ií]odo\s+facturado.*?(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"per[ií]odo\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    "metrogas": [
        r"fecha\s+(?:de\s+)?factura\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"fecha\s+de\s+emisi[oó]n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"per[ií]odo\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    "telecentro": [
        r"fecha\s+de\s+emisi[oó]n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"fecha\s+de\s+vencimiento\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"per[ií]odo\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    "claro": [
        r"fecha\s+de\s+emisi[oó]n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"fecha\s+factura\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"per[ií]odo\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    "visa": [
        r"fecha\s+de\s+cierre\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"f\.?\s*cierre\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"cierre\s*[:\-]\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
    "mastercard": [
        r"fecha\s+de\s+cierre\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"cierre\s*[:\-]\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"resumen\s+al\s+(\d{2})[/\-](\d{2})[/\-](\d{4})",
    ],
}

# Fallback: cualquier DD/MM/YYYY en el documento
_FALLBACK = re.compile(r"(\d{2})[/\-](\d{2})[/\-](\d{4})")


def extract_invoice_date(pdf_path: Path, provider_name: str) -> str | None:
    """
    Extrae la fecha relevante del PDF y la devuelve como YYYY-MM-DD.

    Orden de intento:
      1. Patrones específicos del proveedor (buscan la etiqueta + fecha).
      2. Primer DD/MM/YYYY válido en el documento (fallback general).

    Devuelve None si:
      - pdfplumber no está instalado.
      - El PDF no tiene texto extraíble (escaneado sin OCR).
      - No se encontró ninguna fecha válida.
      - Cualquier error inesperado al leer el archivo.
    """
    if not _AVAILABLE:
        return None

    try:
        text = _read_text(pdf_path)
    except Exception:
        return None

    if not text or not text.strip():
        return None

    # --- patrones específicos ---
    for pat in _PATTERNS.get(provider_name.lower(), []):
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            return _to_iso(m.group(1), m.group(2), m.group(3))

    # --- fallback general ---
    for m in _FALLBACK.finditer(text):
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        result = _to_iso(dd, mm, yyyy)
        if result:
            return result

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
