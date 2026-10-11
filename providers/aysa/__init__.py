from __future__ import annotations

from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.provider import Provider
from core.registry import register
from .accounts import fetch_accounts as _fetch_accounts
from .config import AysaConfig
from .invoice import InvoiceService
from .login import LoginOrchestrator


class AysaProvider(Provider):
    name = "aysa"
    display_name = "AySA"
    invoice_date_patterns = (
        r"fechadeemisi.n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"emisi.n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"vencimiento\s+(\d{2})[/\-](\d{2})[/\-](\d{4})",
    )

    def __init__(self):
        self._config = AysaConfig()
        self._invoice_service: InvoiceService | None = None

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
        if self._invoice_service is None:
            self._invoice_service = InvoiceService(page, self._config)
        return await self._invoice_service.download_for_client(account.client_number)

    async def close(self) -> None:
        if self._invoice_service is not None:
            await self._invoice_service.aclose()
            self._invoice_service = None


register(AysaProvider)
