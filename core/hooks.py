"""Ganchos opcionales que se ejecutan después de cada descarga exitosa.

El núcleo no depende de ninguna integración: quien quiera reaccionar a una
descarga (por ejemplo, sincronizar con Supabase) registra un gancho. Un error
en un gancho se informa y se cuenta, pero no interrumpe las descargas.
"""
from __future__ import annotations

import inspect
import sys
from typing import Callable

_post_download: list[tuple[str, Callable]] = []
stats: dict[str, int] = {"errors": 0, "synced": 0}


def register_post_download(fn: Callable, name: str = "Hook") -> None:
    _post_download.append((name, fn))


def clear() -> None:
    _post_download.clear()
    stats["errors"] = 0
    stats["synced"] = 0


async def run_post_download(**context) -> None:
    for name, fn in list(_post_download):
        try:
            result = fn(**context)
            if inspect.isawaitable(result):
                await result
        except Exception as error:  # noqa: BLE001 - nunca cortar la descarga
            stats["errors"] += 1
            print(f"  ERROR [{name}]: {error}", file=sys.stderr)
            from . import run_log

            account = context.get("account")
            provider = context.get("provider")
            run_log.log_error(
                getattr(provider, "name", "-"),
                getattr(account, "client_number", None),
                f"{name}: {error}",
            )
