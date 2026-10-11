from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Mapping

from playwright.async_api import BrowserContext, Page

from .accounts import Account
from .config import BaseProviderConfig
from .dates import extract_date_from_patterns

if TYPE_CHECKING:
    from .credential_store import CredentialProfile


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    required: bool = True
    secret: bool = False


class Provider(ABC):
    """Shared contract and default login fields for invoice providers."""

    name: ClassVar[str]
    display_name: ClassVar[str]
    requires_credentials: ClassVar[bool] = True
    can_resume_session: ClassVar[bool] = False
    invoice_date_patterns: ClassVar[tuple[str, ...]] = ()
    credential_fields: ClassVar[tuple[CredentialField, ...]] = (
        CredentialField("email", "Email"),
        CredentialField("password", "Contraseña", secret=True),
    )

    @property
    def session_key(self) -> str:
        return getattr(self, "_session_key", self.name)

    @property
    def credential_alias(self) -> str:
        return getattr(self, "_credential_alias", "")

    @abstractmethod
    def get_config(self) -> BaseProviderConfig: ...

    @abstractmethod
    async def login(self, page: Page, context: BrowserContext) -> None: ...

    @abstractmethod
    async def fetch_accounts(
        self, page: Page, context: BrowserContext
    ) -> list[Account]: ...

    @abstractmethod
    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path: ...

    def configure_credentials(
        self,
        profile: CredentialProfile,
        profile_count: int,
        sessions_directory: Path,
    ) -> None:
        config = self.get_config()
        config.set_credentials(profile.credentials)
        self._session_key = (
            f"{self.name}-{profile.id}-{profile.session_version}"
        )
        self._credential_alias = profile.alias
        if config.browser_user_data_dir is not None and profile_count > 1:
            config.browser_user_data_dir = None
        self.configure_profile_session(profile, sessions_directory)

    def configure_profile_session(
        self, profile: CredentialProfile, sessions_directory: Path
    ) -> None:
        """Configure provider-specific session files for a selected profile."""

    def apply_run_options(self, *, url: str | None = None) -> None:
        """Apply options supported by a specific provider."""

    def extract_invoice_date(self, text: str) -> str | None:
        return extract_date_from_patterns(text, self.invoice_date_patterns)

    def drive_target(
        self, period: str, banco: str = ""
    ) -> tuple[tuple[str, ...], str] | None:
        """Return provider-specific Drive folders and filename, when needed."""

    def is_session_error(self, error: Exception) -> bool:
        message = str(error).lower()
        return "401" in message or "403" in message or "token" in message

    async def try_resume_session(
        self, data: dict
    ) -> list[Account] | None:
        """Return accounts when this provider can resume the stored session."""
        return None

    async def save_session(
        self, page: Page, context: BrowserContext, accounts: list[Account]
    ) -> None:
        """Persist session state when the provider supports it."""

    async def logout(self, page: Page, context: BrowserContext) -> None:
        """Close the portal session; providers may override this."""
