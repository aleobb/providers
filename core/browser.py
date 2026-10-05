from __future__ import annotations

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .config import BaseProviderConfig

_DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class BrowserSession:
    def __init__(self, config: BaseProviderConfig):
        self.config = config
        self._playwright = None
        self._browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def __aenter__(self) -> BrowserSession:
        self._playwright = await async_playwright().start()
        launch_options = {
            "headless": self.config.headless,
            "channel": "chrome",
        }
        browser_args = getattr(self.config, "browser_args", [])
        if browser_args:
            launch_options["args"] = browser_args
        self._browser = await self._playwright.chromium.launch(
            **launch_options,
        )
        context_options = {
            "viewport": {"width": 1280, "height": 800},
            "locale": "es-AR",
            "timezone_id": "America/Argentina/Buenos_Aires",
        }
        user_agent = getattr(
            self.config, "browser_user_agent", _DEFAULT_BROWSER_USER_AGENT
        )
        if user_agent is not None:
            context_options["user_agent"] = user_agent
        self.context = await self._browser.new_context(
            **context_options,
        )
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, *args) -> None:
        if self.context:
            await self.context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
