from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseProviderConfig(BaseSettings):
    """Base config shared by all providers. Subclass and set env_prefix."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    email: str = Field(..., description="Email de la cuenta")
    password: str = Field(..., description="Contraseña de la cuenta")
    output_dir: Path = Field(Path("./facturas"), description="Directorio de destino")
    headless: bool = Field(True, description="Ejecutar browser en modo headless")
    timeout_ms: int = Field(30000, description="Timeout en ms")

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir
