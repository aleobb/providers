from __future__ import annotations

from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.provider import Provider
from core.registry import register
from .accounts import fetch_accounts as _fetch_accounts
from .config import ClaroConfig
from .invoice import InvoiceService
from .login import LoginOrchestrator


class ClaroProvider(Provider):
    name = "claro"
    display_name = "Claro"
    invoice_date_patterns = (
        r"emisi.n\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"fecha\s+factura\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"per[ií]odo\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    )

    def __init__(self):
        self._config = ClaroConfig()
        self._invoice_service: InvoiceService | None = None

    def get_config(self) -> ClaroConfig:
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
        return await self._invoice_service.download_for_account(account)

    async def close(self) -> None:
        if self._invoice_service is not None:
            await self._invoice_service.aclose()
            self._invoice_service = None

    # ─── Session store ────────────────────────────────────────────────────────
    # Claro aún necesita el browser para capturar la URL del popup de descarga.
    # Por ahora solo guardamos cookies para análisis futuro del backend.

    async def save_session(
        self, page: Page, context: BrowserContext, accounts: list[Account]
    ) -> None:
        """Guarda cookies de Keycloak + cuentas para la próxima ejecución."""
        from core import session_store
        cookies = {c["name"]: c["value"] for c in await context.cookies()}
        session_store.save(self.session_key, {
            "cookies": cookies,
            "accounts": session_store.accounts_to_list(accounts),
        })
        print("  [Claro] Sesión guardada.")


register(ClaroProvider)
