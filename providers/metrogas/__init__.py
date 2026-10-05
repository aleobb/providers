from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.registry import register
from core.utils import unique_path
from .accounts import fetch_accounts as _fetch_accounts
from .config import MetrogasConfig
from .invoice import (
    InvoiceService,
    _INVOICE_API_PATH,
    _is_pdf_response,
    _validated_pdf_content,
)
from .login import LoginOrchestrator


class MetrogasProvider:
    name = "metrogas"
    display_name = "Metrogas"

    def __init__(self):
        self._config = MetrogasConfig()
        self._saved_cookies: dict | None = None

    def get_config(self) -> MetrogasConfig:
        return self._config

    async def login(self, page: Page, context: BrowserContext) -> None:
        orchestrator = LoginOrchestrator(page, self._config)
        await orchestrator.execute()

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await _fetch_accounts(page, self._config)

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path:
        """
        Descarga la factura del cliente indicado.
        Si page es None (sesión restaurada), usa cookies guardadas vía httpx directo.
        El período queda como 'sin-fecha' y se corrige luego por pdf_extractor.
        """
        if page is None:
            return await self._download_no_browser(account.client_number)
        service = InvoiceService(page, self._config)
        return await service.download_for_client(account.client_number)

    async def _download_no_browser(self, client_number: str) -> Path:
        """Descarga directa vía httpx usando cookies guardadas (sin browser)."""
        dest_dir = self._config.ensure_output_dir()
        # El período se deja en 'sin-fecha'; pdf_extractor lo corrige al subir a Drive
        dest_path = unique_path(
            dest_dir / f"metrogas_sin-fecha_{client_number}_factura.pdf"
        )
        url = f"https://portal.micuenta.metrogas.com.ar{_INVOICE_API_PATH}{client_number}"
        async with httpx.AsyncClient(
            cookies=self._saved_cookies or {},
            follow_redirects=True,
            timeout=60,
            verify=False,
        ) as client:
            r = await client.get(url)
            dest_path.write_bytes(_validated_pdf_content(r, client_number))
        return dest_path

    # ─── Session store ────────────────────────────────────────────────────────

    async def try_resume_session(self, data: dict) -> list[Account] | None:
        """
        Valida la sesión comprobando que el endpoint devuelva un PDF para la primera cuenta.
        """
        from core import session_store
        cookies = data.get("cookies", {})
        accounts = session_store.accounts_from_list(data.get("accounts", []))
        if not accounts or not cookies:
            return None

        probe_url = (
            f"https://portal.micuenta.metrogas.com.ar"
            f"{_INVOICE_API_PATH}{accounts[0].client_number}"
        )
        async with httpx.AsyncClient(
            cookies=cookies,
            follow_redirects=True,
            timeout=10,
            verify=False,
        ) as client:
            response = await client.get(probe_url)
        if not _is_pdf_response(response):
            return None

        self._saved_cookies = cookies
        print("  [Metrogas] Sesión válida — sin browser.")
        return accounts

    async def save_session(
        self, page: Page, context: BrowserContext, accounts: list[Account]
    ) -> None:
        """Guarda cookies SAP Fiori + cuentas para la próxima ejecución."""
        from core import session_store
        cookies = {c["name"]: c["value"] for c in await context.cookies()}
        session_store.save(self.name, {
            "cookies": cookies,
            "accounts": session_store.accounts_to_list(accounts),
        })
        print("  [Metrogas] Sesión guardada.")


register("metrogas", MetrogasProvider)
