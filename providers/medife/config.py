from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from core.config import BaseProviderConfig
from core.exceptions import ConfigurationError


class MedifeConfig(BaseProviderConfig):
    _credential_names: ClassVar[frozenset[str]] = frozenset({
        'tipo_documento', 'documento_nacional_de_identidad', 'password',
    })
    model_config = SettingsConfigDict(
        env_prefix="MEDIFE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    entry_url: str = "https://medife.com.ar/portal/"
    invoices_url: str = "https://medife.com.ar/portal/facturaciones?tab=consulta"
    browser_stealth: bool = False
    browser_user_agent: str | None = None
    browser_args: list[str] = Field(
        default_factory=lambda: ['--disable-blink-features=AutomationControlled'],
        description='Reducir la señal Blink de automatización solo para Medife',
    )

    @property
    def tipo_documento(self) -> str:
        value = self._credential_values.get('tipo_documento', '').strip().upper() or 'DNI'
        if value not in {'DNI', 'CI', 'LE', 'LC', 'PP'}:
            raise ConfigurationError('Tipo de documento Medife invalido. Usar DNI, CI, LE, LC o PP.')
        return value

    @property
    def documento_nacional_de_identidad(self) -> str:
        return self._credential_values.get('documento_nacional_de_identidad', '').strip()
