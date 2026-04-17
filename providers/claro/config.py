from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from core.config import BaseProviderConfig


class ClaroConfig(BaseProviderConfig):
    model_config = SettingsConfigDict(
        env_prefix="CLARO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    portal_url: str = Field(
        "https://m-miclaro.claro.com.ar",
        description="URL base del portal Mi Claro",
    )
    elegir_url: str = Field(
        "https://m-miclaro.claro.com.ar/elegirservicio",
        description="URL del selector de cuentas/servicios",
    )
