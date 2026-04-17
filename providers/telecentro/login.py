from __future__ import annotations

import asyncio
import json

from playwright.async_api import Page, Request, Response, TimeoutError as PlaywrightTimeout

from core.exceptions import LoginError, NavigationError
from .config import TelecentroConfig


class LoginOrchestrator:
    def __init__(self, page: Page, config: TelecentroConfig):
        self.page = page
        self.config = config
        self._jwt: str = ""

    async def execute(self) -> str:
        """Realiza el login y devuelve el JWT capturado."""
        self._setup_interceptors()
        await self._navigate_and_login()
        await self._wait_for_home()
        if not self._jwt:
            raise LoginError("No se capturó el token JWT de Telecentro tras el login")
        return self._jwt

    def _setup_interceptors(self) -> None:
        """Captura el JWT tanto de request headers (XHR override) como del response de autenticar."""

        def on_request(request: Request) -> None:
            if self._jwt:
                return
            if "apiext.telecentro.net.ar" in request.url:
                auth = request.headers.get("authorization", "")
                if auth.lower().startswith("bearer ") and len(auth) > 15:
                    self._jwt = auth[7:]

        async def on_response(response: Response) -> None:
            if self._jwt:
                return
            if "autenticar" in response.url and response.status == 200:
                try:
                    body = await response.text()
                    data = json.loads(body)
                    token = _find_jwt(data)
                    if token:
                        self._jwt = token
                except Exception:
                    pass

        self.page.on("request", on_request)
        self.page.on("response", on_response)

    async def _navigate_and_login(self) -> None:
        try:
            await self.page.goto(self.config.login_url, timeout=self.config.timeout_ms)
            await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
            await asyncio.sleep(1)

            email_input = self.page.locator('input[type="email"]').first
            await email_input.wait_for(state="visible", timeout=self.config.timeout_ms)
            await email_input.click()
            await self.page.keyboard.type(self.config.email, delay=50)

            pass_input = self.page.locator('input[type="password"]').first
            await pass_input.wait_for(state="visible", timeout=self.config.timeout_ms)
            await pass_input.click()
            await self.page.keyboard.type(self.config.password, delay=60)

            submit_btn = self.page.locator('button:has-text("Ingresar"), button[type="submit"]').first
            await submit_btn.click()
        except PlaywrightTimeout as e:
            raise NavigationError(f"Timeout navegando al login de Telecentro: {e}") from e

    async def _wait_for_home(self) -> None:
        """Espera hasta que la URL contenga /home y el JWT haya sido capturado."""
        for _ in range(60):
            await asyncio.sleep(1)
            url = self.page.url
            if "/home" in url and self._jwt:
                await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
                await asyncio.sleep(2)
                return
            # Llegamos a home pero el JWT todavía no se capturó: dar más tiempo a las APIs
            if "/home" in url and not self._jwt:
                for _ in range(10):
                    await asyncio.sleep(1)
                    if self._jwt:
                        return

        raise LoginError(
            f"El login de Telecentro no completó. URL actual: {self.page.url} | "
            f"JWT: {'sí' if self._jwt else 'no'}"
        )


def _find_jwt(obj, depth: int = 0) -> str:
    """Busca recursivamente un token JWT (empieza con 'eyJ') en un objeto JSON."""
    if depth > 5:
        return ""
    if isinstance(obj, str) and obj.startswith("eyJ") and len(obj) > 50:
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            t = _find_jwt(v, depth + 1)
            if t:
                return t
    if isinstance(obj, list):
        for v in obj:
            t = _find_jwt(v, depth + 1)
            if t:
                return t
    return ""
