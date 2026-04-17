from __future__ import annotations

from .exceptions import ConfigurationError

_PROVIDERS: dict[str, type] = {}


def register(name: str, provider_class: type) -> None:
    _PROVIDERS[name] = provider_class


def get_provider(name: str):
    cls = _PROVIDERS.get(name)
    if not cls:
        available = ", ".join(sorted(_PROVIDERS)) or "(ninguno)"
        raise ConfigurationError(
            f"Proveedor '{name}' no registrado. Disponibles: {available}"
        )
    return cls()


def all_provider_names() -> list[str]:
    return sorted(_PROVIDERS.keys())


def all_providers():
    return [cls() for cls in _PROVIDERS.values()]
