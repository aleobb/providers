from __future__ import annotations

import httpx
from playwright.async_api import Page

from core.accounts import Account
from .config import AysaConfig


async def fetch_accounts(page: Page, config: AysaConfig) -> list[Account]:
    """Obtiene las cuentas del usuario via API REST usando las cookies de sesión."""
    cookies = {c["name"]: c["value"] for c in await page.context.cookies()}

    async with httpx.AsyncClient(cookies=cookies, follow_redirects=True, timeout=30, verify=False) as client:
        r = await client.get(f"{config.api_base}/cuentas")
        r.raise_for_status()
        data = r.json()

    accounts = []
    for rel in data.get("RELACIONES", []):
        contrato = rel.get("CONTRATO", "")
        alias = rel.get("ALIAS_CONT", "")
        domicilio = rel.get("DOMICILIO", "").strip()
        accounts.append(
            Account(
                client_number=contrato,
                display_name=alias,
                address=domicilio,
            )
        )

    return accounts
