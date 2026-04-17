from __future__ import annotations

import asyncio

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from core.exceptions import LoginError, NavigationError
from .config import ClaroConfig


class LoginOrchestrator:
    """
    Login de 2 pasos via Keycloak (ingreso.claro.com.ar):
      Paso 1: email  → botón "Continuar"
      Paso 2: password → botón "Ingresar"
    """

    def __init__(self, page: Page, config: ClaroConfig):
        self.page = page
        self.config = config

    async def execute(self) -> None:
        await self._step1_email()
        await self._step2_password()
        await self._wait_for_portal()

    async def _step1_email(self) -> None:
        try:
            await self.page.goto(self.config.portal_url, timeout=self.config.timeout_ms)
            # El portal redirige a ingreso.claro.com.ar (Keycloak)
            await self.page.wait_for_selector('input[type="email"]', timeout=self.config.timeout_ms)
            await asyncio.sleep(0.5)

            await self.page.click('input[type="email"]')
            await self.page.keyboard.type(self.config.email, delay=50)
            await self.page.click('button:has-text("Continuar")')
        except PlaywrightTimeout as e:
            raise NavigationError(f"Timeout en step 1 (email) de Claro: {e}") from e

    async def _step2_password(self) -> None:
        try:
            await self.page.wait_for_selector('input[type="password"]', timeout=self.config.timeout_ms)
            await asyncio.sleep(0.5)

            await self.page.click('input[type="password"]')
            await self.page.keyboard.type(self.config.password, delay=50)
            # Intentar botón submit por varias estrategias
            for sel in [
                'button:has-text("Ingresar")',
                'input[type="submit"]',
                'button[type="submit"]',
                'button[class*="submit"]',
            ]:
                try:
                    elem = self.page.locator(sel).first
                    if await elem.count() > 0 and await elem.is_visible(timeout=2000):
                        await elem.click()
                        return
                except Exception:
                    pass
            # Fallback: Enter
            await self.page.keyboard.press("Return")
        except PlaywrightTimeout as e:
            raise LoginError(f"Timeout en step 2 (password) de Claro: {e}") from e

    async def _wait_for_portal(self) -> None:
        """Espera hasta que la URL sea /elegirservicio."""
        for _ in range(60):
            await asyncio.sleep(1)
            if "elegirservicio" in self.page.url:
                await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
                return
        raise LoginError(
            f"Claro no redirigió a /elegirservicio después del login. URL: {self.page.url}"
        )
