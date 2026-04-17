from __future__ import annotations

import asyncio
import re

from playwright.async_api import Page

from core.accounts import Account
from .config import MetrogasConfig


async def fetch_accounts(page: Page, config: MetrogasConfig) -> list[Account]:
    btn = page.get_by_role("button", name="Cambiar")
    if await btn.count() == 0:
        return [await _extract_single_account(page)]

    await btn.first.click()
    await asyncio.sleep(2)

    items = page.locator("li").filter(has_text="Cliente")
    count = await items.count()

    accounts = []
    for i in range(count):
        text = await items.nth(i).inner_text()
        acc = _parse_account_text(text)
        if acc:
            accounts.append(acc)

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
        display_name=tit.group(1).strip() if tit else "",
        address=addr.group(1).strip() if addr else "",
    )


def _parse_account_text(text: str) -> Account | None:
    cn = re.search(r"(?:N[°º]?\s*Cliente)\s*(\d+)", text)
    if not cn:
        return None

    titular = re.search(r"Titular\s*(.+?)(?:\n|Medidor|$)", text)
    meter = re.search(r"Medidor\s*(\S+)", text)
    address_match = re.match(r"(.+?)(?:N[°º]?\s*Cliente)", text, re.DOTALL)
    address = address_match.group(1).strip().replace("\n", " ") if address_match else ""

    extra = {}
    if meter:
        extra["Medidor"] = meter.group(1).strip()

    return Account(
        client_number=cn.group(1).strip(),
        display_name=titular.group(1).strip() if titular else "",
        address=address,
        extra=extra,
    )
