from __future__ import annotations

from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.registry import register
from .accounts import fetch_accounts as _fetch_accounts
from .config import TelecentroConfig
from .invoice import InvoiceService
from .login import LoginOrchestrator


class TelecentroProvider:
    name = "telecentro"
    display_name = "Telecentro"

    def __init__(self):
        self._config = TelecentroConfig()
        self._jwt: str = ""

    def get_config(self) -> TelecentroConfig:
        return self._config

    async def login(self, page: Page, context: BrowserContext) -> None:
        orchestrator = LoginOrchestrator(page, self._config)
        self._jwt = await orchestrator.execute()

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await _fetch_accounts(page, self._config, self._jwt)

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path:
        service = InvoiceService(page, self._config, self._jwt)
        return await service.download_for_client(account)


register("telecentro", TelecentroProvider)
