from pydantic import Field
from pydantic_settings import SettingsConfigDict

from core.config import BaseProviderConfig


class AysaConfig(BaseProviderConfig):
    model_config = SettingsConfigDict(
        env_prefix="AYSA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    entry_url: str = Field(
        "https://oficinavirtual.web.aysa.com.ar/index.html",
        description="URL de entrada al portal",
    )
    portal_url: str = Field(
        "https://portal.web.aysa.com.ar/index.html",
        description="URL del portal autenticado",
    )
    api_base: str = Field(
        "https://portal.web.aysa.com.ar/AysaOvServiceHub/api/v1/ov",
        description="Base URL de la API REST",
    )
