from __future__ import annotations

import asyncio

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from core.exceptions import LoginError, NavigationError
from .config import AysaConfig


class LoginOrchestrator:
    def __init__(self, page: Page, config: AysaConfig):
        self.page = page
        self.config = config

    async def execute(self) -> None:
        await self._navigate_to_login()
        await self._fill_credentials()
        await self._wait_for_portal()

    async def _navigate_to_login(self) -> None:
        try:
            await self.page.goto(self.config.entry_url, timeout=self.config.timeout_ms)
            await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
            await asyncio.sleep(2)

            # Click "INICIÁ SESIÓN" — abre un modal
            iniciar = self.page.get_by_text("INICIÁ SESIÓN", exact=False).first
            await iniciar.wait_for(state="visible", timeout=self.config.timeout_ms)
            await iniciar.click()
            await asyncio.sleep(1)

            # En el modal elegir "Ya estoy registrado" (botón naranja)
            ya_reg = self.page.get_by_text("Ya estoy registr", exact=False).first
            await ya_reg.wait_for(state="visible", timeout=10_000)
            await ya_reg.click()
            await asyncio.sleep(2)

            # Esperar la página de login SSO en acceso.web.aysa.com.ar
            await self.page.wait_for_selector(
                'input[placeholder="Correo electrónico"], input[type="text"]',
                timeout=self.config.timeout_ms,
            )
            await asyncio.sleep(1)
        except PlaywrightTimeout as e:
            raise NavigationError(f"Timeout navegando al login AYSA: {e}") from e

    async def _fill_credentials(self) -> None:
        try:
            email_input = self.page.locator(
                'input[placeholder="Correo electrónico"], input[type="text"]'
            ).first
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

        submit_btn = self.page.locator('button[type="submit"]').first
        await submit_btn.click()
        await asyncio.sleep(3)

    async def _wait_for_portal(self) -> None:
        # La cadena SAML pasa por authn.br1.hana.ondemand.com que auto-submitea un form.
        # En algunos entornos el form no se auto-submite; en ese caso lo hacemos manualmente.
        for _ in range(60):
            await asyncio.sleep(1)
            url = self.page.url

            if "portal.web.aysa.com.ar" in url:
                await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
                await asyncio.sleep(3)
                return

            # Si el navegador queda trabado en la página de relay SAML de SAP, submitear el form
            if "authn.br1.hana.ondemand.com" in url or "hana.ondemand.com" in url:
                try:
                    await self.page.evaluate("document.forms[0] && document.forms[0].submit()")
                    await asyncio.sleep(2)
                except Exception:
                    pass

        raise LoginError(
            f"El login no redirigió al portal AYSA. URL actual: {self.page.url}"
        )
