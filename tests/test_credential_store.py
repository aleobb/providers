import os
import sqlite3

import pytest
from cryptography.fernet import Fernet

from core.credential_cli import _prompt_credentials
from core.credential_store import (
    CredentialProfile,
    CredentialStore,
    CredentialStoreError,
)
from core.provider import Provider
from core.registry import all_providers
from providers.edenor.config import EdenorConfig
from providers.edesur import EdesurProvider
from providers.visa.config import VisaConfig
from providers.visa import VisaProvider


@pytest.fixture
def credential_store(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PROVIDERS_CREDENTIALS_KEY", Fernet.generate_key().decode("ascii")
    )
    return CredentialStore(tmp_path / "credentials.sqlite3")


def test_profiles_are_encrypted_and_can_coexist_per_provider(credential_store):
    first_id = credential_store.add_profile(
        "edenor",
        "Casa",
        {"email": "first@example.com", "password": "first-secret"},
    )
    second_id = credential_store.add_profile(
        "edenor",
        "Trabajo",
        {"email": "second@example.com", "password": "second-secret"},
    )

    assert [profile.alias for profile in credential_store.list_profiles("edenor")] == [
        "Casa",
        "Trabajo",
    ]
    assert credential_store.get_profile(first_id).credentials["password"] == "first-secret"
    assert credential_store.get_profile(second_id).credentials["email"] == "second@example.com"

    raw_database = credential_store.database_path.read_bytes()
    assert b"first-secret" not in raw_database
    assert b"second-secret" not in raw_database


def test_database_normalizes_providers_and_clients(credential_store):
    credential_store.add_profile(
        "edenor", "Casa", {"email": "home@example.com", "password": "secret"}
    )
    credential_store.add_profile(
        "edenor", "Trabajo", {"email": "work@example.com", "password": "secret"}
    )

    with sqlite3.connect(credential_store.database_path) as connection:
        providers = connection.execute(
            "SELECT id, name FROM providers WHERE name = 'edenor'"
        ).fetchall()
        clients = connection.execute(
            """
            SELECT clients.alias, providers.name
            FROM clients
            JOIN providers ON providers.id = clients.provider_id
            WHERE providers.name = 'edenor'
            ORDER BY clients.alias
            """
        ).fetchall()
        client_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(clients)")
        }
        foreign_keys = connection.execute("PRAGMA foreign_key_list(clients)").fetchall()

    assert len(providers) == 1
    assert [(row[0], row[1]) for row in clients] == [
        ("Casa", "edenor"),
        ("Trabajo", "edenor"),
    ]
    assert "provider" not in client_columns
    assert "provider_id" in client_columns
    assert any(
        row[2] == "providers" and row[3] == "provider_id" for row in foreign_keys
    )


def test_provider_labels_and_credential_fields_are_read_from_database(
    credential_store,
):
    with sqlite3.connect(credential_store.database_path) as connection:
        connection.execute(
            "UPDATE providers SET display_name = 'Edenor residencial' "
            "WHERE name = 'edenor'"
        )
        connection.execute(
            """
            UPDATE provider_credential_fields
            SET label = 'Correo de acceso'
            WHERE field_name = 'email'
              AND provider_id = (
                  SELECT id FROM providers WHERE name = 'edenor'
              )
            """
        )

    restarted_store = CredentialStore(credential_store.database_path)

    assert restarted_store.get_provider("edenor").display_name == (
        "Edenor residencial"
    )
    assert restarted_store.get_credential_fields("edenor")[0].label == (
        "Correo de acceso"
    )


def test_registered_providers_share_the_abstract_contract():
    providers = all_providers()

    assert providers
    assert all(isinstance(provider, Provider) for provider in providers)


def test_edesur_applies_its_provider_specific_url_option():
    provider = EdesurProvider()
    url = "https://example.com/invoice"

    provider.apply_run_options(url=url)

    assert provider.get_config().docuprint_url == url


def test_visa_configures_a_session_file_for_each_credential_profile(tmp_path):
    provider = VisaProvider()
    profile = CredentialProfile(
        id=12,
        provider="visa",
        alias="Personal",
        session_version="abc123",
        credentials={
            "documento_nacional_de_identidad": "12345678",
            "usuario": "visa-user",
            "password": "secret",
        },
    )
    sessions_directory = tmp_path / "sessions"

    provider.configure_credentials(profile, 1, sessions_directory)

    assert provider.session_key == "visa-12-abc123"
    assert provider.get_config().session_file == (
        sessions_directory / "visa-12-abc123_session.json"
    )
    assert provider.get_config().email == ""
    assert provider.get_config().password == "secret"


