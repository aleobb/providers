from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from .config import Config
from .exceptions import EdenorError, NavigationError
from .interceptor import NetworkInterceptor


@dataclass
class Account:
    id: int
    client_number: str
    address: str
    holder_name: str
    alias: str
    city: str
    relationship: str
    status_label: str

    def display(self, index: int) -> str:
        alias = f" ({self.alias})" if self.alias else ""
        return (
            f"  [{index}] {self.holder_name}{alias}\n"
            f"       {self.address} - {self.city}\n"
            f"       N° {self.client_number} | {self.relationship} | {self.status_label}"
        )


def _parse_accounts(data: Any) -> list[Account]:
    if not isinstance(data, list):
        return []
    accounts = []
    for item in data:
        if not isinstance(item, dict):
            continue
        accounts.append(Account(
            id=item.get("id", 0),
            client_number=str(item.get("client_number", "")),
            address=item.get("address", ""),
            holder_name=item.get("holder_name", ""),
            alias=item.get("alias", ""),
            city=item.get("city", ""),
            relationship=item.get("relationship", ""),
            status_label=item.get("status_label", ""),
        ))
    return accounts


async def fetch_accounts(
    context, interceptor: NetworkInterceptor, config: Config
) -> list[Account]:
    cookies = {c["name"]: c["value"] for c in await context.cookies()}
    raw_token = (interceptor.auth_token or "").removeprefix("Bearer ").strip()
    headers = {
        "Accept": "application/json",
        "Accept-Language": "es-AR",
        "Referer": config.base_url + "/",
        "utility-id": "19",
        "channel": "web",
    }
    if raw_token:
        headers["Authorization"] = raw_token

    async with httpx.AsyncClient(
        cookies=cookies, headers=headers, follow_redirects=True, timeout=30
    ) as client:
        r = await client.get(f"{config.api_base}/accounts")
        r.raise_for_status()
        return _parse_accounts(r.json())


def select_account(accounts: list[Account], cuenta_arg: str | None) -> Account:
    """
    Select account from list.
    - If only one account: return it directly.
    - If --cuenta N given: select by 1-based index.
    - Otherwise: print list and ask interactively.
    """
    if len(accounts) == 1:
        return accounts[0]

    if cuenta_arg is not None:
        try:
            idx = int(cuenta_arg) - 1
            if 0 <= idx < len(accounts):
                return accounts[idx]
        except ValueError:
            # Try matching by alias or client_number
            for acc in accounts:
                if cuenta_arg.lower() in (acc.alias.lower(), acc.client_number):
                    return acc
        raise EdenorError(
            f"Cuenta '{cuenta_arg}' no encontrada. "
            f"Usar un número entre 1 y {len(accounts)} o el alias de la cuenta."
        )

    # Interactive prompt
    print("\nCuentas disponibles:")
    for i, acc in enumerate(accounts, 1):
        print(acc.display(i))
    print()

    while True:
        try:
            raw = input(f"Seleccionar cuenta [1-{len(accounts)}]: ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(accounts):
                return accounts[idx]
            print(f"  Ingresar un número entre 1 y {len(accounts)}.")
        except (ValueError, EOFError):
            print("  Ingresar un número válido.")


async def switch_to_account(page: Page, account: Account, config: Config) -> None:
    """
    Select the given account in the browser sidebar so the resumen
    page shows the correct account context.
    """
    # Navigate to resumen — the sidebar will show account switcher
    await page.goto(f"{config.base_url}/cuentas/resumen", timeout=config.timeout_ms)
    await page.wait_for_load_state("networkidle", timeout=config.timeout_ms)
    await asyncio.sleep(2)

    # Check if the current account already matches
    content = await page.content()
    if account.client_number in content:
        # Already on the right account
        await asyncio.sleep(2)
        return

    # Try clicking "Mis cuentas" to open the account list
    try:
        mis_cuentas = page.get_by_role("button", name="Mis cuentas", exact=False)
        if await mis_cuentas.count() == 0:
            mis_cuentas = page.locator('[role="button"]').filter(has_text="Mis cuentas")
        if await mis_cuentas.count() > 0:
            await mis_cuentas.first.click()
            await asyncio.sleep(1)
    except Exception:
        pass

    # Try clicking the account by alias, holder name, or client number
    clicked = False
    for text in filter(None, [account.alias, account.holder_name, account.client_number]):
        candidates = page.get_by_text(text, exact=False)
        if await candidates.count() > 0:
            try:
                await candidates.first.click()
                clicked = True
                break
            except Exception:
                continue

    if not clicked:
        raise NavigationError(
            f"No se pudo seleccionar la cuenta '{account.holder_name}' en el browser. "
            "Usar EDENOR_HEADLESS=false para diagnóstico."
        )

    await page.wait_for_load_state("networkidle", timeout=config.timeout_ms)
    await asyncio.sleep(3)
