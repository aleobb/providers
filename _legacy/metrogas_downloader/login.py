from __future__ import annotations

import asyncio

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from .config import Config
from .exceptions import LoginError, NavigationError


class LoginOrchestrator:
    def __init__(self, page: Page, config: Config):
        self.page = page
        self.config = config

    async def execute(self) -> None:
        await self._navigate_to_portal()
        await self._fill_email()
        await self._fill_password()
        await self._wait_for_portal()

    async def _navigate_to_portal(self) -> None:
        """Navigate to the entry page and follow to the SAML login form."""
        try:
            await self.page.goto(self.config.entry_url, timeout=self.config.timeout_ms)
            await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
            await asyncio.sleep(2)

            # Click "Iniciar Sesión" or similar to go to SAML login
            for label in ("Iniciar Sesión", "Iniciar sesión", "Ingresar", "Mi cuenta"):
                btn = self.page.get_by_text(label, exact=False)
                if await btn.count() > 0:
                    await btn.first.click()
                    break
            else:
                # Try navigating directly to the portal URL (triggers SAML redirect)
                await self.page.goto(self.config.portal_url, timeout=self.config.timeout_ms)

            # Wait for the SAML login form to appear
            await self.page.wait_for_selector(
                "#logOnForm, #j_username, input[name='j_username']",
                timeout=self.config.timeout_ms,
            )
            await asyncio.sleep(1)
        except PlaywrightTimeout as e:
            raise NavigationError(f"Timeout cargando la página de login: {e}") from e

    async def _fill_email(self) -> None:
        """Fill email (Step 1 of SAML login) and submit."""
        try:
            email_input = self.page.locator("#j_username, input[name='j_username']").first
            await email_input.wait_for(state="visible", timeout=self.config.timeout_ms)
            await email_input.click()
            await self.page.keyboard.type(self.config.email, delay=50)
        except PlaywrightTimeout as e:
            raise LoginError("No se encontró el campo de email en el formulario SAML") from e

        # Submit Step 1
        submit_btn = self.page.locator("#logOnFormSubmit, button[type='submit']").first
        await submit_btn.click()

        await asyncio.sleep(2)
        await self._check_for_error("email")

    async def _fill_password(self) -> None:
        """Fill password (Step 2 of SAML login) and submit."""
        try:
            pass_input = self.page.locator("#j_password, input[name='j_password']").first
            await pass_input.wait_for(state="visible", timeout=self.config.timeout_ms)
            await pass_input.click()
            await self.page.keyboard.type(self.config.password, delay=60)
        except PlaywrightTimeout as e:
            raise LoginError(
                "No apareció el campo de contraseña tras ingresar el email"
            ) from e

        submit_btn = self.page.locator("#logOnFormSubmit, button[type='submit']").first
        await submit_btn.click()

        await asyncio.sleep(2)
        await self._check_for_error("contraseña")

    async def _wait_for_portal(self) -> None:
        """Wait for SAML response to redirect to the authenticated portal."""
        # The portal uses hash-based routing (#Home-show), so wait_for_url with
        # standard load events doesn't work reliably. Poll the URL instead.
        for _ in range(30):
            await asyncio.sleep(1)
            if "portal.micuenta.metrogas" in self.page.url:
                await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
                await asyncio.sleep(3)
                return

        raise LoginError(
            "El login no redirigió al portal. "
            f"URL actual: {self.page.url}. "
            "Verificar credenciales o usar METROGAS_HEADLESS=false para diagnóstico."
        )

    async def _check_for_error(self, step: str) -> None:
        for selector in (
            '[class*="error"]',
            '[class*="Error"]',
            '[role="alert"]',
            ".sapUiMsg",
            "#logOnFormErrorMessage",
        ):
            elements = self.page.locator(selector)
            if await elements.count() > 0:
                text = await elements.first.inner_text()
                if text.strip():
                    raise LoginError(f"Error en paso '{step}': {text.strip()}")
