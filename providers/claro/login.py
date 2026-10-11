from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from playwright.async_api import (
    Error as PlaywrightError,
    Page,
    Request,
    Response,
    TimeoutError as PlaywrightTimeout,
)

from core.exceptions import LoginError, NavigationError
from core.network_diagnostics import NetworkDiagnostics
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
        self._network_diagnostics = NetworkDiagnostics(
            ("claro.com.ar", "claro.com", "claro.com.br"),
            include_subdomains=True,
            redact_long_path_segments=True,
            redact_emails=True,
        )
        self._email_submitted = False
        self._requests: list[str] = []
        self._responses: list[str] = []
        self._failures: list[str] = []
        self._console_errors: list[str] = []
        self._page_errors: list[str] = []
        self._cdp_request_urls: dict[str, str] = {}
        self._cdp_request_methods: dict[str, str] = {}
        self._cdp_diagnostics: list[str] = []
        self._cdp = None

    async def execute(self) -> None:
        self._setup_interceptors()
        await self._setup_cdp_diagnostics()
        if await self._step1_email():
            return
        await self._step2_password()
        await self._wait_for_portal()

    def _setup_interceptors(self) -> None:
        self.page.on("request", self._on_request)
        self.page.on("requestfailed", self._on_request_failed)
        self.page.on("response", self._schedule_response_diagnostics)
        self.page.on("console", self._on_console)
        self.page.on("pageerror", self._on_page_error)

    async def _setup_cdp_diagnostics(self) -> None:
        self._cdp = await self.page.context.new_cdp_session(self.page)
        await self._cdp.send("Network.enable")
        self._cdp.on("Network.requestWillBeSent", self._on_cdp_request)
        self._cdp.on("Network.responseReceived", self._on_cdp_response)
        self._cdp.on("Network.loadingFailed", self._on_cdp_loading_failed)

    def _on_cdp_request(self, event: dict) -> None:
        request = event.get("request", {})
        url = request.get("url", "")
        request_id = event.get("requestId", "")
        if self._is_claro_request(url):
            self._cdp_request_urls[request_id] = url
            self._cdp_request_methods[request_id] = request.get("method", "unknown")

    def _on_cdp_response(self, event: dict) -> None:
        request_id = event.get("requestId", "")
        url = self._cdp_request_urls.get(request_id, "")
        status = event.get("response", {}).get("status", "unknown")
        if not url or len(self._cdp_diagnostics) >= 30:
            return
        if not isinstance(status, (int, float)) or status < 400:
            return

        details = [
            f"{self._cdp_request_methods.get(request_id, 'unknown')} "
            f"response HTTP {status} {self._safe_url(url)}"
        ]
        headers = {
            str(key).lower(): str(value)
            for key, value in event.get("response", {}).get("headers", {}).items()
        }
        for name in (
            "content-type",
            "access-control-allow-origin",
            "access-control-allow-methods",
            "access-control-allow-headers",
            "access-control-allow-credentials",
            "server",
        ):
            if headers.get(name):
                details.append(f"{name}={self._redact(headers[name][:160])}")
        self._cdp_diagnostics.append("; ".join(details))

    def _on_cdp_loading_failed(self, event: dict) -> None:
        request_id = event.get("requestId", "")
        url = self._cdp_request_urls.get(request_id, "")
        if not url or len(self._cdp_diagnostics) >= 30:
            return

        details = [
            f"{self._cdp_request_methods.get(request_id, 'unknown')} "
            f"loadingFailed {self._safe_url(url)}: "
            f"{event.get('errorText', 'unknown')}"
        ]
        blocked_reason = event.get("blockedReason")
        if blocked_reason:
            details.append(f"blockedReason={blocked_reason}")
        cors_error = event.get("corsErrorStatus")
        if isinstance(cors_error, dict):
            details.append(
                f"cors={cors_error.get('corsError', 'unknown')}; "
                f"parameter={cors_error.get('failedParameter', '(none)')}"
            )
        self._cdp_diagnostics.append("; ".join(details))

    async def _on_request(self, request: Request) -> None:
        if (
            self._email_submitted
            and self._is_claro_request(request.url)
            and len(self._requests) < 30
        ):
            self._requests.append(
                f"{request.method} {self._safe_url(request.url)} "
                f"resource={request.resource_type}"
            )

    def _on_request_failed(self, request: Request) -> None:
        if not self._is_claro_request(request.url) or len(self._failures) >= 30:
            return
        self._failures.append(
            f"{request.method} {self._safe_url(request.url)} "
            f"failed: {request.failure or 'unknown'}"
        )

    def _on_console(self, message) -> None:
        if message.type != "error" or len(self._console_errors) >= 8:
            return
        text = message.text
        if not any(
            marker in text.lower()
            for marker in ("claro", "error", "request", "cors", "net::err")
        ):
            return
        self._console_errors.append(self._redact(text[:500]))

    def _on_page_error(self, error: Exception) -> None:
        if len(self._page_errors) < 8:
            self._page_errors.append(self._redact(str(error)[:500]))

    def _schedule_response_diagnostics(self, response: Response) -> None:
        request = response.request
        if (
            self._email_submitted
            and self._is_claro_request(response.url)
            and (request.method.upper() == "POST" or response.status >= 400)
        ):
            asyncio.create_task(self._record_response(response))

    async def _record_response(self, response: Response) -> None:
        if len(self._responses) >= 30:
            return
        request = response.request
        headers = response.headers
        parts = [
            f"{request.method} {self._safe_url(response.url)} "
            f"-> HTTP {response.status}",
            f"resource={request.resource_type}",
        ]
        for name in (
            "content-type",
            "access-control-allow-origin",
            "access-control-allow-methods",
            "access-control-allow-headers",
            "access-control-allow-credentials",
            "server",
        ):
            value = headers.get(name)
            if value:
                parts.append(f"{name}={self._redact(value[:160])}")

        content_type = headers.get("content-type", "")
        if "json" in content_type.lower() or "text/plain" in content_type.lower():
            try:
                body = await response.text()
            except PlaywrightError as error:
                parts.append(f"body-unavailable={type(error).__name__}")
            else:
                parts.append(self._summarize_body(body, content_type))
        else:
            parts.append("body=omitted")
        self._responses.append("; ".join(parts))

    async def _step1_email(self) -> bool:
        try:
            await self.page.goto(self.config.portal_url, timeout=self.config.timeout_ms)
            if await self._wait_for_email_or_active_session():
                return True

            # El portal redirige a ingreso.claro.com.ar (Keycloak)
            await asyncio.sleep(0.5)

            await self.page.click('input[type="email"]')
            await self.page.keyboard.type(self.config.email, delay=50)
            self._email_submitted = True
            await self.page.click('button:has-text("Continuar")')
            return False
        except PlaywrightTimeout as error:
            raise NavigationError(
                f"Timeout en step 1 (email) de Claro: {error} | "
                f"Diagnóstico: {await self._diagnostics()}"
            ) from error

    async def _wait_for_email_or_active_session(self) -> bool:
        """Espera el formulario de login o la redirección de una sesión activa."""
        email_input = None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.timeout_ms / 1000

        while loop.time() < deadline:
            if self._is_authenticated_portal_url(self.page.url):
                return True
            if email_input is None:
                email_input = self.page.locator('input[type="email"]')
            if await email_input.is_visible():
                return False
            await asyncio.sleep(min(0.1, max(0, deadline - loop.time())))

        raise PlaywrightTimeout(
            "No apareció el formulario de email ni se detectó una sesión activa "
            "en /elegirservicio"
        )

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
        except PlaywrightTimeout as error:
            raise LoginError(
                f"Timeout en step 2 (password) de Claro: {error} | "
                f"Diagnóstico: {await self._diagnostics()}"
            ) from error

    async def _wait_for_portal(self) -> None:
        """Espera hasta que la URL sea /elegirservicio."""
        for _ in range(60):
            await asyncio.sleep(1)
            if "elegirservicio" in self.page.url:
                await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
                return
        raise LoginError(
            f"Claro no redirigió a /elegirservicio después del login. "
            f"URL: {self._safe_url(self.page.url)} | "
            f"Diagnóstico: {await self._diagnostics()}"
        )

    async def _diagnostics(self) -> str:
        try:
            visible_text = await self.page.locator("body").inner_text(timeout=1500)
        except PlaywrightError as error:
            visible_error = f"(unavailable: {type(error).__name__})"
        else:
            error_lines = [
                self._redact(" ".join(line.split())[:180])
                for line in visible_text.splitlines()
                if any(
                    marker in line.lower()
                    for marker in ("error", "request", "solicitud", "fall", "intenta")
                )
            ][:8]
            visible_error = " | ".join(error_lines) or "(no visible error text)"

        return (
            f"url={self._safe_url(self.page.url)}; "
            f"visible-error=[{visible_error}]; "
            f"requests=[{' | '.join(self._requests) or '(none)'}]; "
            f"responses=[{' | '.join(self._responses) or '(none)'}]; "
            f"failed=[{' | '.join(self._failures) or '(none)'}]; "
            f"console=[{' | '.join(self._console_errors) or '(none)'}]; "
            f"page-errors=[{' | '.join(self._page_errors) or '(none)'}]; "
            f"chromium=[{' | '.join(self._cdp_diagnostics) or '(none)'}]"
        )

    def _is_claro_request(self, url: str) -> bool:
        return self._network_diagnostics.matches_domain(url)

    def _is_authenticated_portal_url(self, url: str) -> bool:
        current_url = urlsplit(url)
        portal_url = urlsplit(self.config.elegir_url)
        return (
            current_url.hostname == portal_url.hostname
            and current_url.path.rstrip("/") == portal_url.path.rstrip("/")
        )

    def _safe_url(self, url: str) -> str:
        return self._network_diagnostics.safe_url(url)

    def _summarize_body(self, body: str, content_type: str) -> str:
        return self._network_diagnostics.summarize_body(
            body,
            content_type,
            (
                "error",
                "message",
                "error_description",
                "code",
                "requestId",
                "correlationId",
                "traceId",
                "title",
                "status",
            ),
            (self.config.email, self.config.password),
        )

    def _redact(self, value: str) -> str:
        return self._network_diagnostics.redact(
            value, (self.config.email, self.config.password)
        )
