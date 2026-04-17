from pydantic import Field
from pydantic_settings import SettingsConfigDict

from core.config import BaseProviderConfig


class MetrogasConfig(BaseProviderConfig):
    model_config = SettingsConfigDict(
        env_prefix="METROGAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    entry_url: str = Field(
        "https://registro.micuenta.metrogas.com.ar/",
        description="URL de entrada al portal",
    )
    portal_url: str = Field(
        "https://portal.micuenta.metrogas.com.ar/sites/ovmetrogas",
        description="URL del portal autenticado",
    )
