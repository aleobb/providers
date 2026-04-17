from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.registry import register
from .accounts import fetch_accounts as _fetch_accounts
from .config import EdenorConfig
from .interceptor import NetworkInterceptor
from .invoice import InvoiceService
from .login import LoginOrchestrator


class EdenorProvider:
    name = "edenor"
    display_name = "Edenor"

    def __init__(self):
        self._config = EdenorConfig()
        self._interceptor = NetworkInterceptor()
        self._page: Page | None = None
        self._context: BrowserContext | None = None

    def get_config(self) -> EdenorConfig:
        return self._config

    async def login(self, page: Page, context: BrowserContext) -> None:
        self._page = page
        self._context = context
        await self._interceptor.start(page)
        orchestrator = LoginOrchestrator(page, self._config)
        await orchestrator.execute()
        await page.wait_for_load_state("networkidle", timeout=self._config.timeout_ms)
        await asyncio.sleep(3)

        # Navigate to resumen to load bill data and download button
        await page.goto(
            f"{self._config.base_url}/cuentas/resumen",
            timeout=self._config.timeout_ms,
        )
        await page.wait_for_load_state("networkidle", timeout=self._config.timeout_ms)
        await asyncio.sleep(4)

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await _fetch_accounts(context, self._interceptor, self._config)

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path:
        service = InvoiceService(context, page, self._interceptor, self._config)
        return await service.download_latest(
            account_id=account.extra["id"],
            client_number=account.client_number,
        )


register("edenor", EdenorProvider)
