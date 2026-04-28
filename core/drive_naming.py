from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# Nombre de carpeta raíz para servicios y tarjetas (dentro del folder ID configurado)
SERVICE_FOLDER = "Facturas de Productos y Servicios"
CARD_FOLDER = "Tarjetas de Credito"

# Nombre de visualización por proveedor (para el nombre de archivo y subcarpeta)
PROVIDER_DISPLAY: dict[str, str] = {
    "edenor": "Edenor",
    "edesur": "Edesur",
    "metrogas": "Metrogas",
    "telecentro": "Telecentro",
    "claro": "Claro",
}


@dataclass
class DriveTarget:
    # Partes de la ruta relativa al folder raíz en Drive (e.g. ["Tarjetas de Credito", "Visa", "Galicia"])
    subfolder_parts: list[str] = field(default_factory=list)
    # Nombre final del archivo en Drive (e.g. "Visa Galicia - Resumen F.Cierre 2026-03-15.pdf")
    filename: str = ""


def _normalize_date(period: str) -> str:
    """
    Normaliza el período a YYYY-MM-DD.
    - Si ya es YYYY-MM-DD lo devuelve tal cual.
    - Si es YYYY-MM agrega -01 (primer día del mes).
    """
    if re.match(r"\d{4}-\d{2}-\d{2}$", period):
        return period
    if re.match(r"\d{4}-\d{2}$", period):
        return period + "-01"
    return period


def get_drive_target(
    provider_name: str,
    period: str,
    banco: str = "",
) -> DriveTarget:
    """
    Devuelve la subcarpeta y el nombre de archivo para Drive.

    Args:
        provider_name: nombre del proveedor en minúsculas (ej. "edenor", "visa").
        period: período en formato YYYY-MM o YYYY-MM-DD.
        banco: nombre del banco (para tarjetas). Si está vacío se lee del env var.
    """
    name = provider_name.lower()
    date_str = _normalize_date(period)

    if name == "visa":
        banco_name = banco or os.environ.get("VISA_BANCO", "")
        filename = f"Visa {banco_name} - Resumen F.Cierre {date_str}.pdf".strip()
        parts = [CARD_FOLDER, "Visa"]
        if banco_name:
            parts.append(banco_name)
        return DriveTarget(subfolder_parts=parts, filename=filename)

    if name == "mastercard":
        banco_name = banco or os.environ.get("MASTERCARD_BANCO", "")
        filename = f"Mastercard {banco_name} - Resumen F.Cierre {date_str}.pdf".strip()
        parts = [CARD_FOLDER, "Mastercard"]
        if banco_name:
            parts.append(banco_name)
        return DriveTarget(subfolder_parts=parts, filename=filename)

    # Proveedores de servicios
    display = PROVIDER_DISPLAY.get(name, name.capitalize())
    filename = f"Fra. {display} - {date_str}.pdf"
    return DriveTarget(
        subfolder_parts=[SERVICE_FOLDER, display],
        filename=filename,
    )
