from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeout

from core.exceptions import DownloadError
from core.utils import unique_path
from .config import EdesurConfig


class InvoiceService:
    def __init__(self, page: Page, context: BrowserContext, config: EdesurConfig):
        self.page = page
        self.context = context
        self.config = config

    async def download_for_client(self, client_number: str) -> Path:
        await self._select_account(client_number)
        await asyncio.sleep(2)

        period = await self._extract_period()
        dest_dir = self.config.ensure_output_dir()
        dest_path = unique_path(
            dest_dir / f"edesur_{period}_{client_number}_factura.pdf"
        )

        pdf_bytes = await self._download_via_popup()
        dest_path.write_bytes(pdf_bytes)
        return dest_path

    async def _select_account(self, client_number: str) -> None:
        """Select the account in the portal's account dropdown."""
        # Check if the current account already matches
        current = await self.page.evaluate(
            "JSON.parse(localStorage.getItem('DATOSSUMINISTRO') || '{}')?.detalle?.contractAccount"
        )
        if current == client_number:
            return

        # Open the account selector dropdown
        selector_btn = self.page.locator('nav[aria-label="selector-cuentas"] button').first
        if await selector_btn.count() > 0:
            await selector_btn.click()
            await asyncio.sleep(1)

            # Click the option that contains this client number
            option = self.page.locator(f'text="{client_number}"').first
            if await option.count() > 0:
                await option.click()
                await asyncio.sleep(3)
                await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)

    async def _extract_period(self) -> str:
        """Extract billing period from the page."""
        try:
            # Look for "1er Vencimiento DD/MM/YYYY"
            text = await self.page.locator("body").inner_text()
            import re
            dates = re.findall(r"(\d{2})/(\d{2})/(\d{4})", text)
            if dates:
                d, m, y = dates[0]
                return f"{y}-{m}"
        except Exception:
            pass
        return "sin-fecha"

    async def _download_via_popup(self) -> bytes:
        """Click Descargar, handle the docuprint popup with reCAPTCHA, download PDF."""

        # Click "Descargar" and capture the popup
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
            await popup.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
            await asyncio.sleep(2)
            await popup.bring_to_front()

            # The popup is on edesur.docuprint.com with a reCAPTCHA v2 checkbox
            # Try to click the reCAPTCHA checkbox automatically
            recaptcha_clicked = False
            recaptcha_frame = popup.frame_locator('iframe[src*="recaptcha"]').first
            try:
                checkbox = recaptcha_frame.locator("#recaptcha-anchor")
                await checkbox.click(timeout=5000)
                recaptcha_clicked = True
                await asyncio.sleep(3)
            except Exception:
                pass

            if not recaptcha_clicked or not self.config.headless:
                print(
                    "  [CAPTCHA] Resolver el captcha en la ventana del browser "
                    "y luego hacer click en 'Descargá tu factura digital'...",
                    file=sys.stderr,
                    flush=True,
                )

            # Wait for the download button to become enabled (captcha solved)
            download_btn = popup.locator("#downloadBtn")
            if await download_btn.count() == 0:
                download_btn = popup.get_by_role(
                    "button", name="Descargá tu factura digital"
                )

            # Give user up to 120 seconds in debug mode to solve captcha
            max_wait = 120 if not self.config.headless else 30
            for _ in range(max_wait):
                try:
                    if not await download_btn.is_disabled():
                        break
                except Exception:
                    pass
                await asyncio.sleep(1)
            else:
                raise DownloadError(
                    "El botón de descarga no se habilitó. "
                    "Ejecutar con --debug para resolver el captcha manualmente."
                )

            # Click download and intercept the PDF
            try:
                async with popup.expect_download(timeout=30000) as download_info:
                    await download_btn.click()
                download = await download_info.value
                download_path = await download.path()
                if download_path is None:
                    raise DownloadError("La descarga no produjo un archivo.")
                return Path(download_path).read_bytes()
            except PlaywrightTimeout:
                # Fallback: the download might happen as a navigation
                # Wait for the popup to navigate to a PDF URL
                await asyncio.sleep(5)
                pdf_url = popup.url
                if pdf_url and "pdf" in pdf_url.lower():
                    import httpx
                    cookies = {
                        c["name"]: c["value"]
                        for c in await self.context.cookies()
                    }
                    async with httpx.AsyncClient(
                        cookies=cookies, follow_redirects=True, timeout=60
                    ) as client:
                        r = await client.get(pdf_url)
                        if r.status_code < 400:
                            return r.content
                raise DownloadError(
                    "No se pudo descargar la factura desde docuprint."
                )

        finally:
            if not popup.is_closed():
                await popup.close()
