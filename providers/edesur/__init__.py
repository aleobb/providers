from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.provider import Provider
from core.registry import register
from .accounts import fetch_accounts as _fetch_accounts
from .config import EdesurConfig
from .invoice import InvoiceService
from .login import LoginOrchestrator


class EdesurProvider(Provider):
    name = "edesur"
    display_name = "Edesur"
    invoice_date_patterns = (
        r"emisi.n\s+(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"fecha.+?vencimiento\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    )

    def __init__(self):
        self._config = EdesurConfig()

    def get_config(self) -> EdesurConfig:
        return self._config

    def apply_run_options(self, *, url: str | None = None) -> None:
        if url:
            self._config.docuprint_url = url

    async def login(self, page: Page, context: BrowserContext) -> None:
        orchestrator = LoginOrchestrator(page, self._config)
        await orchestrator.execute()

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await _fetch_accounts(page, self._config)

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path:
        service = InvoiceService(page, context, self._config)
        return await service.download_for_client(account.client_number)


    # ─── Session store ────────────────────────────────────────────────────────
    # Edesur tiene reCAPTCHA interactivo. Por ahora solo guardamos cookies.
    # El path alternativo via Gmail (docuprint URL) no requiere sesión propia.

    async def save_session(
        self, page: Page, context: BrowserContext, accounts: list[Account]
    ) -> None:
        """Guarda cookies del portal Edesur + cuentas para la próxima ejecución."""
        from core import session_store
        cookies = {c["name"]: c["value"] for c in await context.cookies()}
        session_store.save(self.session_key, {
            "cookies": cookies,
            "accounts": session_store.accounts_to_list(accounts),
        })
        print("  [Edesur] Sesión guardada.")


register(EdesurProvider)
