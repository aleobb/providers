from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qsl

from playwright.async_api import (
    Error as PlaywrightError,
    Page,
    Request,
    Response,
    TimeoutError as PlaywrightTimeout,
)

from core.exceptions import LoginError, NavigationError
from core.network_diagnostics import NetworkDiagnostics
from .config import TelecentroConfig


class LoginOrchestrator:
    """Realiza el login de Telecentro y captura el JWT."""

    def __init__(self, page: Page, config: TelecentroConfig):
        self.page = page
        self.config = config
        self._network_diagnostics = NetworkDiagnostics(
            ("apiext.telecentro.net.ar",),
            preserve_netloc=True,
        )
        self._jwt = ""
        self._login_submitted = False
        self._requests: list[str] = []
        self._responses: list[str] = []
        self._failures: list[str] = []
        self._console_errors: list[str] = []
        self._cdp_request_urls: dict[str, str] = {}
        self._cdp_request_methods: dict[str, str] = {}
        self._cdp_pending_request_headers: dict[str, dict] = {}
        self._cdp_diagnostics: list[str] = []
        self._cdp = None

    async def execute(self) -> str:
        self._setup_interceptors()
        await self._setup_cdp_diagnostics()

        try:
            await self.page.goto(self.config.login_url, timeout=self.config.timeout_ms)
        except PlaywrightTimeout as e:
            raise NavigationError(
                f"Timeout navegando al login de Telecentro: {e}"
            ) from e

        await asyncio.sleep(2)
        if "/home" in self.page.url:
            await self._wait_for_jwt_from_active_session()
        else:
            await self._fill_login_form()
            await self._wait_for_jwt_after_login()

        if not self._jwt:
            raise LoginError(
                f"No se capturó JWT de Telecentro. URL: {self.page.url} | "
                f"Diagnóstico: {self._diagnostics()}"
            )
        return self._jwt

    def _setup_interceptors(self) -> None:
        self.page.on("request", self._on_request)
        self.page.on("requestfailed", self._on_request_failed)
        self.page.on("response", self._schedule_response_diagnostics)
        self.page.on("console", self._on_console)

    async def _setup_cdp_diagnostics(self) -> None:
        self._cdp = await self.page.context.new_cdp_session(self.page)
        await self._cdp.send("Network.enable")
        self._cdp.on("Network.requestWillBeSent", self._on_cdp_request)
        self._cdp.on(
            "Network.requestWillBeSentExtraInfo", self._on_cdp_request_extra_info
        )
        self._cdp.on("Network.responseReceivedExtraInfo", self._on_cdp_response)
        self._cdp.on("Network.loadingFailed", self._on_cdp_loading_failed)

    def _on_cdp_request(self, event: dict) -> None:
        request = event.get("request", {})
        url = request.get("url", "")
        request_id = event.get("requestId", "")
        if self._is_auth_request(url):
            self._cdp_request_urls[request_id] = url
            self._cdp_request_methods[request_id] = request.get("method", "unknown")
            pending_headers = self._cdp_pending_request_headers.pop(
                request_id, None
            )
            if pending_headers:
                self._record_cdp_request_headers(request_id, url, pending_headers)
        else:
            self._cdp_pending_request_headers.pop(request_id, None)

    def _on_cdp_request_extra_info(self, event: dict) -> None:
        request_id = event.get("requestId", "")
        url = self._cdp_request_urls.get(request_id, "")
        headers = event.get("headers", {})
        if not url:
            if len(self._cdp_pending_request_headers) < 30:
                self._cdp_pending_request_headers[request_id] = (
                    self._safe_cdp_request_headers(headers)
                )
            return

        self._record_cdp_request_headers(
            request_id, url, self._safe_cdp_request_headers(headers)
        )

    def _safe_cdp_request_headers(self, raw_headers: dict) -> dict[str, str]:
        allowed = {
            "origin",
            "content-type",
            "access-control-request-method",
            "access-control-request-headers",
            "sec-fetch-site",
            "sec-fetch-mode",
            "user-agent",
        }
        safe_headers = {}
        for key, value in raw_headers.items():
            name = str(key).lower()
            if name in allowed:
                safe_headers[name] = str(value)
            elif name.startswith("xa4vrhyp3q-"):
                safe_headers[name] = ""
        return safe_headers

    def _record_cdp_request_headers(self, request_id: str, url: str, raw_headers: dict) -> None:
        if len(self._cdp_diagnostics) >= 30:
            return
        headers = raw_headers
        details = [
            f"{self._cdp_request_methods.get(request_id, 'unknown')} "
            f"request-headers {self._safe_url(url)}"
        ]
        for name in (
            "origin",
            "content-type",
            "access-control-request-method",
            "access-control-request-headers",
            "sec-fetch-site",
            "sec-fetch-mode",
            "user-agent",
        ):
            if headers.get(name):
                details.append(f"{name}={self._redact(headers[name][:160])}")
        custom_headers = sorted(
            name for name in headers if name.startswith("xa4vrhyp3q-")
        )
        if custom_headers:
            details.append(f"custom-header-names={','.join(custom_headers)}")
        self._cdp_diagnostics.append("; ".join(details))

    def _on_cdp_response(self, event: dict) -> None:
        request_id = event.get("requestId", "")
        url = self._cdp_request_urls.get(request_id, "")
        if not url or len(self._cdp_diagnostics) >= 30:
            return

        headers = {
            str(key).lower(): str(value)
            for key, value in event.get("headers", {}).items()
        }
        details = [
            f"{self._cdp_request_methods.get(request_id, 'unknown')} "
            f"response HTTP {event.get('statusCode', 'unknown')} "
            f"{self._safe_url(url)}"
        ]
        for name in (
            "content-type",
            "access-control-allow-origin",
            "access-control-allow-methods",
            "access-control-allow-headers",
            "access-control-allow-credentials",
            "vary",
            "server",
        ):
            if headers.get(name):
                details.append(
                    f"{name}={self._redact(headers[name][:160])}"
                )
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
        if "apiext.telecentro.net.ar" in request.url:
            headers = await request.all_headers()
            authorization = headers.get("authorization", "")
            if (
                not self._jwt
                and authorization.lower().startswith("bearer ")
                and len(authorization) > 20
            ):
                self._jwt = authorization[7:]

        if self._login_submitted and len(self._requests) < 30:
            self._requests.append(await self._describe_request(request))

    def _on_request_failed(self, request: Request) -> None:
        if not self._is_auth_request(request.url):
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
            for marker in (
                "apiext.telecentro.net.ar",
                "autenticar",
                "cors",
                "access-control",
                "net::err_failed",
            )
        ):
            return
        self._console_errors.append(self._redact(text[:500]))

    def _schedule_response_diagnostics(self, response: Response) -> None:
        if self._login_submitted and self._is_auth_request(response.url):
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

        for header in (
            "content-type",
            "access-control-allow-origin",
            "access-control-allow-methods",
            "access-control-allow-headers",
            "access-control-allow-credentials",
            "vary",
            "server",
        ):
            value = headers.get(header)
            if value:
                parts.append(f"{header}={self._redact(value[:160])}")

        try:
            body = await response.text()
        except PlaywrightError as e:
            parts.append(f"body-unavailable={type(e).__name__}")
        else:
            parts.append(self._summarize_body(body, headers.get("content-type", "")))

        self._responses.append("; ".join(parts))

    async def _describe_request(self, request: Request) -> str:
        parts = [
            f"{request.method} {self._safe_url(request.url)}",
            f"resource={request.resource_type}",
        ]
        headers = await request.all_headers()
        for header in (
            "content-type",
            "origin",
            "referer",
            "user-agent",
            "sec-ch-ua",
            "access-control-request-method",
            "access-control-request-headers",
            "sec-fetch-site",
            "sec-fetch-mode",
            "sec-fetch-dest",
        ):
            value = headers.get(header)
            if value:
                parts.append(f"{header}={self._redact(value[:160])}")

        content_type = headers.get("content-type", "").lower()
        if "json" not in content_type and "application/x-www-form-urlencoded" not in content_type:
            return "; ".join(parts)

        try:
            body = request.post_data
        except UnicodeDecodeError:
            return "; ".join(parts + ["body=binary"])
        if not body:
            return "; ".join(parts)

        keys: list[str] = []
        if "json" in content_type:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                keys = [str(key) for key in list(payload)[:15]]
        else:
            keys = [key for key, _ in parse_qsl(body, keep_blank_values=True)[:15]]
        if keys:
            parts.append(f"body-keys={','.join(keys)}")
        return "; ".join(parts)

    async def _fill_login_form(self) -> None:
        try:
            email_input = self.page.locator(
                'input[type="email"], input[name="email"], input[placeholder*="mail" i]'
            ).first
            await email_input.wait_for(state="visible", timeout=self.config.timeout_ms)
            await email_input.fill(self.config.email)

            password_input = self.page.locator('input[type="password"]').first
            await password_input.wait_for(state="visible", timeout=5000)
            await password_input.fill(self.config.password)

            submit_button = self.page.locator(
                'button:has-text("Ingresar"), button[type="submit"]'
            ).first
            self._login_submitted = True
            await submit_button.click()
        except PlaywrightTimeout as e:
            raise NavigationError(
                f"Timeout completando el formulario de Telecentro: {e}"
            ) from e

    async def _wait_for_jwt_after_login(self) -> None:
        for _ in range(120):
            if "/home" in self.page.url and self._jwt:
                return

            error = self.page.get_by_text("Ha ocurrido un error", exact=False).first
            if await error.count() and await error.is_visible():
                await asyncio.sleep(0.5)
                raise LoginError(
                    f"Telecentro mostró un error al iniciar sesión: "
                    f"{(await error.inner_text()).strip()} | "
                    f"Diagnóstico: {self._diagnostics()}"
                )
            await asyncio.sleep(0.5)

        raise LoginError(
            f"Login de Telecentro no completó. URL: {self.page.url} | "
            f"JWT: {'sí' if self._jwt else 'no'} | "
            f"Diagnóstico: {self._diagnostics()}"
        )

    async def _wait_for_jwt_from_active_session(self) -> None:
        try:
            await self.page.wait_for_load_state(
                "networkidle", timeout=self.config.timeout_ms
            )
        except PlaywrightTimeout:
            pass

        for _ in range(30):
            if self._jwt:
                return
            await asyncio.sleep(0.5)

        raise LoginError(
            "Sesión activa en home pero no se capturó el JWT de las llamadas a apiext."
        )

    def _diagnostics(self) -> str:
        return (
            f"requests=[{' | '.join(self._requests) or '(none)'}]; "
            f"responses=[{' | '.join(self._responses) or '(none)'}]; "
            f"failed=[{' | '.join(self._failures) or '(none)'}]; "
            f"console=[{' | '.join(self._console_errors) or '(none)'}]; "
            f"chromium=[{' | '.join(self._cdp_diagnostics) or '(none)'}]"
        )

    def _is_auth_request(self, url: str) -> bool:
        return self._network_diagnostics.matches_domain(url)

    def _safe_url(self, url: str) -> str:
        return self._network_diagnostics.safe_url(url)

    def _summarize_body(self, body: str, content_type: str) -> str:
        return self._network_diagnostics.summarize_body(
            body,
            content_type,
            ("error", "message", "mensaje", "code", "codigo", "estado"),
            (self.config.email, self.config.password, self._jwt),
        )

    def _redact(self, value: str) -> str:
        return self._network_diagnostics.redact(
            value, (self.config.email, self.config.password, self._jwt)
        )
