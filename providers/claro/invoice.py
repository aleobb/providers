from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx
from playwright.async_api import Page, Response, TimeoutError as PlaywrightTimeout

from core.accounts import Account
from core.exceptions import DownloadError
from core.utils import unique_path
from .config import ClaroConfig


class InvoiceService:
    def __init__(self, page: Page, config: ClaroConfig):
        self.page = page
        self.config = config

    async def download_for_account(self, account: Account) -> Path:
        factura_url = self._factura_url(account.client_number)
        period = await self._navigate_and_get_period(factura_url)
        download_url = await self._click_download_and_capture_url()

        dest_dir = self.config.ensure_output_dir()
        dest_path = unique_path(
            dest_dir / f"claro_{period}_{account.client_number}_factura.pdf"
        )
        await self._fetch_pdf(download_url, dest_path)
        return dest_path

    # ------------------------------------------------------------------ helpers

    def _factura_url(self, bill_number: str) -> str:
        b64 = base64.b64encode(bill_number.encode()).decode()
        encoded = quote(b64, safe="")
        return f"{self.config.portal_url}/{encoded}/factura"

    async def _navigate_and_get_period(self, factura_url: str) -> str:
        """Navega a la página de factura e intercepta /ciclos para obtener el período."""
        period_holder: list[str] = []

        async def on_response(response: Response) -> None:
            if period_holder:
                return
            if "ciclos" in response.url and response.status == 200:
                try:
                    data = await response.json()
                    p = _parse_period(data)
                    if p:
                        period_holder.append(p)
                except Exception:
                    pass

        self.page.on("response", on_response)
        try:
            await self.page.goto(factura_url, timeout=self.config.timeout_ms)
            await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
            await asyncio.sleep(2)
        finally:
            self.page.remove_listener("response", on_response)

        return period_holder[0] if period_holder else datetime.now().strftime("%Y-%m")

    async def _click_download_and_capture_url(self) -> str:
        """
        Hace click en "Descargar factura en PDF" e intercepta el popup que abre
        con la URL /factura/back/public/facturas/ultima?t=...
        """
        selector = ':text("Descargar factura en PDF")'
        try:
            await self.page.wait_for_selector(selector, timeout=self.config.timeout_ms)
        except PlaywrightTimeout:
            raise DownloadError("No se encontró el botón 'Descargar factura en PDF' en la página de Claro")

        try:
            async with self.page.expect_popup(timeout=15000) as popup_info:
                await self.page.click(selector)
        except PlaywrightTimeout:
            raise DownloadError("El popup de descarga de Claro no se abrió en el tiempo esperado")
        popup = await popup_info.value
        try:
            await popup.wait_for_url(
                lambda url: "ultima" in url,
                timeout=15000,
                wait_until="domcontentloaded",
            )
            url = popup.url
        except PlaywrightTimeout as error:
            raise DownloadError(
                "El popup de descarga de Claro se abrió, pero no navegó a la URL "
                f"de la factura. URL actual: {popup.url!r}"
            ) from error
        finally:
            await popup.close()

        if not url or "ultima" not in url:
            raise DownloadError(f"URL de descarga de Claro inesperada: {url!r}")

        return url

    async def _fetch_pdf(self, url: str, dest_path: Path) -> None:
        cookies = {c["name"]: c["value"] for c in await self.page.context.cookies()}
        async with httpx.AsyncClient(
            cookies=cookies,
            follow_redirects=True,
            timeout=60,
        ) as client:
            r = await client.get(url)
            if r.status_code >= 400:
                raise DownloadError(
                    f"HTTP {r.status_code} al descargar PDF de Claro desde {url}"
                )
        dest_path.write_bytes(r.content)


# ------------------------------------------------------------------ period parsing

def _parse_period(data) -> str:
    """
    Intenta extraer un período (YYYY-MM) del JSON de /factura/back/cuenta/ciclos.
    Soporta formatos: YYYY-MM, MM/YYYY, YYYYMM, DD/MM/YYYY (usa año-mes).
    """
    text = json.dumps(data) if isinstance(data, (dict, list)) else str(data)

    # YYYY-MM directo
    m = re.search(r'20\d\d-\d\d', text)
    if m:
        return m.group(0)

    # YYYYMM (sin separador, 6 dígitos)
    m = re.search(r'(20\d\d)(\d\d)\b', text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    # DD/MM/YYYY o MM/YYYY
    m = re.search(r'\d{2}/\d{2}/(20\d\d)', text)
    if m:
        # Extraer el mes del contexto
        m2 = re.search(r'\d{2}/(\d{2})/20\d\d', text)
        if m2:
            return f"{m.group(1)}-{m2.group(1)}"

    return ""
