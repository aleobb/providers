from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from core.config import BaseProviderConfig


_DEFAULT_DEBUG_PROFILE = (
    Path(__file__).resolve().parents[2]
    / ".chrome_profile"
    / "telecentro_default_clone"
)


class TelecentroConfig(BaseProviderConfig):
    model_config = SettingsConfigDict(
        env_prefix="TELECENTRO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    browser_user_agent: str | None = Field(
        None,
        description="Usar el User-Agent real de Chrome",
    )
    browser_stealth: bool = Field(
        False,
        description="No parchear el fingerprint de Chrome para Telecentro",
    )
    browser_args: list[str] = Field(
        default_factory=lambda: ["--disable-blink-features=AutomationControlled"],
        description="Reducir la señal Blink de automatización en Chrome",
    )
    browser_user_data_dir: Path | None = Field(
        _DEFAULT_DEBUG_PROFILE,
        description=(
            "Clon local del perfil Default de Chrome para sesiones visibles. "
            "Se puede sobrescribir con TELECENTRO_BROWSER_USER_DATA_DIR."
        ),
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
        description="Base URL para descargar PDFs de facturas (solo requiere JWT, sin cookies)",
    )
    refresh_token_url: str = Field(
        "https://apiext.telecentro.net.ar/sv/api/refreshtokenByClient",
        description="Endpoint para obtener JWT especifico por clienteId. POST {clienteid: int}",
    )
