"""Redacción de secretos en los registros de ejecución.

Las líneas de consola de una ejecución gestionada se guardan en Supabase (`ejecucion_logs` y el log
completo en Storage). Antes de enviarlas se tapan: los valores exactos que el proceso conoce (campos
secretos de las credenciales, claves del entorno, respuestas OTP/MFA) y los formatos de token
más comunes (JWT, Bearer/Basic, tokens Fernet y de GitHub, claves `sb_...`).
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping
from urllib.parse import quote

MASK = "***"
MIN_LENGTH = 4

# Variables de entorno cuyo valor es secreto (se toma el valor exacto).
_SECRET_ENV_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSPHRASE)", re.IGNORECASE)
# Campos de credenciales que se tratan como secretos aunque el portal no los marque.
SECRET_FIELD_NAME = re.compile(r"(pass|clave|token|secret|pin|cvc|cvv)", re.IGNORECASE)

_PATTERNS = (
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"gAAAA[A-Za-z0-9_=-]{40,}"),  # token Fernet
    re.compile(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsb_(?:secret|publishable)_[A-Za-z0-9_-]{8,}"),
)


class Redactor:
    def __init__(self) -> None:
        self._values: list[str] = []

    def add(self, value: object) -> None:
        """Registra un valor secreto (y su versión codificada para URL)."""
        if not isinstance(value, str):
            return
        value = value.strip()
        if len(value) < MIN_LENGTH or "\n" in value:
            return
        for variant in {value, quote(value, safe="")}:
            if variant not in self._values:
                self._values.append(variant)
        self._values.sort(key=len, reverse=True)

    def add_many(self, values: Iterable[object]) -> None:
        for value in values:
            self.add(value)

    def add_env(self, environ: Mapping[str, str]) -> None:
        """Registra los valores de las variables de entorno con nombre de secreto."""
        for name, value in environ.items():
            if _SECRET_ENV_NAME.search(name) and len(value.strip()) >= 8:
                self.add(value)

    def redact(self, text: str) -> str:
        for value in self._values:
            text = text.replace(value, MASK)
        for pattern in _PATTERNS:
            text = pattern.sub(MASK, text)
        return text
