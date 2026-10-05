from __future__ import annotations

import httpx
from playwright.async_api import Page

from core.accounts import Account
from .config import TelecentroConfig


async def fetch_accounts(page: Page, config: TelecentroConfig, jwt: str) -> list[Account]:
    """
    Obtiene todas las cuentas vinculadas al email via API REST.
    El endpoint acepta el email como query param, pero tambien lo deduce del JWT.
    No usa el browser (page se ignora, se mantiene por compatibilidad con el Protocol).
    """
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(
        headers=headers, follow_redirects=True, timeout=30, verify=False
    ) as client:
        r = await client.get(
            f"{config.api_base}/bss/vta/clientes/v1/byEmail",
            params={"email": config.email},
        )
        r.raise_for_status()
        data = r.json()

    accounts = []
    for cliente in data.get("clientes", []):
        client_id = str(cliente.get("clienteId", ""))
        if not client_id:
            continue
        accounts.append(
            Account(
                client_number=client_id,
                display_name=cliente.get("apellidoNombre", "").strip(),
                address=cliente.get("domicilio", "").strip(),
            )
        )
    return accounts
