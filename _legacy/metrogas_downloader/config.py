from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="METROGAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    email: str = Field(..., description="Email de la cuenta Metrogas")
    password: str = Field(..., description="Contraseña de la cuenta Metrogas")
    output_dir: Path = Field(Path("./facturas"), description="Directorio de destino para los PDFs")
    headless: bool = Field(True, description="Ejecutar browser en modo headless")
    timeout_ms: int = Field(30000, description="Timeout en ms para operaciones de browser")
    entry_url: str = Field(
        "https://registro.micuenta.metrogas.com.ar/",
        description="URL de entrada al portal",
    )
    portal_url: str = Field(
        "https://portal.micuenta.metrogas.com.ar/sites/ovmetrogas",
        description="URL del portal autenticado",
    )

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir
