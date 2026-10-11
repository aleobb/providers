from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.provider import Provider
from core.registry import register
from .accounts import fetch_accounts as _fetch_accounts
from .config import EdenorConfig
from .interceptor import NetworkInterceptor
from .invoice import InvoiceService
from .login import LoginOrchestrator


class EdenorProvider(Provider):
    name = "edenor"
    display_name = "Edenor"
    can_resume_session = True
    invoice_date_patterns = (
        r"emisi.n\s+(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"fecha.+?vencimiento\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
    )

    def __init__(self):
        self._config = EdenorConfig()
        self._interceptor = NetworkInterceptor()
        self._page: Page | None = None
        self._context: BrowserContext | None = None
        # Credenciales de sesión guardada (path sin browser)
        self._saved_cookies: dict | None = None
        self._saved_token: str | None = None
        self._invoice_service: InvoiceService | None = None

    def get_config(self) -> EdenorConfig:
        return self._config

    async def login(self, page: Page, context: BrowserContext) -> None:
        self._page = page
        self._context = context
        await self._interceptor.start(page)
        orchestrator = LoginOrchestrator(page, self._config)
        await orchestrator.execute()
        await asyncio.sleep(3)

        await page.goto(
            f"{self._config.base_url}/cuentas/resumen",
            timeout=self._config.timeout_ms,
        )
        await asyncio.sleep(4)

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await _fetch_accounts(context, self._interceptor, self._config)

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path:
        """
        Descarga la factura más reciente.
        page/context pueden ser None cuando se restaura desde sesión guardada:
        en ese caso usa las credenciales en self._saved_cookies / self._saved_token.
        """
        if self._invoice_service is None:
            if page is None:
                self._invoice_service = InvoiceService(
                    None,
                    None,
                    None,
                    self._config,
                    saved_cookies=self._saved_cookies,
                    saved_token=self._saved_token,
                )
            else:
                self._invoice_service = InvoiceService(
                    context, page, self._interceptor, self._config
                )
        return await self._invoice_service.download_latest(
            account_id=account.extra["id"],
            client_number=account.client_number,
        )

    async def close(self) -> None:
        if self._invoice_service is not None:
            await self._invoice_service.aclose()
            self._invoice_service = None

    # ─── Session store ────────────────────────────────────────────────────────

    async def try_resume_session(self, data: dict) -> list[Account] | None:
        """
        Valida sesión guardada haciendo un probe al endpoint de cuentas.
        Si responde 2xx, restaura credenciales y devuelve cuentas.
        """
        from core import session_store
        auth_token = data.get("auth_token", "")
        cookies = data.get("cookies", {})
        accounts = session_store.accounts_from_list(data.get("accounts", []))
        if not accounts or not auth_token:
            return None

        headers = {
            "Authorization": auth_token,
            "utility-id": "19",
            "channel": "web",
            "Accept": "application/json",
        }
        valid = await session_store.probe(
            f"{self._config.api_base}/accounts",
            headers=headers,
            cookies=cookies,
        )
        if not valid:
            return None

        self._saved_token = auth_token.removeprefix("Bearer ").strip()
        self._saved_cookies = cookies
        print("  [Edenor] Sesión válida — sin browser.")
        return accounts

    async def save_session(
        self, page: Page, context: BrowserContext, accounts: list[Account]
    ) -> None:
        """Guarda token + cookies + cuentas para la próxima ejecución."""
        from core import session_store
        cookies = {c["name"]: c["value"] for c in await context.cookies()}
        session_store.save(self.session_key, {
            "auth_token": self._interceptor.auth_token or "",
            "cookies": cookies,
            "accounts": session_store.accounts_to_list(accounts),
        })
        print("  [Edenor] Sesión guardada.")


register(EdenorProvider)
