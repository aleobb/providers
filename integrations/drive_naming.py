from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.provider import Provider

SERVICE_FOLDER = "Facturas de Productos y Servicios"


@dataclass
class DriveTarget:
    subfolder_parts: list[str] = field(default_factory=list)
    filename: str = ""


def _normalize_date(period: str) -> str:
    if re.match(r"\d{4}-\d{2}-\d{2}$", period):
        return period
    if re.match(r"\d{4}-\d{2}$", period):
        return period + "-01"
    return period


def get_drive_target(
    provider: Provider,
    period: str,
    banco: str = "",
) -> DriveTarget:
    date_str = _normalize_date(period)
    provider_target = provider.drive_target(date_str, banco)
    if provider_target is not None:
        subfolder_parts, filename = provider_target
        return DriveTarget(
            subfolder_parts=list(subfolder_parts),
            filename=filename,
        )

    display = provider.display_name
    return DriveTarget(
        subfolder_parts=[SERVICE_FOLDER, display],
        filename=f"Fra. {display} - {date_str}.pdf",
    )
