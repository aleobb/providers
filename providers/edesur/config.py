from typing import Optional

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

    browser_stealth: bool = False
    browser_user_agent: Optional[str] = None

    login_url: str = Field(
        "https://ov.edesur.com.ar/login",
        description="URL de login",
    )
    portal_url: str = Field(
        "https://ov.edesur.com.ar/mi-cuenta",
        description="URL del portal autenticado",
    )
    docuprint_url: Optional[str] = Field(
        None,
        description="URL directa de Docuprint (del mail). Si se provee, saltea el portal.",
    )
    gmail_credentials_file: str = Field(
        "gmail_credentials.json",
        description="Ruta al JSON de credenciales OAuth de Gmail (Google Cloud Console).",
    )
    gmail_token_file: str = Field(
        "gmail_token.json",
        description="Ruta donde guardar el token OAuth generado tras la primera autorización.",
    )
