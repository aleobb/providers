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

    browser_user_agent: str | None = Field(
        None,
        description="Usar el User-Agent real de Chrome",
    )
    browser_stealth: bool = Field(
        False,
        description="No parchear el fingerprint de Chrome para Claro",
    )
    browser_args: list[str] = Field(
        default_factory=lambda: ["--disable-blink-features=AutomationControlled"],
        description="Reducir la señal Blink de automatización en Chrome",
    )
    portal_url: str = Field(
        "https://m-miclaro.claro.com.ar",
        description="URL base del portal Mi Claro",
    )
    elegir_url: str = Field(
        "https://m-miclaro.claro.com.ar/elegirservicio",
        description="URL del selector de cuentas/servicios",
    )
