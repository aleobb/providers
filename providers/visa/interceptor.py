from __future__ import annotations

import asyncio
from typing import Any

from playwright.async_api import Page, Response

# Fragmentos de URL que nos interesan en el trafico de Prisma
_API_FRAGMENTS = (
    "mis-tarjetas.prismamediosdepago.com",
    "mistarjetas.prismamediosdepago.com",
    "mycards.prismamediosdepago.com",
)


class NetworkInterceptor:
    """
    Captura responses de la API de Prisma/Visa del trafico del browser.

    Detecta:
    - Token JWT (cookie 'token' o header Authorization)
    - Datos de tarjetas / cuentas
    - URLs de descarga de resumenes
    """

    def __init__(self):
        self.captured: list[dict[str, Any]] = []
        self.auth_token: str | None = None
        self._lock = asyncio.Lock()

    async def start(self, page: Page) -> None:
        page.on("response", self._handle_response)

    async def _handle_response(self, response: Response) -> None:
        url = response.url
        if not any(frag in url for frag in _API_FRAGMENTS):
            return

        # Capturar token de los headers del request
        req_headers = response.request.headers
        auth = req_headers.get("authorization", "")
        if auth.startswith("Bearer ") and not self.auth_token:
            async with self._lock:
                self.auth_token = auth[len("Bearer "):]

        # Intentar parsear body JSON
        body: Any = None
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            try:
                body = await response.json()
            except Exception:
                pass
        elif response.status == 200 and "pdf" not in content_type:
            try:
                body = await response.json()
            except Exception:
                pass

        # Capturar token del body si viene del login/refresh
        if isinstance(body, dict):
            for key in ("token", "access_token", "accessToken"):
                if key in body and not self.auth_token:
                    async with self._lock:
                        self.auth_token = str(body[key])

        async with self._lock:
            self.captured.append({
                "url": url,
                "status": response.status,
                "body": body,
            })

    def find_body_for_url(self, *fragments: str) -> Any:
        """Devuelve el body del primer response cuya URL contenga todos los fragmentos."""
        for entry in self.captured:
            if all(f in entry["url"] for f in fragments):
                return entry["body"]
        return None

    def find_bodies_for_url(self, *fragments: str) -> list[Any]:
        """Devuelve todos los bodies cuya URL contenga todos los fragmentos."""
        return [
            e["body"]
            for e in self.captured
            if all(f in e["url"] for f in fragments) and e["body"] is not None
        ]

    def find_url_containing(self, *fragments: str) -> str | None:
        """Devuelve la primera URL que contenga todos los fragmentos."""
        for entry in self.captured:
            if all(f in entry["url"] for f in fragments):
                return entry["url"]
        return None

    def dump_captured(self) -> None:
        """Imprime un resumen de todo lo capturado (util para debug)."""
        print(f"  [Visa interceptor] {len(self.captured)} responses capturadas:")
        for e in self.captured:
            body_preview = ""
            if isinstance(e["body"], dict):
                keys = list(e["body"].keys())[:5]
                body_preview = f" keys={keys}"
            elif isinstance(e["body"], list):
                body_preview = f" list[{len(e['body'])}]"
            print(f"    {e['status']} {e['url']}{body_preview}")
