from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from playwright.async_api import BrowserContext, Page

from .accounts import Account
from .config import BaseProviderConfig


@runtime_checkable
class Provider(Protocol):
    """Interface that every invoice provider must implement."""

    name: str
    display_name: str

    def get_config(self) -> BaseProviderConfig: ...

    async def login(self, page: Page, context: BrowserContext) -> None: ...

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]: ...

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path: ...

    async def logout(self, page: Page, context: BrowserContext) -> None:
        """Cierra sesion en el portal. Implementacion opcional — default no-op."""
        ...
