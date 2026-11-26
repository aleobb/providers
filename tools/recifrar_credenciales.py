#!/usr/bin/env python3
"""Vuelve a cifrar `portal_perfiles.credenciales_enc` con la primera clave de PROVIDERS_CREDENTIALS_KEY.

Rotación de la clave Fernet (docs/OPERACIONES.md §8):
  1. Poner la clave nueva primero y dejar la vieja detrás, separadas por coma: `nueva,vieja`
     (en este repo y en el secret CREDENTIALS_KEY del Worker de finanzas).
  2. Correr esta herramienta: descifra con cualquiera de las claves y guarda con la primera.
  3. Verificar una ejecución y, recién entonces, quitar la clave vieja de todos los lugares.

Uso:
    python tools/recifrar_credenciales.py --dry-run   # cuenta cuántos perfiles descifra, sin escribir
    python tools/recifrar_credenciales.py             # recifra y guarda

Necesita SUPABASE_URL, SUPABASE_SERVICE_KEY y PROVIDERS_CREDENTIALS_KEY. No imprime valores: solo ids.
Es repetible: volver a correrla recifra con la misma clave primera sin cambiar el contenido.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.fernet import InvalidToken  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from core.crypto_keys import build_cipher  # noqa: E402
from integrations.supabase_sync.client import (  # noqa: E402
    SupabaseClient,
    SupabaseConfigurationError,
    SupabaseError,
)


def recifrar(client, cipher, dry_run: bool = False) -> tuple[list[int], list[int]]:
    """Devuelve (ids recifrados, ids que ninguna clave pudo descifrar)."""
    hechos: list[int] = []
    fallidos: list[int] = []
    perfiles = client.select("portal_perfiles", {"select": "id,credenciales_enc", "order": "id"})
    for perfil in perfiles:
        token = perfil.get("credenciales_enc")
        if not token:
            continue
        try:
            nuevo = cipher.rotate(token.encode("ascii")).decode("ascii")
        except InvalidToken:
            fallidos.append(int(perfil["id"]))
            continue
        if not dry_run:
            client.update("portal_perfiles", {"id": f"eq.{perfil['id']}"}, {"credenciales_enc": nuevo})
        hechos.append(int(perfil["id"]))
    return hechos, fallidos


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    load_dotenv()
    try:
        client = SupabaseClient()
        cipher = build_cipher(os.environ["PROVIDERS_CREDENTIALS_KEY"])
    except (SupabaseConfigurationError, KeyError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    try:
        hechos, fallidos = recifrar(client, cipher, dry_run)
    except SupabaseError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    verbo = "se recifrarían" if dry_run else "recifrados"
    print(f"Perfiles {verbo}: {len(hechos)} {hechos}")
    if fallidos:
        print(f"No se pudieron descifrar con ninguna clave (no se tocaron): {fallidos}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
