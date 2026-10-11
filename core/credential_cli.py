from __future__ import annotations

from getpass import getpass

from .provider import CredentialField
from .credential_store import (
    CredentialProfile,
    CredentialProfileSummary,
    CredentialStore,
    CredentialStoreError,
)


def manage_credentials(store: CredentialStore) -> None:
    while True:
        providers = store.list_providers()
        print("\nGestión de credenciales")
        for index, provider in enumerate(providers, 1):
            print(f"  {index}. {provider.display_name}")
        print("  0. Salir")
        choice = input("Elige un proveedor: ").strip()
        if choice == "0":
            return
        try:
            provider = providers[int(choice) - 1]
        except (ValueError, IndexError):
            print("Selección inválida.")
            continue
        _manage_provider(store, provider.name)


def _manage_provider(store: CredentialStore, provider: str) -> None:
    provider_details = store.get_provider(provider)
    while True:
        profiles = store.list_profiles(provider)
        print(f"\n{provider_details.display_name} — perfiles guardados:")
        _print_profiles(profiles)
        print("  A. Agregar perfil")
        print("  E. Editar perfil")
        print("  B. Borrar perfil")
        print("  0. Volver")
        choice = input("Acción: ").strip().lower()
        if choice == "0":
            return
        try:
            if choice == "a":
                _add_profile(store, provider)
            elif choice == "e":
                profile = _select_profile(store, profiles)
                if profile:
                    _edit_profile(store, profile)
            elif choice == "b":
                profile = _select_profile(store, profiles)
                if profile and input(
                    f"¿Borrar «{profile.alias}»? [s/N]: "
                ).strip().lower() == "s":
                    store.delete_profile(profile.id)
                    print("Perfil borrado.")
            else:
                print("Acción inválida.")
        except CredentialStoreError as exc:
            print(f"Error: {exc}")


def _print_profiles(profiles: list[CredentialProfileSummary]) -> None:
    if not profiles:
        print("  (ninguno)")
        return
    for profile in profiles:
        print(f"  - {profile.alias}")


def _select_profile(
    store: CredentialStore,
    profiles: list[CredentialProfileSummary],
) -> CredentialProfile | None:
    if not profiles:
        print("No hay perfiles para seleccionar.")
        return None
    for index, profile in enumerate(profiles, 1):
        print(f"  {index}. {profile.alias}")
    try:
        choice = int(input("Elige un perfil: ").strip()) - 1
    except ValueError:
        print("Selección inválida.")
        return None
    if not 0 <= choice < len(profiles):
        print("Selección inválida.")
        return None
    return store.get_profile(profiles[choice].id)


def _add_profile(store: CredentialStore, provider: str) -> None:
    alias = input("Alias del perfil: ").strip()
    if not alias:
        print("El alias del perfil no puede estar vacío.")
        return
    credentials = _prompt_credentials(store.get_credential_fields(provider), {})
    store.add_profile(provider, alias, credentials)
    print("Perfil guardado cifrado en la base de datos.")


def _edit_profile(store: CredentialStore, profile: CredentialProfile) -> None:
    alias = input(f"Alias [{profile.alias}]: ").strip() or profile.alias
    credentials = _prompt_credentials(
        store.get_credential_fields(profile.provider),
        profile.credentials,
        editing=True,
    )
    store.update_profile(profile.id, alias, credentials)
    print("Perfil actualizado.")


def _prompt_credentials(
    fields: list[CredentialField],
    existing: dict[str, str],
    *,
    editing: bool = False,
) -> dict[str, str]:
    values = dict(existing)
    for field in fields:
        field_name = field.name
        label = field.label
        if not field.required:
            label = f"{label} (opcional)"
        current = values.get(field_name, "")
        missing_required = field.required and not current.strip()
        if field.secret:
            if editing and missing_required:
                prompt = f"{label} (obligatorio)"
            else:
                prompt = f"{label} (vacío para conservar)" if editing else label
            value = getpass(f"{prompt}: ")
        else:
            if editing and missing_required:
                prompt = f"{label} (obligatorio)"
            else:
                prompt = (
                    f"{label} [{current}] (vacío para conservar)"
                    if editing
                    else label
                )
            value = input(f"{prompt}: ").strip()
        if value:
            values[field_name] = value
        elif missing_required:
            raise CredentialStoreError(f"{label} es obligatorio.")
        elif not editing:
            if field.required:
                raise CredentialStoreError(f"{label} es obligatorio.")
            values[field_name] = ""
    return values
