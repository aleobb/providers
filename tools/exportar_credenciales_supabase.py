#!/usr/bin/env python3
"""Copia tus perfiles de credenciales locales (SQLite) a Supabase, cifrados en Vault.

Uso (en tu PC, donde está tu SQLite y PROVIDERS_CREDENTIALS_KEY):
    python tools/exportar_credenciales_supabase.py --dry-run   # solo muestra qué haría
    python tools/exportar_credenciales_supabase.py             # sube los perfiles

Necesita SUPABASE_URL y SUPABASE_SERVICE_KEY. No imprime contraseñas.
Es repetible: un perfil que ya existe en Supabase se actualiza.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from core.credential_store import CredentialStore, CredentialStoreError  # noqa: E402
from integrations.supabase_sync.client import (  # noqa: E402
    SupabaseClient,
    SupabaseConfigurationError,
    SupabaseError,
)

# Variables no secretas que cada portal usa y que conviene tener en Supabase.
_CONFIG_ENV = {"visa": ["VISA_BANCO"], "mastercard": ["MASTERCARD_BANCO"]}


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    load_dotenv()
    try:
        store = CredentialStore()
        client = SupabaseClient()
    except (CredentialStoreError, SupabaseConfigurationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    try:
        portals = {p["codigo"]: p for p in client.select("proveedor_portales", {"select": "id,codigo,config"})}
    except SupabaseError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    total = 0
    for provider in store.list_providers():
        profiles = store.list_profiles(provider.name)
        if not profiles:
            continue
        portal = portals.get(provider.name)
        if portal is None:
            print(f"- {provider.display_name}: no hay un portal «{provider.name}» en Supabase; se omite.")
            continue
        config = {
            name: os.environ[name]
            for name in _CONFIG_ENV.get(provider.name, [])
            if os.environ.get(name)
        }
        print(f"- {provider.display_name}: {len(profiles)} perfil(es)" + (f"; config: {', '.join(config)}" if config else ""))
        if dry_run:
            continue
        if config:
            client.update("proveedor_portales", {"id": f"eq.{portal['id']}"}, {"config": {**(portal.get("config") or {}), **config}})
        for summary in profiles:
            profile = store.get_profile(summary.id)
            existing = client.select_one(
                "portal_perfiles",
                {"portal_id": f"eq.{portal['id']}", "alias": f"eq.{profile.alias}", "select": "id"},
            )
            profile_id = existing["id"] if existing else client.insert_one(
                "portal_perfiles", {"portal_id": portal["id"], "alias": profile.alias}
            )["id"]
            client.rpc("set_perfil_credenciales", {"p_perfil_id": profile_id, "p_creds": profile.credentials})
            print(f"    · {profile.alias}: {'actualizado' if existing else 'creado'}")
            total += 1
    print(f"\n{'Simulación terminada' if dry_run else f'{total} perfil(es) subido(s) a Supabase'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
