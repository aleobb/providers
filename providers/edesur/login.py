from __future__ import annotations

import asyncio

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from core.exceptions import LoginError, NavigationError
from .config import EdesurConfig


class LoginOrchestrator:
    def __init__(self, page: Page, config: EdesurConfig):
        self.page = page
        self.config = config

    async def execute(self) -> None:
        await self._navigate_to_login()
        await self._fill_credentials()
        await self._wait_for_portal()

    async def _navigate_to_login(self) -> None:
        try:
            await self.page.goto(self.config.login_url, timeout=self.config.timeout_ms)
            await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
            await asyncio.sleep(2)
        except PlaywrightTimeout as e:
            raise NavigationError(f"Timeout cargando login: {e}") from e

    async def _fill_credentials(self) -> None:
        try:
            email_input = self.page.locator('input[type="email"]').first
            await email_input.wait_for(state="visible", timeout=self.config.timeout_ms)
            await email_input.click()
            await self.page.keyboard.type(self.config.email, delay=50)
        except PlaywrightTimeout as e:
            raise LoginError("No se encontró el campo de email") from e

        try:
            pass_input = self.page.locator('input[type="password"]').first
            await pass_input.wait_for(state="visible", timeout=self.config.timeout_ms)
            await pass_input.click()
            await self.page.keyboard.type(self.config.password, delay=60)
        except PlaywrightTimeout as e:
            raise LoginError("No se encontró el campo de contraseña") from e

        ingresar = self.page.get_by_role("button", name="Ingresar")
        await ingresar.click()
        await asyncio.sleep(3)

    async def _wait_for_portal(self) -> None:
        try:
            await self.page.wait_for_url(
                "**/mi-cuenta**", timeout=self.config.timeout_ms
            )
            await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
            await asyncio.sleep(3)
        except PlaywrightTimeout:
            raise LoginError(
                f"El login no redirigió al portal. URL actual: {self.page.url}"
            )
