from __future__ import annotations

import re
from pathlib import Path

import httpx
from playwright.async_api import Page

from core.exceptions import DownloadError
from core.utils import unique_path
from .config import MetrogasConfig

_INVOICE_API_PATH = "/sap/fiori/ovcustdashboard//OvServiceHub/api/v1/M360/invoice/isu/lastInvoice/"


def _is_pdf_response(response: httpx.Response) -> bool:
    return 200 <= response.status_code < 300 and b"%PDF-" in response.content[:1024]


def _validated_pdf_content(response: httpx.Response, client_number: str) -> bytes:
    if response.status_code >= 400:
        raise DownloadError(
            f"HTTP {response.status_code} al descargar factura para cliente {client_number}"
        )
    if not _is_pdf_response(response):
        content_type = response.headers.get("content-type", "desconocido")
        raise DownloadError(
            f"Respuesta no es una factura PDF para cliente {client_number} "
            f"(HTTP {response.status_code}, content-type: {content_type}, "
            f"size: {len(response.content)} bytes). "
            "La sesión puede haber expirado; reintentar autenticación."
        )
    return response.content


class InvoiceService:
    def __init__(self, page: Page, config: MetrogasConfig):
        self.page = page
        self.config = config
        self._cookies: dict | None = None
        self._client: httpx.AsyncClient | None = None

    async def _get_cookies(self) -> dict:
        if self._cookies is None:
            cookies = await self.page.context.cookies()
            self._cookies = {c["name"]: c["value"] for c in cookies}
        return self._cookies

    async def download_for_client(self, client_number: str) -> Path:
        period = await self._extract_period()
        dest_dir = self.config.ensure_output_dir()
        dest_path = unique_path(dest_dir / f"metrogas_{period}_{client_number}_factura.pdf")

        pdf_url = (
            f"https://portal.micuenta.metrogas.com.ar{_INVOICE_API_PATH}{client_number}"
        )
        cookies = await self._get_cookies()

        client = self._get_client(cookies)
        r = await client.get(pdf_url)
        dest_path.write_bytes(_validated_pdf_content(r, client_number))

        return dest_path

    def _get_client(self, cookies: dict) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                cookies=cookies,
                follow_redirects=True,
                timeout=60,
                verify=False,
            )
        else:
            self._client.cookies.clear()
            self._client.cookies.update(cookies)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _extract_period(self) -> str:
        body = await self.page.locator("body").inner_text()
        dates = re.findall(r"(\d{2})/(\d{2})/(\d{4})", body)
        if len(dates) >= 2:
            d, m, y = dates[1]
            return f"{y}-{m}"
        if dates:
            d, m, y = dates[0]
            return f"{y}-{m}"
        return "sin-fecha"
