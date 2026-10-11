from __future__ import annotations

from .provider import Provider
from .exceptions import ConfigurationError

_PROVIDERS: dict[str, type[Provider]] = {}


def register(provider_class: type[Provider]) -> None:
    name = provider_class.name
    if not name:
        raise ConfigurationError(
            f"La clase {provider_class.__name__} debe definir un nombre."
        )
    _PROVIDERS[name] = provider_class


def get_provider(name: str) -> Provider:
    cls = _PROVIDERS.get(name)
    if not cls:
        available = ", ".join(sorted(_PROVIDERS)) or "(ninguno)"
        raise ConfigurationError(
            f"Proveedor '{name}' no registrado. Disponibles: {available}"
        )
    return cls()


def all_provider_names() -> list[str]:
    return sorted(_PROVIDERS.keys())


def all_provider_classes() -> list[type[Provider]]:
    return list(_PROVIDERS.values())


def all_providers() -> list[Provider]:
    return [provider_class() for provider_class in all_provider_classes()]
