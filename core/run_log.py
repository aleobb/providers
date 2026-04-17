"""
Registro persistente de ejecuciones del script.

Guarda una línea por evento en `./ejecucion.log` con el formato:
  [YYYY-MM-DD HH:MM:SS] PROVEEDOR | ESTADO | CUENTA | DETALLE
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_LOG_FILE = Path(__file__).parent.parent / "ejecucion.log"

# Ancho fijo para columnas de proveedor y estado
_COL_PROV = 14
_COL_STATUS = 11


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write(line: str) -> None:
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"  [log] No se pudo escribir en {_LOG_FILE}: {e}", file=sys.stderr)


def log_ok(provider: str, account_id: str, period: str, path: Path) -> None:
    """Descarga exitosa."""
    detail = f"{period}  →  {path.name}"
    _write(
        f"[{_now()}]  {provider:<{_COL_PROV}}  {'OK':<{_COL_STATUS}}  N°{account_id:<12}  {detail}"
    )


def log_error(provider: str, account_id: str | None, error: str) -> None:
    """Error de descarga o login (credenciales, navegación, etc.)."""
    acct = f"N°{account_id}" if account_id else "-"
    _write(
        f"[{_now()}]  {provider:<{_COL_PROV}}  {'ERROR':<{_COL_STATUS}}  {acct:<14}  {error}"
    )


def log_server_down(provider: str, error: str) -> None:
    """El servidor del proveedor no está disponible (HTTP 500/503, 'intente más tarde', etc.)."""
    _write(
        f"[{_now()}]  {provider:<{_COL_PROV}}  {'SERVER_DOWN':<{_COL_STATUS}}  {'-':<14}  {error}"
    )


def log_run_start(providers: list[str]) -> None:
    """Marca el inicio de una ejecución."""
    sep = "-" * 60
    _write(f"[{_now()}]  {sep}")
    _write(
        f"[{_now()}]  {'INICIO':<{_COL_PROV}}  {'':<{_COL_STATUS}}  {'':<14}  proveedores: {', '.join(providers)}"
    )
