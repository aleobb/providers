from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.provider import Provider
from core.registry import register
from .accounts import fetch_accounts
from .config import MedifeConfig
from .invoice import InvoiceService
from .login import LoginOrchestrator


class MedifeProvider(Provider):
    name = 'medife'
    display_name = 'Medifé'

    def __init__(self):
        self._config = MedifeConfig()

    def get_config(self) -> MedifeConfig:
        return self._config

    async def login(self, page: Page, context: BrowserContext) -> None:
        await LoginOrchestrator(page, self._config).execute()

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await fetch_accounts(page, self._config)

    async def download_invoice(self, page: Page, context: BrowserContext, account: Account) -> Path:
        return await InvoiceService(page, self._config).download_for_account(account)


register(MedifeProvider)
