from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
from playwright.async_api import (
    BrowserContext,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeout,
)

from core.exceptions import DownloadError
from core.utils import unique_path
from .config import EdesurConfig


class InvoiceService:
    def __init__(self, page: Page, context: BrowserContext, config: EdesurConfig):
        self.page = page
        self.context = context
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def download_for_client(self, client_number: str) -> Path:
        dest_dir = self.config.ensure_output_dir()

        # Auto-detectar URL desde Gmail si hay credenciales configuradas
        if not self.config.docuprint_url:
            from pathlib import Path as _Path
            creds_file = _Path(self.config.gmail_credentials_file)
            if creds_file.exists():
                try:
                    from .gmail_reader import find_docuprint_url
                    url = find_docuprint_url(
                        credentials_file=creds_file,
                        token_file=_Path(self.config.gmail_token_file),
                    )
                    if url:
                        print(f"  [Gmail] URL encontrada: {url}", file=sys.stderr, flush=True)
                        self.config.docuprint_url = url
                except Exception as e:
                    print(f"  [Gmail] Error leyendo mail: {e}", file=sys.stderr, flush=True)

        # Flujo alternativo: URL directa desde el mail (saltea login y portal)
        if self.config.docuprint_url:
            period = "sin-fecha"
            dest_path = unique_path(
                dest_dir / f"edesur_{period}_{client_number}_factura.pdf"
            )
            pdf_bytes = await self._download_from_url(self.config.docuprint_url)
            dest_path.write_bytes(pdf_bytes)
            return dest_path

        # Flujo principal: portal de Edesur
        await self._select_account(client_number)
        await asyncio.sleep(2)

        period = await self._extract_period()
        dest_path = unique_path(
            dest_dir / f"edesur_{period}_{client_number}_factura.pdf"
        )
        pdf_bytes = await self._download_via_popup()
        dest_path.write_bytes(pdf_bytes)
        return dest_path

    async def _download_from_url(self, docuprint_url: str) -> bytes:
        """Descarga el PDF navegando directo a la URL de Docuprint (del mail).
        No requiere login al portal de Edesur. La verificación humana, si aparece,
        debe completarse manualmente en el browser visible.
        """
        await self.page.goto(
            docuprint_url,
            timeout=self.config.timeout_ms,
            wait_until="domcontentloaded",
        )
        await asyncio.sleep(2)

        download_btn = await self._wait_for_download_button(self.page)

        async with self.page.expect_download(timeout=30000) as download_info:
            await download_btn.click()
        download = await download_info.value
        download_path = await download.path()
        if download_path is None:
            raise DownloadError("La descarga no produjo un archivo.")
        return Path(download_path).read_bytes()

    async def _select_account(self, client_number: str) -> None:
        """Select the account in the portal's account dropdown."""
        current = await self.page.evaluate(
            "JSON.parse(localStorage.getItem('DATOSSUMINISTRO') || '{}')?.detalle?.contractAccount"
        )
        if current == client_number:
            return

        selector_btn = self.page.locator('nav[aria-label="selector-cuentas"] button').first
        if await selector_btn.count() > 0:
            await selector_btn.click()
            await asyncio.sleep(1)

            option = self.page.locator(f'text="{client_number}"').first
            if await option.count() > 0:
                await option.click()
                await asyncio.sleep(3)
                await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)

    async def _extract_period(self) -> str:
        """Extract billing period from the page."""
        try:
            import re
            text = await self.page.locator("body").inner_text()
            dates = re.findall(r"(\d{2})/(\d{2})/(\d{4})", text)
            if dates:
                d, m, y = dates[0]
                return f"{y}-{m}"
        except Exception:
            pass
        return "sin-fecha"

    async def _download_via_popup(self) -> bytes:
        """Open Docuprint, wait for any human verification, and download the PDF."""

        descargar_btn = self.page.locator("button.ultima-factura-btn").first
        if await descargar_btn.count() == 0:
            descargar_btn = self.page.get_by_role("button", name="Descargar").first

        try:
            async with self.context.expect_page(timeout=15000) as popup_info:
                await descargar_btn.click()
            popup = await popup_info.value
        except PlaywrightTimeout:
            raise DownloadError(
                "No se abrió la ventana de descarga de factura. "
                "Verificar que la cuenta tenga factura disponible."
            )

        try:
            await popup.wait_for_load_state(
                "domcontentloaded", timeout=self.config.timeout_ms
            )
            await asyncio.sleep(2)
            await popup.bring_to_front()

            download_btn = await self._wait_for_download_button(popup)

            try:
                async with popup.expect_download(timeout=30000) as download_info:
                    await download_btn.click()
                download = await download_info.value
                download_path = await download.path()
                if download_path is None:
                    raise DownloadError("La descarga no produjo un archivo.")
                return Path(download_path).read_bytes()
            except PlaywrightTimeout:
                await asyncio.sleep(5)
                pdf_url = popup.url
                if pdf_url and "pdf" in pdf_url.lower():
                    cookies = {
                        c["name"]: c["value"]
                        for c in await self.context.cookies()
                    }
                    if self._client is None:
                        self._client = httpx.AsyncClient(
                            cookies=cookies, follow_redirects=True, timeout=60
                        )
                    else:
                        self._client.cookies.clear()
                        self._client.cookies.update(cookies)
                    r = await self._client.get(pdf_url)
                    if r.status_code < 400:
                        return r.content
                raise DownloadError(
                    "No se pudo descargar la factura desde docuprint."
                )

        finally:
            if not popup.is_closed():
                await popup.close()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _wait_for_download_button(self, page: Page) -> Locator:
        download_btn = page.locator("#downloadBtn")
        if await download_btn.count() == 0:
            download_btn = page.get_by_role(
                "button", name="Descargá tu factura digital"
            )

        if not self.config.headless:
            print(
                "  [Verificación] Si aparece Cloudflare o reCAPTCHA, "
                "completá la verificación en la ventana del browser. "
                "La descarga continuará automáticamente.",
                file=sys.stderr,
                flush=True,
            )

        timeout_seconds = 30 if self.config.headless else 180
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            if (
                await download_btn.count() > 0
                and await download_btn.is_visible()
                and not await download_btn.is_disabled()
            ):
                return download_btn
            await asyncio.sleep(1)

        if self.config.headless:
            raise DownloadError(
                "El botón de descarga no se habilitó. Si Edesur solicita "
                "verificación humana, ejecutá con --debug para completarla "
                "en el browser visible."
            )
        raise DownloadError(
            "La verificación humana no se completó o el botón de descarga "
            "siguió deshabilitado después de 180 segundos."
        )
