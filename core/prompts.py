"""Entrada interactiva desacoplada de la consola.

Por defecto `ask()` equivale a `input()`: la ejecución local por consola no
cambia. Una ejecución gestionada (ver `core/managed.py`) instala un "broker"
que deriva la consulta a la interfaz web y espera la respuesta allí.
"""
from __future__ import annotations

from typing import Callable, Sequence

from .exceptions import InvoiceDownloaderError


class PromptTimeoutError(InvoiceDownloaderError):
    """No llegó respuesta a una consulta interactiva dentro del plazo."""


# broker(prompt, kind, options) -> respuesta en texto
Broker = Callable[[str, str, "Sequence[str] | None"], str]
_broker: Broker | None = None


def set_broker(broker: Broker | None) -> None:
    global _broker
    _broker = broker


def ask(
    prompt: str, *, kind: str = "texto", options: Sequence[str] | None = None
) -> str:
    """Pide un dato al usuario. kind: otp, mfa, perfil, cuenta o texto."""
    if _broker is None:
        return input(prompt)
    return _broker(prompt, kind, list(options) if options else None)
