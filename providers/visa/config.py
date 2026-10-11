from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from core.config import BaseProviderConfig


class VisaConfig(BaseProviderConfig):
    model_config = SettingsConfigDict(
        env_prefix="VISA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    portal_url: str = Field(
        "https://mistarjetas.prismamediosdepago.com/socios/app/landing",
        description="URL del dashboard post-login",
    )
    api_base: str = Field(
        "https://mis-tarjetas.prismamediosdepago.com/socios/auth/api",
        description="Base URL de la API REST",
    )
    session_file: Path = Field(
        default_factory=lambda: Path(__file__).parent / "visa_session.json",
        description="Archivo JSON donde se persisten las cookies de sesión",
    )

    @property
    def documento_nacional_de_identidad(self) -> str:
        return self._credential_values.get("documento_nacional_de_identidad", "")

    @property
    def usuario(self) -> str:
        return self._credential_values.get("usuario", "")

    @property
    def titular(self) -> str:
        return self._credential_values.get("titular", "")