def test_legacy_credential_profiles_are_migrated_to_clients(
    credential_store,
):
    profile_id = credential_store.add_profile(
        "edenor",
        "Casa",
        {"email": "home@example.com", "password": "legacy-secret"},
    )
    database_path = credential_store.database_path
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TABLE clients")
        connection.execute("DROP TABLE provider_credential_fields")
        connection.execute("DROP TABLE providers")
        connection.execute(
            """
            CREATE TABLE credential_profiles (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                alias TEXT NOT NULL,
                encrypted_credentials BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, alias)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO credential_profiles
                (id, provider, alias, encrypted_credentials)
            VALUES (?, ?, ?, ?)
            """,
            (
                profile_id,
                "edenor",
                "Casa",
                credential_store._encrypt(
                    {"email": "home@example.com", "password": "legacy-secret"}
                ),
            ),
        )

    migrated_store = CredentialStore(credential_store.database_path)

    migrated_profile = migrated_store.get_profile(profile_id)
    with sqlite3.connect(credential_store.database_path) as connection:
        legacy_table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'credential_profiles'
            """
        ).fetchone()

    assert migrated_profile.provider == "edenor"
    assert migrated_profile.alias == "Casa"
    assert migrated_profile.credentials["password"] == "legacy-secret"
    assert legacy_table is None


def test_wrong_encryption_key_fails_when_profile_is_decrypted(
    credential_store, monkeypatch, tmp_path
):
    profile_id = credential_store.add_profile(
        "edenor", "Casa", {"email": "user@example.com", "password": "secret"}
    )
    monkeypatch.setenv(
        "PROVIDERS_CREDENTIALS_KEY", Fernet.generate_key().decode("ascii")
    )

    with pytest.raises(CredentialStoreError, match="misma que se usó"):
        CredentialStore(credential_store.database_path).get_profile(profile_id)


def test_legacy_dotenv_is_imported_once_and_secret_lines_are_removed(
    credential_store, monkeypatch, tmp_path
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EDENOR_EMAIL=old@example.com\n"
        "EDENOR_PASSWORD=legacy-secret\n"
        "GOOGLE_DRIVE_FOLDER_ID=folder-id\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EDENOR_PASSWORD", "legacy-secret")

    assert credential_store.import_legacy_dotenv_once(env_file) == 1
    profile = credential_store.get_profile(
        credential_store.list_profiles("edenor")[0].id
    )
    assert profile.alias == "old@example.com"
    assert profile.credentials == {
        "email": "old@example.com",
        "password": "legacy-secret",
    }
    assert "legacy-secret" not in env_file.read_text(encoding="utf-8")
    assert "GOOGLE_DRIVE_FOLDER_ID=folder-id" in env_file.read_text(encoding="utf-8")
    assert "EDENOR_PASSWORD" not in os.environ

    env_file.write_text("EDENOR_PASSWORD=should-not-import-again\n", encoding="utf-8")
    assert credential_store.import_legacy_dotenv_once(env_file) == 0
    assert len(credential_store.list_profiles("edenor")) == 1
    assert "should-not-import-again" in env_file.read_text(encoding="utf-8")


def test_credential_values_are_not_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("EDENOR_EMAIL", "plaintext@example.com")
    monkeypatch.setenv("EDENOR_PASSWORD", "plaintext-secret")
    config = EdenorConfig()

    assert config.email == ""
    assert config.password == ""


def test_credentials_are_injected_and_visa_fields_remain_available():
    config = EdenorConfig(email="user@example.com", password="secret")
    assert config.email == "user@example.com"
    assert config.password == "secret"

    visa_config = VisaConfig(
        documento_nacional_de_identidad="12345678",
        usuario="visa-user",
        password="visa-secret",
        titular="Titular",
    )
    assert visa_config.documento_nacional_de_identidad == "12345678"
    assert visa_config.usuario == "visa-user"
    assert visa_config.password == "visa-secret"
    assert visa_config.titular == "Titular"


def test_profile_validation_reports_missing_login_fields(credential_store):
    credential_store.add_profile(
        "visa", "Incompleto", {"usuario": "visa-user"}
    )

    with pytest.raises(CredentialStoreError, match="DNI, Contraseña"):
        credential_store.request_credentials("visa")


def test_generic_credential_request_returns_valid_profile(credential_store):
    profile_id = credential_store.add_profile(
        "edenor", "Casa", {"email": "home@example.com", "password": "secret"}
    )

    profile = credential_store.request_credentials("edenor")

    assert profile.id == profile_id
    assert profile.credentials["password"] == "secret"


def test_editing_incomplete_visa_profile_requires_missing_credentials(
    credential_store, monkeypatch
):
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    with pytest.raises(CredentialStoreError, match="DNI es obligatorio"):
        _prompt_credentials(
            credential_store.get_credential_fields("visa"),
            {"titular": "Titular"},
            editing=True,
        )


def test_editing_incomplete_visa_profile_collects_required_fields(
    credential_store, monkeypatch
):
    answers = iter(["12345678", "visa-user", "Titular"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("core.credential_cli.getpass", lambda _prompt: "visa-secret")

    credentials = _prompt_credentials(
        credential_store.get_credential_fields("visa"),
        {"titular": "Titular"},
        editing=True,
    )

    assert credentials == {
        "documento_nacional_de_identidad": "12345678",
        "usuario": "visa-user",
        "password": "visa-secret",
        "titular": "Titular",
    }


def test_duplicate_alias_is_rejected(credential_store):
    credential_store.add_profile(
        "edenor", "Casa", {"email": "user@example.com", "password": "secret"}
    )

    with pytest.raises(CredentialStoreError, match="Ya existe el alias"):
        credential_store.add_profile(
            "edenor", "Casa", {"email": "another@example.com", "password": "secret"}
        )


def test_choosing_between_profiles_uses_interactive_selection(
    credential_store, monkeypatch
):
    credential_store.add_profile(
        "edenor", "Casa", {"email": "home@example.com", "password": "home-secret"}
    )
    work_id = credential_store.add_profile(
        "edenor", "Trabajo", {"email": "work@example.com", "password": "work-secret"}
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    selected = credential_store.choose_profile("edenor")

    assert selected.id == work_id
    assert selected.alias == "Trabajo"


def test_updating_credentials_changes_profile_session_version(credential_store):
    profile_id = credential_store.add_profile(
        "edenor", "Casa", {"email": "old@example.com", "password": "old-secret"}
    )
    original_version = credential_store.get_profile(profile_id).session_version
    credential_store.update_profile(
        profile_id, "Casa", {"email": "new@example.com", "password": "new-secret"}
    )

    updated = credential_store.get_profile(profile_id)
    assert updated.session_version != original_version
    assert updated.credentials["email"] == "new@example.com"
