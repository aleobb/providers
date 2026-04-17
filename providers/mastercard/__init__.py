from __future__ import annotations

from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.registry import register
from .accounts import fetch_accounts as _fetch_accounts
from .config import MastercardConfig
from .invoice import download_invoice as _download_invoice
from .login import do_login


class MastercardProvider:
    name = "mastercard"
    display_name = "Mastercard (Mis Consultas)"

    def __init__(self):
        self._config = MastercardConfig()
        self._token: str = ""
        self._cookies: dict[str, str] = {}

    def get_config(self) -> MastercardConfig:
        return self._config

    async def login(self, page: Page, context: BrowserContext) -> None:
        self._token = await do_login(page, context, self._config)
        # Capturar cookies del browser para usarlas en httpx
        raw = await context.cookies()
        self._cookies = {c["name"]: c["value"] for c in raw}

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await _fetch_accounts(self._config, self._token, self._cookies)

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path:
        return await _download_invoice(self._config, self._token, self._cookies, account)


register("mastercard", MastercardProvider)
