from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.provider import CredentialField, Provider
from core.registry import register
from .accounts import fetch_accounts
from .config import MedifeConfig
from .invoice import InvoiceService
from .login import LoginOrchestrator


class MedifeProvider(Provider):
    name = 'medife'
    display_name = 'Medifé'
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
        await LoginOrchestrator(page, self._config).execute()

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await fetch_accounts(page, self._config)

    async def download_invoice(self, page: Page, context: BrowserContext, account: Account) -> Path:
        return await InvoiceService(page, self._config).download_for_account(account)


register(MedifeProvider)
