import asyncio
from types import SimpleNamespace

from providers.edenor.login import LoginOrchestrator


class _Page:
    def __init__(self):
        self.goto_args = None

    async def goto(self, url, *, timeout):
        self.goto_args = (url, timeout)

    async def wait_for_load_state(self, state, *, timeout):
        raise AssertionError(f"Unexpected wait for {state}")


class _EmailButton:
    async def wait_for(self, *, state, timeout):
        assert state == "visible"

    async def click(self):
        pass


class _EmailLoginPage:
    def __init__(self):
        self.selector = None

    def locator(self, selector):
        self.selector = selector
        return _EmailButton()

    async def wait_for_url(self, url, *, timeout):
        assert url == "**/ingreso/ingresar"


def test_welcome_navigation_does_not_wait_for_network_idle(monkeypatch):
    page = _Page()
    config = SimpleNamespace(
        base_url="https://edenordigital.com/",
        timeout_ms=1000,
    )

    async def skip_sleep(_seconds):
        pass

    monkeypatch.setattr("providers.edenor.login.asyncio.sleep", skip_sleep)

    asyncio.run(LoginOrchestrator(page, config)._navigate_to_welcome())

    assert page.goto_args == (
        "https://edenordigital.com/ingreso/bienvenida",
        1000,
    )


def test_email_login_uses_current_portal_test_id(monkeypatch):
    page = _EmailLoginPage()
    config = SimpleNamespace(timeout_ms=1000)

    async def skip_sleep(_seconds):
        pass

    monkeypatch.setattr("providers.edenor.login.asyncio.sleep", skip_sleep)

    asyncio.run(LoginOrchestrator(page, config)._click_email_login())

    assert page.selector == '[data-testid="unifiedAuth.email"]'
