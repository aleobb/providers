from __future__ import annotations

import asyncio

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from core.exceptions import LoginError, NavigationError
from .config import MetrogasConfig


class LoginOrchestrator:
    def __init__(self, page: Page, config: MetrogasConfig):
        self.page = page
        self.config = config

    async def execute(self) -> None:
        await self._navigate_to_portal()
        await self._fill_email()
        await self._fill_password()
        await self._wait_for_portal()

    async def _navigate_to_portal(self) -> None:
        try:
            await self.page.goto(self.config.entry_url, timeout=self.config.timeout_ms)
            await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
            await asyncio.sleep(2)

            for label in ("Iniciar Sesión", "Iniciar sesión", "Ingresar"):
                btn = self.page.get_by_text(label, exact=False)
                if await btn.count() > 0:
                    await btn.first.click()
                    break
            else:
                await self.page.goto(self.config.portal_url, timeout=self.config.timeout_ms)

            await self.page.wait_for_selector(
                "#logOnForm, #j_username, input[name='j_username']",
                timeout=self.config.timeout_ms,
            )
            await asyncio.sleep(1)
        except PlaywrightTimeout as e:
            raise NavigationError(f"Timeout cargando login: {e}") from e

    async def _fill_email(self) -> None:
        try:
            email_input = self.page.locator("#j_username, input[name='j_username']").first
            await email_input.wait_for(state="visible", timeout=self.config.timeout_ms)
            current_email = (await email_input.input_value()).strip()
            if current_email != self.config.email:
                await email_input.fill(self.config.email)
        except PlaywrightTimeout as e:
            raise LoginError("No se encontró el campo de email") from e

        submit_btn = self.page.locator("#logOnFormSubmit, button[type='submit']").first
        await submit_btn.click()
        await asyncio.sleep(2)
        await self._check_for_error("email")

    async def _fill_password(self) -> None:
        try:
            pass_input = self.page.locator("#j_password, input[name='j_password']").first
            await pass_input.wait_for(state="visible", timeout=self.config.timeout_ms)
            await pass_input.click()
            await self.page.keyboard.type(self.config.password, delay=60)
        except PlaywrightTimeout as e:
            raise LoginError("No apareció el campo de contraseña") from e

        submit_btn = self.page.locator("#logOnFormSubmit, button[type='submit']").first
        await submit_btn.click()
        await asyncio.sleep(2)
        await self._check_for_error("contraseña")

    async def _wait_for_portal(self) -> None:
        for _ in range(30):
            await asyncio.sleep(1)
            if "portal.micuenta.metrogas" in self.page.url:
                await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
                await asyncio.sleep(3)
                return
        raise LoginError(
            f"El login no redirigió al portal. URL actual: {self.page.url}"
        )

    async def _check_for_error(self, step: str) -> None:
        for selector in (
            '[class*="error"]', '[class*="Error"]', '[role="alert"]',
            ".sapUiMsg", "#logOnFormErrorMessage",
        ):
            elements = self.page.locator(selector)
            if await elements.count() > 0:
                text = await elements.first.inner_text()
                if text.strip():
                    raise LoginError(f"Error en paso '{step}': {text.strip()}")
