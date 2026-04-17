from __future__ import annotations

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .config import Config


class BrowserSession:
    def __init__(self, config: Config):
        self.config = config
        self._playwright = None
        self._browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def __aenter__(self) -> BrowserSession:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            channel="chrome",  # Use system Google Chrome to avoid VC++ dependency issues
        )
        self.context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="es-AR",
            timezone_id="America/Argentina/Buenos_Aires",
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
