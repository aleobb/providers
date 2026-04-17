from __future__ import annotations

import json

from playwright.async_api import Page

from core.accounts import Account
from .config import EdesurConfig


async def fetch_accounts(page: Page, config: EdesurConfig) -> list[Account]:
    """Read accounts from localStorage after login."""

    raw = await page.evaluate("localStorage.getItem('LISTA_CUENTAS_DETALLE')")
    if not raw:
        return []

    entries = json.loads(raw)
    accounts = []
    for entry in entries:
        detalle = entry.get("detalle", {})
        contract = detalle.get("contractAccount", "")
        meter = detalle.get("meterNumber", "")
        name = detalle.get("name", entry.get("name", ""))
        address_obj = detalle.get("address", {})
        address = (
            address_obj.get("short", "")
            if isinstance(address_obj, dict)
            else entry.get("address", "")
        )

        extra = {}
        if meter:
            extra["meter"] = meter

        accounts.append(
            Account(
                client_number=contract,
                display_name=name,
                address=address,
                extra=extra,
            )
        )

    return accounts
