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

    # La base requiere email/password; sobreescribimos email como no-requerido
    email: str = Field("", description="No usado en Visa (usa documento + usuario)")

    # Credenciales específicas de Visa/Prisma
    documento_nacional_de_identidad: str = Field(
        ..., description="Número de DNI"
    )
    usuario: str = Field(..., description="Nombre de usuario del portal")
    # password heredado de BaseProviderConfig (→ VISA_PASSWORD)

    # Si se especifica, solo se descargan las tarjetas donde el titular contiene este texto.
    # Dejar vacio para descargar todas.
    # Ej: VISA_TITULAR=Alejandro Osvaldo Ben
    titular: str = Field("", description="Nombre del titular para filtrar tarjetas (opcional)")

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
