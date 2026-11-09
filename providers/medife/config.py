from pydantic_settings import SettingsConfigDict

from core.config import BaseProviderConfig


class MedifeConfig(BaseProviderConfig):
    model_config = SettingsConfigDict(
        env_prefix="MEDIFE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    entry_url: str = "https://medife.com.ar/portal/"
    invoices_url: str = "https://medife.com.ar/portal/facturaciones?tab=consulta"
    browser_stealth: bool = False
    browser_user_agent: str | None = None
