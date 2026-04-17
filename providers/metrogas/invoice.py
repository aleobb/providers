from __future__ import annotations

import re
from pathlib import Path

import httpx
from playwright.async_api import Page

from core.exceptions import DownloadError
from core.utils import unique_path
from .config import MetrogasConfig

_INVOICE_API_PATH = "/sap/fiori/ovcustdashboard//OvServiceHub/api/v1/M360/invoice/isu/lastInvoice/"


class InvoiceService:
    def __init__(self, page: Page, config: MetrogasConfig):
        self.page = page
        self.config = config
        self._cookies: dict | None = None

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

        async with httpx.AsyncClient(
            cookies=cookies, follow_redirects=True, timeout=60, verify=False
        ) as client:
            r = await client.get(pdf_url)
            if r.status_code >= 400:
                raise DownloadError(
                    f"HTTP {r.status_code} al descargar factura para cliente {client_number}"
                )
            dest_path.write_bytes(r.content)

        return dest_path

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
