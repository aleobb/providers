from __future__ import annotations

from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.registry import register
from .accounts import fetch_accounts as _fetch_accounts
from .config import AysaConfig
from .invoice import InvoiceService
from .login import LoginOrchestrator


class AysaProvider:
    name = "aysa"
    display_name = "AySA"

    def __init__(self):
        self._config = AysaConfig()

    def get_config(self) -> AysaConfig:
        return self._config

    async def login(self, page: Page, context: BrowserContext) -> None:
        orchestrator = LoginOrchestrator(page, self._config)
        await orchestrator.execute()

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await _fetch_accounts(page, self._config)

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path:
        service = InvoiceService(page, self._config)
        return await service.download_for_client(account.client_number)


register("aysa", AysaProvider)
