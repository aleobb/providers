from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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
    browser_stealth: bool = Field(
        True, description="Aplicar ajustes stealth al navegador"
    )
    browser_args: list[str] = Field(
        default_factory=list,
        description="Argumentos adicionales para el navegador",
    )
    browser_user_agent: str | None = Field(
        _DEFAULT_BROWSER_USER_AGENT,
        description="User-Agent del navegador; None usa el User-Agent real de Chrome",
    )
    browser_user_data_dir: Path | None = Field(
        None,
        description="Directorio de datos de Chrome; None usa un perfil aislado",
    )

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir
