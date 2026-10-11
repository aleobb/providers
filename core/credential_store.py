from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from cryptography.fernet import Fernet, InvalidToken
from dotenv import dotenv_values

from .provider import CredentialField


_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATABASE = _ROOT / ".credentials" / "providers.sqlite3"
_KEY_ENV_VAR = "PROVIDERS_CREDENTIALS_KEY"
_MIGRATION_KEY = "legacy_dotenv_imported"


class CredentialStoreError(RuntimeError):
    """Error de configuración o acceso al almacén de credenciales."""


@dataclass(frozen=True)
class CredentialProfile:
    id: int
    provider: str
    alias: str
    session_version: str
    credentials: dict[str, str] = field(repr=False)


@dataclass(frozen=True)
class CredentialProfileSummary:
    id: int
    alias: str


@dataclass(frozen=True)
class CredentialProviderSummary:
    name: str
    display_name: str


class CredentialStore:
    """Almacena proveedores y perfiles de cliente cifrados en SQLite."""

    def __init__(self, database_path: Path | None = None) -> None:
        raw_key = os.environ.get(_KEY_ENV_VAR, "").strip()
        if not raw_key:
            raise CredentialStoreError(
                f"Falta {_KEY_ENV_VAR}. Genera una clave Fernet y configúrala "
                "como variable de entorno antes de ejecutar el programa."
            )
        try:
            self._cipher = Fernet(raw_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise CredentialStoreError(
                f"{_KEY_ENV_VAR} no es una clave Fernet válida."
            ) from exc

        self.database_path = database_path or Path(
            os.environ.get("PROVIDERS_CREDENTIALS_DB", _DEFAULT_DATABASE)
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        return connection

    def _initialize(self) -> None:
        import providers  # noqa: F401

        from .registry import all_provider_classes

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS providers (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL DEFAULT ''
                )
                """
            )
            provider_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(providers)")
            }
            if "display_name" not in provider_columns:
                connection.execute(
                    "ALTER TABLE providers ADD COLUMN display_name TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY,
                    provider_id INTEGER NOT NULL
                        REFERENCES providers(id) ON DELETE CASCADE,
                    alias TEXT NOT NULL,
                    encrypted_credentials BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(provider_id, alias)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS credential_store_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_credential_fields (
                    provider_id INTEGER NOT NULL
                        REFERENCES providers(id) ON DELETE CASCADE,
                    field_name TEXT NOT NULL,
                    label TEXT NOT NULL,
                    required INTEGER NOT NULL DEFAULT 1,
                    secret INTEGER NOT NULL DEFAULT 0,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (provider_id, field_name)
                )
                """
            )
            for provider_class in all_provider_classes():
                connection.execute(
                    """
                    INSERT INTO providers (name, display_name)
                    VALUES (?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        display_name = CASE
                            WHEN providers.display_name = ''
                            THEN excluded.display_name
                            ELSE providers.display_name
                        END
                    """,
                    (provider_class.name, provider_class.display_name),
                )
                provider_id = self._provider_id(connection, provider_class.name)
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO provider_credential_fields
                        (provider_id, field_name, label, required, secret, position)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            provider_id,
                            field.name,
                            field.label,
                            int(field.required),
                            int(field.secret),
                            position,
                        )
                        for position, field in enumerate(
                            provider_class.credential_fields
                        )
                    ),
                )
            legacy_table = connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'credential_profiles'
                """
            ).fetchone()
            if legacy_table:
                legacy_profiles = connection.execute(
                    """
                    SELECT id, provider, alias, encrypted_credentials,
                           created_at, updated_at
                    FROM credential_profiles
                    """
                ).fetchall()
                for profile in legacy_profiles:
                    provider_id = self._provider_id(
                        connection, profile["provider"]
                    )
                    connection.execute(
                        """
                        INSERT INTO clients
                            (id, provider_id, alias, encrypted_credentials,
                             created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            provider_id = excluded.provider_id,
                            alias = excluded.alias,
                            encrypted_credentials = excluded.encrypted_credentials,
                            created_at = excluded.created_at,
                            updated_at = excluded.updated_at
                        """,
                        (
                            profile["id"],
                            provider_id,
                            profile["alias"],
                            profile["encrypted_credentials"],
                            profile["created_at"],
                            profile["updated_at"],
                        ),
                    )
                connection.execute("DROP TABLE credential_profiles")

    def list_providers(self) -> list[CredentialProviderSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name, display_name FROM providers ORDER BY name"
            ).fetchall()
        return [
            CredentialProviderSummary(
                name=row["name"], display_name=row["display_name"]
            )
            for row in rows
        ]

    def get_provider(self, provider: str) -> CredentialProviderSummary:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT name, display_name FROM providers WHERE name = ?",
                (provider.lower(),),
            ).fetchone()
        if row is None:
            raise CredentialStoreError(f"Proveedor desconocido: {provider}.")
        return CredentialProviderSummary(
            name=row["name"], display_name=row["display_name"]
        )

    def get_credential_fields(self, provider: str) -> list[CredentialField]:
        with self._connect() as connection:
            provider_id = self._provider_id(connection, provider.lower())
            rows = connection.execute(
                """
                SELECT field_name, label, required, secret
                FROM provider_credential_fields
                WHERE provider_id = ?
                ORDER BY position, field_name
                """,
                (provider_id,),
            ).fetchall()
        return [
            CredentialField(
                name=row["field_name"],
                label=row["label"],
                required=bool(row["required"]),
                secret=bool(row["secret"]),
            )
            for row in rows
        ]

    def list_profiles(self, provider: str) -> list[CredentialProfileSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT clients.id, clients.alias
                FROM clients
                JOIN providers ON providers.id = clients.provider_id
                WHERE providers.name = ?
                ORDER BY clients.alias COLLATE NOCASE
                """,
                (provider.lower(),),
            ).fetchall()
        return [
            CredentialProfileSummary(id=row["id"], alias=row["alias"])
            for row in rows
        ]

    def get_profile(self, profile_id: int) -> CredentialProfile:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT clients.id, providers.name AS provider, clients.alias,
                       clients.encrypted_credentials
                FROM clients
                JOIN providers ON providers.id = clients.provider_id
                WHERE clients.id = ?
                """,
                (profile_id,),
            ).fetchone()
        if row is None:
            raise CredentialStoreError("No se encontró el perfil seleccionado.")
        return self._decode_profile(row)

    def add_profile(
        self, provider: str, alias: str, credentials: Mapping[str, str]
    ) -> int:
        provider = self._validate_provider(provider)
        alias = self._validate_alias(alias)
        encrypted = self._encrypt(credentials)
        try:
            with self._connect() as connection:
                provider_id = self._provider_id(connection, provider)
                cursor = connection.execute(
                    """
                    INSERT INTO clients
                        (provider_id, alias, encrypted_credentials)
                    VALUES (?, ?, ?)
                    """,
                    (provider_id, alias, encrypted),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise CredentialStoreError(
                f"Ya existe el alias «{alias}» para {provider}."
            ) from exc

    def update_profile(
        self, profile_id: int, alias: str, credentials: Mapping[str, str]
    ) -> None:
        alias = self._validate_alias(alias)
        encrypted = self._encrypt(credentials)
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE clients
                    SET alias = ?, encrypted_credentials = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (alias, encrypted, profile_id),
                )
                if cursor.rowcount == 0:
                    raise CredentialStoreError("No se encontró el perfil indicado.")
        except sqlite3.IntegrityError as exc:
            raise CredentialStoreError(
                f"Ya existe el alias «{alias}» para este proveedor."
            ) from exc

    def delete_profile(self, profile_id: int) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM clients WHERE id = ?", (profile_id,)
            )
            if cursor.rowcount == 0:
                raise CredentialStoreError("No se encontró el perfil indicado.")

    def choose_profile(self, provider: str) -> CredentialProfile:
        provider_details = self.get_provider(provider)
        profiles = self.list_profiles(provider)
        if not profiles:
            raise CredentialStoreError(
                f"No hay credenciales guardadas para {provider_details.display_name}. "
                "Ejecuta «python main.py --gestionar-credenciales» para agregarlas."
            )
        if len(profiles) == 1:
            return self.get_profile(profiles[0].id)

        print(f"\nCredenciales guardadas para {provider_details.display_name}:")
        for index, profile in enumerate(profiles, 1):
            print(f"  {index}. {profile.alias}")
        while True:
            selected = input("Elige un perfil: ").strip()
            try:
                profile_index = int(selected) - 1
            except ValueError:
                profile_index = -1
            if 0 <= profile_index < len(profiles):
                return self.get_profile(profiles[profile_index].id)
            print(f"Ingresa un número entre 1 y {len(profiles)}.")

    def request_credentials(self, provider: str) -> CredentialProfile:
        """Select and validate the credentials required by a provider."""
        profile = self.choose_profile(provider)
        self.validate_profile_credentials(profile)
        return profile

    def validate_profile_credentials(self, profile: CredentialProfile) -> None:
        fields = self.get_credential_fields(profile.provider)
        missing = [
            field.label
            for field in fields
            if field.required and not profile.credentials.get(field.name, "").strip()
        ]
        if missing:
            provider = self.get_provider(profile.provider)
            raise CredentialStoreError(
                f"El perfil «{profile.alias}» de {provider.display_name} está "
                f"incompleto: falta {', '.join(missing)}. "
                "Complétalo en el gestor de credenciales."
            )

    def import_legacy_dotenv_once(self, env_file: Path) -> int:
        """Importa perfiles de credenciales del .env y quita esas líneas una vez."""
        env_file = env_file.resolve()
        providers = self.list_providers()
        fields_by_provider = {
            provider.name: self.get_credential_fields(provider.name)
            for provider in providers
        }
        legacy_names = {
            f"{provider.upper()}_{field.name.upper()}"
            for provider, fields in fields_by_provider.items()
            for field in fields
        }
        with self._connect() as connection:
            already_imported = connection.execute(
                "SELECT 1 FROM credential_store_metadata WHERE key = ?",
                (_MIGRATION_KEY,),
            ).fetchone()
        if already_imported:
            self._clear_legacy_environment(legacy_names)
            return 0

        parsed_values = dotenv_values(env_file) if env_file.exists() else {}
        imported = 0
        for provider, fields in fields_by_provider.items():
            credentials = {
                field.name: str(
                    parsed_values[f"{provider.upper()}_{field.name.upper()}"]
                )
                for field in fields
                if parsed_values.get(f"{provider.upper()}_{field.name.upper()}")
            }
            if not credentials:
                continue
            alias = (
                credentials.get("email")
                or credentials.get("usuario")
                or "principal"
            )
            self._upsert_imported_profile(provider, alias, credentials)
            imported += 1

        if env_file.exists():
            original = env_file.read_text(encoding="utf-8")
            cleaned_lines = [
                line
                for line in original.splitlines(keepends=True)
                if not self._is_legacy_credential_line(line, legacy_names)
            ]
            cleaned = "".join(cleaned_lines)
            if cleaned != original:
                temporary_file = env_file.with_suffix(env_file.suffix + ".tmp")
                try:
                    temporary_file.write_text(cleaned, encoding="utf-8")
                    temporary_file.replace(env_file)
                except OSError as exc:
                    temporary_file.unlink(missing_ok=True)
                    raise CredentialStoreError(
                        "Las credenciales se importaron a SQLite, pero no se pudo "
                        f"quitar las líneas antiguas de {env_file}. Elimínalas "
                        "manualmente para que no sigan en texto plano."
                    ) from exc

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO credential_store_metadata (key, value)
                VALUES (?, CURRENT_TIMESTAMP)
                """,
                (_MIGRATION_KEY,),
            )
        self._clear_legacy_environment(legacy_names)
        return imported

    def _upsert_imported_profile(
        self, provider: str, alias: str, credentials: Mapping[str, str]
    ) -> None:
        with self._connect() as connection:
            provider_id = self._provider_id(connection, provider)
            connection.execute(
                """
                INSERT INTO clients
                    (provider_id, alias, encrypted_credentials)
                VALUES (?, ?, ?)
                ON CONFLICT(provider_id, alias) DO UPDATE SET
                    encrypted_credentials = excluded.encrypted_credentials,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (provider_id, alias, self._encrypt(credentials)),
            )

    @staticmethod
    def _provider_id(connection: sqlite3.Connection, provider: str) -> int:
        row = connection.execute(
            "SELECT id FROM providers WHERE name = ?", (provider.lower(),)
        ).fetchone()
        if row is None:
            raise CredentialStoreError(f"No se encontró el proveedor {provider}.")
        return int(row["id"])

    def _encrypt(self, credentials: Mapping[str, str]) -> bytes:
        clean_values = {key: value for key, value in credentials.items() if key}
        payload = json.dumps(clean_values, ensure_ascii=False).encode("utf-8")
        return self._cipher.encrypt(payload)

    def _decode_profile(self, row: sqlite3.Row) -> CredentialProfile:
        try:
            credentials = json.loads(
                self._cipher.decrypt(row["encrypted_credentials"]).decode("utf-8")
            )
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CredentialStoreError(
                "No se pudieron descifrar las credenciales. Verifica "
                f"{_KEY_ENV_VAR}; la clave debe ser la misma que se usó al guardarlas."
            ) from exc
        return CredentialProfile(
            id=row["id"],
            provider=row["provider"],
            alias=row["alias"],
            session_version=hashlib.sha256(
                row["encrypted_credentials"]
            ).hexdigest()[:12],
            credentials=credentials,
        )

    def _validate_provider(self, provider: str) -> str:
        normalized = provider.lower()
        self.get_provider(normalized)
        return normalized

    @staticmethod
    def _validate_alias(alias: str) -> str:
        alias = alias.strip()
        if not alias:
            raise CredentialStoreError("El alias del perfil no puede estar vacío.")
        return alias

    @staticmethod
    def _is_legacy_credential_line(line: str, credential_names: set[str]) -> bool:
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        return bool(match and match.group(1).upper() in credential_names)

    @staticmethod
    def _clear_legacy_environment(credential_names: set[str]) -> None:
        for name in credential_names:
            os.environ.pop(name, None)
