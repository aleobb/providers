from __future__ import annotations

import asyncio

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from core.exceptions import AccountLockedError, CaptchaError, LoginError, NavigationError
from .config import EdenorConfig

_WELCOME_URL = "/ingreso/bienvenida"
_LOGIN_URL = "/ingreso/ingresar"


class LoginOrchestrator:
    def __init__(self, page: Page, config: EdenorConfig):
        self.page = page
        self.config = config

    async def execute(self) -> None:
        await self._navigate_to_welcome()
        await self._click_email_login()
        await self._fill_credentials()
        await self._wait_for_dashboard()

    async def _navigate_to_welcome(self) -> None:
        try:
            url = self.config.base_url.rstrip("/") + _WELCOME_URL
            await self.page.goto(url, timeout=self.config.timeout_ms)
            await asyncio.sleep(2)
        except PlaywrightTimeout as e:
            raise NavigationError(f"Timeout cargando la página de bienvenida: {e}") from e

    async def _click_email_login(self) -> None:
        try:
            email_btn = self.page.locator('[data-testid="unifiedAuth.email"]')
            await email_btn.wait_for(state="visible", timeout=self.config.timeout_ms)
            await email_btn.click()
            await self.page.wait_for_url(f"**{_LOGIN_URL}", timeout=self.config.timeout_ms)
            await asyncio.sleep(1)
        except PlaywrightTimeout as e:
            raise LoginError("No se encontró el botón de login con email") from e

    async def _fill_credentials(self) -> None:
        try:
            email_input = self.page.locator('[data-testid="unifiedAuth.form.email"]')
            await email_input.wait_for(state="visible", timeout=self.config.timeout_ms)
            await email_input.click()
            await self.page.keyboard.type(self.config.email, delay=60)
        except PlaywrightTimeout as e:
            raise LoginError("No se encontró el campo de email") from e

        try:
            pass_input = self.page.locator('[data-testid="unifiedAuth.form.password"]')
            await pass_input.click()
            await self.page.keyboard.type(self.config.password, delay=70)
        except PlaywrightTimeout as e:
            raise LoginError("No se encontró el campo de contraseña") from e

        ingresar_btn = self.page.get_by_role("button", name="Ingresar", exact=True)
        if await ingresar_btn.count() == 0:
            ingresar_btn = self.page.locator("button").last
        await ingresar_btn.click()

        await self._check_for_captcha()
        await self._check_for_error("credenciales")

    async def _wait_for_dashboard(self) -> None:
        try:
            await self.page.wait_for_url("**/cuentas/**", timeout=self.config.timeout_ms)
        except PlaywrightTimeout as e:
            content = await self.page.content()
            if any(w in content.lower() for w in ("bloqueada", "bloqueado", "locked")):
                raise AccountLockedError("La cuenta está bloqueada") from e
            raise LoginError("El login no redirigió al área de cuentas.") from e

    async def _check_for_captcha(self) -> None:
        if await self.page.locator('iframe[src*="recaptcha"]').count() > 0:
            raise CaptchaError("reCAPTCHA activado. Ejecutar con --debug.")

    async def _check_for_error(self, step: str) -> None:
        await asyncio.sleep(1)
        for selector in ('[class*="error"]', '[class*="Error"]', '[role="alert"]'):
            elements = self.page.locator(selector)
            if await elements.count() > 0:
                text = await elements.first.inner_text()
                if text.strip():
                    raise LoginError(f"Error en paso '{step}': {text.strip()}")
