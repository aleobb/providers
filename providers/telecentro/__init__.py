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
        """
        Captura el JWT via browser (único paso que requiere Playwright).
        El browser se cierra inmediatamente después — el resto del flujo es httpx puro.
        """
        orchestrator = LoginOrchestrator(page, self._config)
        self._jwt = await orchestrator.execute()

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        """Obtiene cuentas via API REST (no usa browser)."""
        return await _fetch_accounts(page, self._config, self._jwt)

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path:
        """
        Descarga la factura más reciente via API REST (no usa browser).
        Internamente obtiene un JWT específico para la cuenta via refreshtokenByClient.
        page y context pueden ser None cuando se restaura desde sesión guardada.
        """
        service = InvoiceService(self._config, self._jwt)
        return await service.download_for_client(account)

    # ─── Session store ────────────────────────────────────────────────────────

    async def try_resume_session(self, data: dict) -> list[Account] | None:
        """
        Intenta restaurar la sesión desde credenciales guardadas sin abrir el browser.
        Valida el JWT por su claim 'exp'. Si expiró, devuelve None (se hará login).
        """
        from core import session_store
        jwt = data.get("jwt", "")
        if not session_store.jwt_is_valid(jwt):
            return None
        accounts = session_store.accounts_from_list(data.get("accounts", []))
        if not accounts:
            return None
        self._jwt = jwt
        print("  [Telecentro] JWT válido — sin browser.")
        return accounts

    async def save_session(
        self, page: Page, context: BrowserContext, accounts: list[Account]
    ) -> None:
        """Guarda JWT + cuentas para evitar login en próximas ejecuciones."""
        from core import session_store
        session_store.save(self.name, {
            "jwt": self._jwt,
            "accounts": session_store.accounts_to_list(accounts),
        })
        print("  [Telecentro] Sesión guardada.")


register("telecentro", TelecentroProvider)
