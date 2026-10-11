"""
core/session_store.py
---------------------
Persiste credenciales de sesión por proveedor para evitar el login al browser.
Los archivos se guardan en <repo_root>/.sessions/<provider>.json (gitignoreado).

Flujo de uso:
    session_store.save(provider_key, session_data)
    data = session_store.load(provider_key)
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

_STORE_DIR = Path(__file__).parent.parent / ".sessions"


# ─── Persistencia ───────────────────────────────────────────────────────────

def _path(provider: str) -> Path:
    _STORE_DIR.mkdir(exist_ok=True)
    return _STORE_DIR / f"{provider}.json"


def save(provider: str, data: dict) -> None:
    """Guarda credenciales de sesión en disco."""
    _path(provider).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def load(provider: str) -> dict | None:
    """Carga credenciales guardadas. Devuelve None si no existe o está corrupto."""
    p = _path(provider)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear(provider: str) -> None:
    """Borra credenciales guardadas (p.ej. tras sesión inválida o logout)."""
    _path(provider).unlink(missing_ok=True)


# ─── Validación de JWT ───────────────────────────────────────────────────────

def jwt_is_valid(token: str, buffer_secs: int = 300) -> bool:
    """
    True si el JWT no está expirado (con `buffer_secs` segundos de margen).
    Si el JWT no tiene claim 'exp', se asume válido.
    """
    if not token:
        return False
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = claims.get("exp")
        if exp is None:
            return True
        return float(time.time()) < float(exp) - buffer_secs
    except Exception:
        return False


# ─── Probe de sesión vía HTTP ────────────────────────────────────────────────

async def probe(
    url: str,
    headers: dict | None = None,
    cookies: dict | None = None,
    verify: bool = False,
) -> bool:
    """
    Hace un GET al `url` con las credenciales dadas.
    Devuelve True si el servidor responde 2xx (sesión válida).
    """
    import httpx
    try:
        async with httpx.AsyncClient(
            headers=headers or {},
            cookies=cookies or {},
            follow_redirects=True,
            timeout=10,
            verify=verify,
        ) as client:
            r = await client.get(url)
            return r.status_code < 400
    except Exception:
        return False


# ─── Serialización de cuentas ────────────────────────────────────────────────

def accounts_to_list(accounts: list) -> list[dict]:
    """Serializa una lista de Account a dicts guardables en JSON."""
    return [
        {
            "client_number": a.client_number,
            "display_name": a.display_name,
            "address": a.address,
            "extra": a.extra or {},
        }
        for a in accounts
    ]


def accounts_from_list(data: list[dict]) -> list:
    """Deserializa una lista de dicts (del JSON) a objetos Account."""
    from core.accounts import Account
    return [
        Account(
            client_number=d["client_number"],
            display_name=d["display_name"],
            address=d["address"],
            extra=d.get("extra", {}),
        )
        for d in data
        if isinstance(d, dict) and d.get("client_number")
    ]
