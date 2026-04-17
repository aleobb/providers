from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from playwright.async_api import Page

from .config import Config
from .exceptions import MetrogasError


@dataclass
class Account:
    client_number: str
    address: str
    titular: str
    meter: str

    def display(self, index: int) -> str:
        meter = f" | Medidor {self.meter}" if self.meter else ""
        return (
            f"  [{index}] N° {self.client_number}\n"
            f"       {self.address}\n"
            f"       Titular: {self.titular}{meter}"
        )


async def fetch_accounts(page: Page, config: Config) -> list[Account]:
    """Click 'Cambiar' to open the account selector and parse all accounts."""
    btn = page.get_by_role("button", name="Cambiar")
    if await btn.count() == 0:
        # Only one account — extract from page directly
        return [await _extract_single_account(page)]

    await btn.first.click()
    await asyncio.sleep(2)

    # Parse the modal list items
    items = page.locator("li").filter(has_text="N° Cliente")
    count = await items.count()
    if count == 0:
        # Fallback: try different selector
        items = page.locator("li").filter(has_text="Cliente")
        count = await items.count()

    accounts = []
    for i in range(count):
        text = await items.nth(i).inner_text()
        acc = _parse_account_text(text)
        if acc:
            accounts.append(acc)

    # Close the modal
    cancelar = page.get_by_role("button", name="Cancelar")
    if await cancelar.count() > 0:
        await cancelar.first.click()
        await asyncio.sleep(1)
    else:
        await page.keyboard.press("Escape")
        await asyncio.sleep(1)

    return accounts


async def _extract_single_account(page: Page) -> Account:
    body = await page.locator("body").inner_text()
    cn = re.search(r"(?:N[uú]mero de Cliente|N° Cliente)\s*(\d{8,})", body)
    addr = re.search(r"Direcci[oó]n\s*(.+?)(?:Titular|$)", body, re.DOTALL)
    tit = re.search(r"Titular\s*(.+?)(?:Cambiar|Medidor|Estado|$)", body, re.DOTALL)
    return Account(
        client_number=cn.group(1).strip() if cn else "",
        address=addr.group(1).strip() if addr else "",
        titular=tit.group(1).strip() if tit else "",
        meter="",
    )


def _parse_account_text(text: str) -> Account | None:
    """Parse account info from a modal list item text like:
    'JACINTO ROSSO 698 ... \nN° Cliente30012772314\nTitularANA MARIA...\nMedidor2049868'
    """
    cn = re.search(r"(?:N[°º]?\s*Cliente)\s*(\d+)", text)
    if not cn:
        return None

    titular = re.search(r"Titular\s*(.+?)(?:\n|Medidor|$)", text)
    meter = re.search(r"Medidor\s*(\S+)", text)

    # Address is the first line (before N° Cliente)
    address_match = re.match(r"(.+?)(?:N[°º]?\s*Cliente)", text, re.DOTALL)
    address = address_match.group(1).strip().replace("\n", " ") if address_match else ""

    return Account(
        client_number=cn.group(1).strip(),
        address=address,
        titular=titular.group(1).strip() if titular else "",
        meter=meter.group(1).strip() if meter else "",
    )


def select_account(accounts: list[Account], cuenta_arg: str | None) -> Account:
    if len(accounts) == 1:
        return accounts[0]

    if cuenta_arg is not None:
        try:
            idx = int(cuenta_arg) - 1
            if 0 <= idx < len(accounts):
                return accounts[idx]
        except ValueError:
            for acc in accounts:
                if cuenta_arg in acc.client_number:
                    return acc
        raise MetrogasError(
            f"Cuenta '{cuenta_arg}' no encontrada. "
            f"Usar un número entre 1 y {len(accounts)} o el N° de cliente."
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
