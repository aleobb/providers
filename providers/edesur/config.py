from pydantic import Field
from pydantic_settings import SettingsConfigDict

from core.config import BaseProviderConfig


class EdesurConfig(BaseProviderConfig):
    model_config = SettingsConfigDict(
        env_prefix="EDESUR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    login_url: str = Field(
        "https://ov.edesur.com.ar/login",
        description="URL de login",
    )
    portal_url: str = Field(
        "https://ov.edesur.com.ar/mi-cuenta",
        description="URL del portal autenticado",
    )
