from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.provider import CredentialField, Provider
from core.registry import register
from .accounts import fetch_accounts
from .config import MedifeConfig
from .browser import apply_context_stealth
from .invoice import InvoiceService
from .login import LoginOrchestrator


class MedifeProvider(Provider):
    name = 'medife'
    display_name = 'Medifé'
    estimated_next_due_date_months = 1
    invoice_data_patterns = {
        "account_identifier": (
            r"\bnro\.?\s+asociado\s*/\s*empresa\s*:\s*(\d[\d ./\-]*)",
        ),
        "current_due_date": (
            r"\bvencimiento\b[^\r\n]*\r?\n"
            r"(?:[^\r\n]*\r?\n){0,1}[^\r\n]*\bnro\.?\s*:\s*\d+[^\r\n]*"
            r"\r?\n\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})",
        ),
    }
    credential_fields = (
        CredentialField('tipo_documento', 'Tipo de documento (DNI, CI, LE, LC, PP; vacio = DNI)', required=False),
        CredentialField('documento_nacional_de_identidad', 'Numero de documento'),
        CredentialField('password', 'Contraseña', secret=True),
    )

    def __init__(self):
        self._config = MedifeConfig()
        if self._config.manual_login:
            self._config.headless = False

    def get_config(self) -> MedifeConfig:
        return self._config

    async def login(self, page: Page, context: BrowserContext) -> None:
        if self._config.stealth_enabled:
            await apply_context_stealth(context)
        await LoginOrchestrator(page, self._config).execute()

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await fetch_accounts(page, self._config)

    async def download_invoice(self, page: Page, context: BrowserContext, account: Account) -> Path:
        return await InvoiceService(page, self._config).download_for_account(account)


register(MedifeProvider)
