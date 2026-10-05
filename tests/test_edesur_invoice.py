import asyncio
from types import SimpleNamespace

from core.config import BaseProviderConfig
from providers.edesur.config import EdesurConfig
from providers.edesur.invoice import InvoiceService


def test_edesur_uses_unmodified_chrome_for_manual_verification():
    config = EdesurConfig(email="user@example.com", password="password")
    other_provider_config = BaseProviderConfig(
        email="user@example.com", password="password"
    )

    assert config.browser_stealth is False
    assert config.browser_user_agent is None
    assert other_provider_config.browser_stealth is True
    assert other_provider_config.browser_user_agent is not None


class _DownloadButton:
    def __init__(self, disabled_states):
        self.disabled_states = iter(disabled_states)
        self.clicked = False

    async def count(self):
        return 1

    async def is_visible(self):
        return True

    async def is_disabled(self):
        return next(self.disabled_states)

    async def click(self):
        self.clicked = True


class _Page:
    def __init__(self, button):
        self.button = button

    def locator(self, selector):
        assert selector == "#downloadBtn"
        return self.button


def test_waits_for_human_verification_without_attempting_to_click_it(monkeypatch):
    button = _DownloadButton([True, False])
    service = InvoiceService(
        page=None,
        context=None,
        config=SimpleNamespace(headless=False),
    )

    async def skip_sleep(_seconds):
        pass

    monkeypatch.setattr("providers.edesur.invoice.asyncio.sleep", skip_sleep)

    result = asyncio.run(service._wait_for_download_button(_Page(button)))

    assert result is button
    assert button.clicked is False


def test_headless_download_proceeds_when_no_human_verification_is_needed():
    button = _DownloadButton([False])
    service = InvoiceService(
        page=None,
        context=None,
        config=SimpleNamespace(headless=True),
    )

    result = asyncio.run(service._wait_for_download_button(_Page(button)))

    assert result is button
