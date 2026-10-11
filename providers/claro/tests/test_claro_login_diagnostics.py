import asyncio
from types import SimpleNamespace

from providers.claro.login import LoginOrchestrator


def _orchestrator():
    return LoginOrchestrator(
        SimpleNamespace(),
        SimpleNamespace(email="person@example.com", password="secret"),
    )


def test_claro_diagnostics_url_omits_query_and_masks_long_path_segments():
    orchestrator = _orchestrator()

    safe_url = orchestrator._safe_url(
        "https://ingreso.claro.com.ar/login-actions/"
        "a-very-long-sensitive-session-value-0123456789?token=secret"
    )

    assert safe_url == "ingreso.claro.com.ar/login-actions/[redacted]"
    assert "secret" not in safe_url


def test_claro_diagnostics_summarize_error_id_and_redact_email():
    orchestrator = _orchestrator()

    summary = orchestrator._summarize_body(
        '{"error":"Request error","requestId":"a00514f2-e620-4843-bbff-2a6fdbaa400d",'
        '"message":"Login failed for person@example.com"}',
        "application/json",
    )

    assert "Request error" in summary
    assert "a00514f2-e620-4843-bbff-2a6fdbaa400d" in summary
    assert "person@example.com" not in summary
    assert "[redacted]" in summary


def test_claro_request_filter_matches_claro_domains_only():
    orchestrator = _orchestrator()

    assert orchestrator._is_claro_request("https://ingreso.claro.com.ar/login")
    assert orchestrator._is_claro_request("https://api.claro.com.br/login")
    assert not orchestrator._is_claro_request("https://claro.com.ar.example.net/login")


def test_claro_login_skips_email_step_when_existing_session_redirects_to_accounts():
    class _Page:
        url = ""

        async def goto(self, _url, timeout):
            assert timeout == 1000
            self.url = "https://m-miclaro.claro.com.ar/elegirservicio"

    page = _Page()
    orchestrator = LoginOrchestrator(
        page,
        SimpleNamespace(
            email="person@example.com",
            password="secret",
            portal_url="https://m-miclaro.claro.com.ar",
            elegir_url="https://m-miclaro.claro.com.ar/elegirservicio",
            timeout_ms=1000,
        ),
    )

    already_authenticated = asyncio.run(orchestrator._step1_email())

    assert already_authenticated is True
    assert page.url.endswith("/elegirservicio")


def test_claro_login_waits_through_home_redirect_before_detecting_existing_session():
    class _EmailInput:
        def __init__(self, page):
            self.page = page
            self.checked = False

        async def is_visible(self):
            if not self.checked:
                self.checked = True
                self.page.url = "https://m-miclaro.claro.com.ar/elegirservicio"
            return False

    class _Page:
        url = ""

        async def goto(self, _url, timeout):
            assert timeout == 1000
            self.url = "https://m-miclaro.claro.com.ar/home"

        def locator(self, _selector):
            return _EmailInput(self)

    page = _Page()
    orchestrator = LoginOrchestrator(
        page,
        SimpleNamespace(
            email="person@example.com",
            password="secret",
            portal_url="https://m-miclaro.claro.com.ar",
            elegir_url="https://m-miclaro.claro.com.ar/elegirservicio",
            timeout_ms=1000,
        ),
    )

    already_authenticated = asyncio.run(orchestrator._step1_email())

    assert already_authenticated is True
    assert page.url.endswith("/elegirservicio")
