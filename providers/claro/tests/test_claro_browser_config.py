import asyncio

from core.browser import BrowserSession
from providers.claro.config import ClaroConfig


def test_claro_uses_chromes_real_user_agent_without_stealth():
    config = ClaroConfig(email="user@example.com", password="secret")

    assert config.browser_user_agent is None
    assert config.browser_stealth is False
    assert "--disable-blink-features=AutomationControlled" in config.browser_args


def test_browser_session_applies_claro_args_and_native_user_agent(monkeypatch, tmp_path):
    browser_options = {}
    context_options = {}

    class FakeContext:
        async def new_page(self):
            return object()

        async def close(self):
            pass

    class FakeBrowser:
        async def new_context(self, **options):
            context_options.update(options)
            return FakeContext()

        async def close(self):
            pass

    class FakeChromium:
        async def launch(self, **options):
            browser_options.update(options)
            return FakeBrowser()

        async def launch_persistent_context(self, **options):
            browser_options.update(options)
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

        async def stop(self):
            pass

    class FakePlaywrightContext:
        async def start(self):
            return FakePlaywright()

        async def __aenter__(self):
            return FakePlaywright()

        async def __aexit__(self, *_args):
            pass

    monkeypatch.setattr("core.browser.async_playwright", FakePlaywrightContext)
    monkeypatch.setattr("core.browser._PROFILES_BASE", tmp_path / "profiles", raising=False)
    config = ClaroConfig(
        email="user@example.com",
        password="secret",
        headless=True,
    )

    async def exercise():
        async with BrowserSession(config):
            pass

    asyncio.run(exercise())

    assert "--disable-blink-features=AutomationControlled" in browser_options["args"]
    assert "user_agent" not in browser_options
    assert "user_agent" not in context_options
