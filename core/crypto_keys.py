"""Clave(s) Fernet de las credenciales: admite varias separadas por coma (rotación).

La primera cifra y todas descifran, igual que `apps/finanzas/src/lib/credenciales.ts` en el Worker.
Para rotar: poner la clave nueva primero (`nueva,vieja`), volver a guardar los perfiles y, cuando todo
descifre con la nueva, quitar la vieja.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, MultiFernet


def build_cipher(raw: str) -> MultiFernet:
    """Arma el cifrador desde `PROVIDERS_CREDENTIALS_KEY`. Lanza ValueError si alguna clave no es válida."""
    keys = [part.strip() for part in raw.split(",") if part.strip()]
    if not keys:
        raise ValueError("No hay ninguna clave Fernet.")
    return MultiFernet([Fernet(key.encode("ascii")) for key in keys])
