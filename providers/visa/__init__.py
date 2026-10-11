from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.dates import to_iso
from core.provider import CredentialField, Provider
from core.registry import register
from .accounts import fetch_accounts as _fetch_accounts
from .config import VisaConfig
from .interceptor import NetworkInterceptor
from .invoice import InvoiceService
from .login import LoginOrchestrator
from .logout import LogoutService

if TYPE_CHECKING:
    from core.credential_store import CredentialProfile


class VisaProvider(Provider):
    name = "visa"
    display_name = "Visa (Prisma)"
    credential_fields = (
        CredentialField("documento_nacional_de_identidad", "DNI"),
        CredentialField("usuario", "Usuario"),
        CredentialField("password", "Contraseña", secret=True),
        CredentialField("titular", "Titular", required=False),
    )

    def __init__(self):
        self._config = VisaConfig()
        self._interceptor = NetworkInterceptor()
        self._invoice_service: InvoiceService | None = None
        self._logout_service = LogoutService(self._config)

    def get_config(self) -> VisaConfig:
        return self._config

    def extract_invoice_date(self, text: str) -> str | None:
        match = re.search(
            r"cierre\s+actual\s*[:\-]?\s*(\d{1,2})\s+"
            r"(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\s+(\d{2})\b",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        months = {
            "ene": "01",
            "feb": "02",
            "mar": "03",
            "abr": "04",
            "may": "05",
            "jun": "06",
            "jul": "07",
            "ago": "08",
            "sep": "09",
            "oct": "10",
            "nov": "11",
            "dic": "12",
        }
        month = months[match.group(2).lower()]
        return to_iso(match.group(1), month, f"20{match.group(3)}")

    def drive_target(
        self, period: str, banco: str = ""
    ) -> tuple[tuple[str, ...], str]:
        bank_name = banco or os.environ.get("VISA_BANCO", "")
        filename = f"Visa {bank_name} - Resumen F.Cierre {period}.pdf".strip()
        folders = ["Tarjetas de Credito", "Visa"]
        if bank_name:
            folders.append(bank_name)
        return tuple(folders), filename

    def configure_profile_session(
        self, profile: CredentialProfile, sessions_directory: Path
    ) -> None:
        self._config.session_file = (
            sessions_directory / f"{self.session_key}_session.json"
        )
        self._config.session_file.parent.mkdir(parents=True, exist_ok=True)

    async def login(self, page: Page, context: BrowserContext) -> None:
        # Activar el interceptor antes del login para capturar el token
        await self._interceptor.start(page)
        orchestrator = LoginOrchestrator(page, context, self._config)
        await orchestrator.execute()
        # Esperar a que el dashboard renderice el contenido; la app usa polling
        # y no llega a networkidle de forma consistente.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=self._config.timeout_ms)
        except Exception:
            pass
        await asyncio.sleep(3)

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await _fetch_accounts(page, context, self._interceptor, self._config)

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path:
        if self._invoice_service is None:
            self._invoice_service = InvoiceService(
                page, context, self._interceptor, self._config
            )
        return await self._invoice_service.download_for_account(account)

    async def close(self) -> None:
        if self._invoice_service is not None:
            await self._invoice_service.aclose()
            self._invoice_service = None

    async def logout(self, page: Page, context: BrowserContext) -> None:
        await self._logout_service.logout(page, context)

    # ─── Session store ────────────────────────────────────────────────────────
    # Visa (JSF portal) aún necesita el browser para el switch de tarjeta y
    # la captura de la URL de descarga. Solo guardamos cookies para análisis futuro.

    async def save_session(
        self, page: Page, context: BrowserContext, accounts: list[Account]
    ) -> None:
        """Guarda cookies de Spring Security + cuentas para la próxima ejecución."""
        from core import session_store
        cookies = {c["name"]: c["value"] for c in await context.cookies()}
        session_store.save(self.session_key, {
            "cookies": cookies,
            "accounts": session_store.accounts_to_list(accounts),
        })
        print("  [Visa] Sesión guardada.")


register(VisaProvider)
