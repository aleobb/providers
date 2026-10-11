import pytest
from cryptography.fernet import Fernet

from core.credential_cli import _prompt_credentials
from core.credential_store import (
    CredentialProfile,
    CredentialStore,
    CredentialStoreError,
)
from providers.visa import VisaProvider
from providers.visa.config import VisaConfig


@pytest.fixture
def credential_store(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PROVIDERS_CREDENTIALS_KEY", Fernet.generate_key().decode("ascii")
    )
    return CredentialStore(tmp_path / "credentials.sqlite3")


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


def test_visa_config_exposes_provider_specific_credential_fields():
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


def test_visa_profile_validation_reports_missing_login_fields(credential_store):
    credential_store.add_profile(
        "visa", "Incompleto", {"usuario": "visa-user"}
    )

    with pytest.raises(CredentialStoreError, match="DNI, Contraseña"):
        credential_store.request_credentials("visa")


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
