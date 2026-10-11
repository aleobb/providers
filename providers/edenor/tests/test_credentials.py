from providers.edenor.config import EdenorConfig


def test_credential_values_are_not_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("EDENOR_EMAIL", "plaintext@example.com")
    monkeypatch.setenv("EDENOR_PASSWORD", "plaintext-secret")
    config = EdenorConfig()

    assert config.email == ""
    assert config.password == ""


def test_credentials_are_injected_into_provider_config():
    config = EdenorConfig(email="user@example.com", password="secret")

    assert config.email == "user@example.com"
    assert config.password == "secret"
