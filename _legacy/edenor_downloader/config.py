from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EDENOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    email: str = Field(..., description="Email de la cuenta Edenor")
    password: str = Field(..., description="Contraseña de la cuenta Edenor")
    output_dir: Path = Field(Path("./facturas"), description="Directorio de destino para los PDFs")
    headless: bool = Field(True, description="Ejecutar browser en modo headless")
    timeout_ms: int = Field(30000, description="Timeout en ms para operaciones de browser")
    base_url: str = Field("https://edenordigital.com", description="URL base del portal")
    api_base: str = Field("https://utilitygo.widergy.com/api/v1", description="URL base de la API")

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir
