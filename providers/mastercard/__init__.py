from __future__ import annotations

import os
from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.provider import Provider
from core.registry import register
from .accounts import fetch_accounts as _fetch_accounts
from .config import MastercardConfig
from .invoice import InvoiceService
from .login import do_login


class MastercardProvider(Provider):
    name = "mastercard"
    display_name = "Mastercard (Mis Consultas)"
    can_resume_session = True
    invoice_date_patterns = (
        r"fecha\s+de\s+cierre\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"cierre\s*[:\-]\s*(\d{2})[/\-](\d{2})[/\-](\d{4})",
        r"resumen\s+al\s+(\d{2})[/\-](\d{2})[/\-](\d{4})",
    )

    def __init__(self):
        self._config = MastercardConfig()
        self._token: str = ""
        self._cookies: dict[str, str] = {}
        self._invoice_service: InvoiceService | None = None

    def get_config(self) -> MastercardConfig:
        return self._config

    def drive_target(
        self, period: str, banco: str = ""
    ) -> tuple[tuple[str, ...], str]:
        bank_name = banco or os.environ.get("MASTERCARD_BANCO", "")
        filename = f"Mastercard {bank_name} - Resumen F.Cierre {period}.pdf".strip()
        folders = ["Tarjetas de Credito", "Mastercard"]
        if bank_name:
            folders.append(bank_name)
        return tuple(folders), filename

    async def login(self, page: Page, context: BrowserContext) -> None:
        self._token = await do_login(page, context, self._config)
        raw = await context.cookies()
        self._cookies = {c["name"]: c["value"] for c in raw}

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await _fetch_accounts(self._config, self._token, self._cookies)

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path:
        """page y context pueden ser None cuando se restaura desde sesión guardada."""
        if self._invoice_service is None:
            self._invoice_service = InvoiceService(
                self._config, self._token, self._cookies
            )
        return await self._invoice_service.download_for_account(account)

    async def close(self) -> None:
        if self._invoice_service is not None:
            await self._invoice_service.aclose()
            self._invoice_service = None

    # ─── Session store ────────────────────────────────────────────────────────

    async def try_resume_session(self, data: dict) -> list[Account] | None:
        """
        Intenta restaurar la sesión desde credenciales guardadas sin abrir el browser.
        Valida el JWT por su claim 'exp'. Si expiró, devuelve None.
        Nota: Mastercard requiere MFA en cada login. Si la sesión expira, el usuario
        deberá ingresar el código actual de Authenticator en la consola.
        """
        from core import session_store
        token = data.get("token", "")
        if not session_store.jwt_is_valid(token):
            return None
        accounts = session_store.accounts_from_list(data.get("accounts", []))
        if not accounts:
            return None
        self._token = token
        self._cookies = data.get("cookies", {})
        print("  [Mastercard] JWT válido — sin browser (se omite el OTP).")
        return accounts

    async def save_session(
        self, page: Page, context: BrowserContext, accounts: list[Account]
    ) -> None:
        """Guarda token + cookies + cuentas para evitar el OTP en próximas ejecuciones."""
        from core import session_store
        session_store.save(self.session_key, {
            "token": self._token,
            "cookies": self._cookies,
            "accounts": session_store.accounts_to_list(accounts),
        })
        print("  [Mastercard] Sesión guardada.")


register(MastercardProvider)
