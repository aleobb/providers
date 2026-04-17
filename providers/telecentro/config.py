from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from core.config import BaseProviderConfig


class TelecentroConfig(BaseProviderConfig):
    model_config = SettingsConfigDict(
        env_prefix="TELECENTRO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    login_url: str = Field(
        "https://telecentro.com.ar/sucursal-virtual/login",
        description="URL de login",
    )
    portal_url: str = Field(
        "https://telecentro.com.ar/sucursal-virtual/home",
        description="URL del portal autenticado",
    )
    api_base: str = Field(
        "https://apiext.telecentro.net.ar",
        description="Base URL de la API REST",
    )
    invoices_url: str = Field(
        "https://telecentro.com.ar/tlc/facturas/show",
        description="Base URL para descargar PDFs de facturas",
    )
