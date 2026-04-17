from pydantic import Field
from pydantic_settings import SettingsConfigDict

from core.config import BaseProviderConfig


class EdenorConfig(BaseProviderConfig):
    model_config = SettingsConfigDict(
        env_prefix="EDENOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = Field("https://edenordigital.com", description="URL base del portal")
    api_base: str = Field(
        "https://utilitygo.widergy.com/api/v1", description="URL base de la API Widergy"
    )
