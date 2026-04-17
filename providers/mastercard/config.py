from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from core.config import BaseProviderConfig


class MastercardConfig(BaseProviderConfig):
    model_config = SettingsConfigDict(
        env_prefix="MASTERCARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # email y password heredados de BaseProviderConfig

    login_url: str = "https://misconsultas.com.ar/socios/login"
    api_base: str = "https://misconsultas.com.ar/api/api"
