import json
from types import SimpleNamespace

from providers.telecentro.login import LoginOrchestrator


def _orchestrator():
    return LoginOrchestrator(
        SimpleNamespace(),
        SimpleNamespace(email="person@example.com", password="test-password"),
    )


def test_telecentro_diagnostics_only_match_the_auth_domain():
    orchestrator = _orchestrator()

    assert orchestrator._is_auth_request(
        "https://apiext.telecentro.net.ar/login"
    )
    assert not orchestrator._is_auth_request(
        "https://sub.apiext.telecentro.net.ar/login"
    )
    assert not orchestrator._is_auth_request(
        "https://telecentro.net.ar.example.net/login"
    )


def test_telecentro_diagnostics_omit_query_and_redact_secrets():
    orchestrator = _orchestrator()
    orchestrator._jwt = "captured-jwt"

    safe_url = orchestrator._safe_url(
        "https://apiext.telecentro.net.ar/auth/continue?token=secret"
    )
    summary = orchestrator._summarize_body(
        json.dumps(
            {
                "error": "Request error",
                "message": "Login failed for person@example.com",
            }
        ),
        "application/json",
    )

    assert safe_url == "apiext.telecentro.net.ar/auth/continue"
    assert "secret" not in safe_url
    assert "Request error" in summary
    assert "person@example.com" not in summary
    assert "[redacted]" in summary
    assert "captured-jwt" not in orchestrator._redact("captured-jwt")
