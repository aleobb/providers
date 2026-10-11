from pathlib import Path
from typing import Any, ClassVar, Mapping

from pydantic import Field, PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict


_DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class BaseProviderConfig(BaseSettings):
    """Base config shared by all providers. Subclass and set env_prefix."""

    _credential_values: dict[str, str] = PrivateAttr(default_factory=dict)
    _credential_names: ClassVar[frozenset[str]] = frozenset(
        {
            "email",
            "password",
            "documento_nacional_de_identidad",
            "usuario",
            "titular",
        }
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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

    def __init__(self, **values: Any) -> None:
        credentials = {
            key: str(values.pop(key))
            for key in self._credential_names
            if key in values
        }
        super().__init__(**values)
        self._credential_values = credentials

    @property
    def email(self) -> str:
        return self._credential_values.get("email", "")

    @property
    def password(self) -> str:
        return self._credential_values.get("password", "")

    def set_credentials(self, credentials: Mapping[str, str]) -> None:
        self._credential_values = {
            key: value
            for key, value in credentials.items()
            if key in self._credential_names
        }

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir
