from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urljoin

import httpx
from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeout

from core.exceptions import DownloadError


class DownloadStrategies:
    """Browser and direct-HTTP strategies for retrieving a Visa PDF."""

    def __init__(
        self,
        page: Page,
        context: BrowserContext,
        dump_resumen_links: Callable[[], Awaitable[None]],
    ):
        self.page = page
        self.context = context
        self._dump_resumen_links = dump_resumen_links
        self._client: httpx.AsyncClient | None = None

    async def try_download_event(self) -> bytes | None:
        try:
            async with self.page.expect_download(timeout=3000) as dl_info:
                await self._click_download_button()
            download = await dl_info.value
            path = await download.path()
            if path:
                data = Path(path).read_bytes()
                if data[:4] == b"%PDF":
                    return data
        except PlaywrightTimeout:
            pass
        except Exception as error:
            print(f"  [Visa] Download event fallo: {error}")
        return None

    async def try_popup_download(self) -> bytes | None:
        try:
            async with self.page.expect_popup(timeout=3000) as popup_info:
                await self._click_download_button()
            popup = await popup_info.value
            await popup.wait_for_load_state("domcontentloaded", timeout=15000)
            pdf_url = popup.url
            await popup.close()

            if pdf_url and pdf_url not in ("about:blank", ""):
                print(f"  [Visa] PDF via popup: {pdf_url}")
                data = await self.fetch_url(pdf_url)
                if data[:4] == b"%PDF":
                    return data
        except PlaywrightTimeout:
            pass
        except Exception as error:
            print(f"  [Visa] Popup strategy fallo: {error}")
        return None

    async def _click_download_button(self) -> None:
        clickables = self.page.locator(
            'a, button, input[type="button"], input[type="submit"], '
            '[role="button"], [onclick]'
        )
        for index in range(await clickables.count()):
            try:
                element = clickables.nth(index)
                if not await element.is_visible(timeout=300):
                    continue
                label = " ".join(
                    filter(
                        None,
                        [
                            await element.text_content(),
                            await element.get_attribute("value"),
                            await element.get_attribute("title"),
                            await element.get_attribute("aria-label"),
                        ],
                    )
                ).strip().lower()
                if not re.search(r"descarg|imprim|pdf", label):
                    continue
                print(f"  [Visa] Click descarga en control: {label[:100]!r}")
                await element.click()
                return
            except Exception:
                pass

        embedded_pdf = await self.find_pdf_link_in_dom()
        if embedded_pdf:
            print(f"  [Visa] PDF embebido detectado: {embedded_pdf}")
            return

        await self._dump_resumen_links()
        raise DownloadError(
            "No se encontro link de descarga en la pagina de resumen de Visa"
        )

    def find_pdf_url_in_captured(self, entries: list[dict]) -> str | None:
        for entry in entries:
            url = entry.get("url", "")
            if any(
                keyword in url.lower()
                for keyword in ("pdf", "resumen", "download", "factura", "comprobante")
            ):
                if entry.get("status") == 200:
                    return url
        return None

    async def find_pdf_link_in_dom(self) -> str | None:
        try:
            urls = await self.page.evaluate(
                r"""() => {
                    const result = [];
                    for (const el of document.querySelectorAll(
                        'a[href], iframe[src], embed[src], object[data]'
                    )) {
                        const url = el.getAttribute('href')
                            || el.getAttribute('src')
                            || el.getAttribute('data');
                        if (!url) continue;
                        const type = (el.getAttribute('type') || '').toLowerCase();
                        const hint = `${url} ${type}`.toLowerCase();
                        if (/\.pdf|pdf|resumen|download|descarg/.test(hint)) {
                            result.push(url);
                        }
                    }
                    return result;
                }"""
            )
            for url in urls:
                return urljoin(self.page.url, url)
        except Exception as error:
            print(f"  [Visa] Error buscando links PDF: {error}")
        return None

    async def fetch_url(self, url: str) -> bytes:
        cookies = {cookie["name"]: cookie["value"] for cookie in await self.context.cookies()}
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
        response = await self._client.get(url)
        if response.status_code >= 400:
            raise DownloadError(
                f"HTTP {response.status_code} descargando PDF de Visa desde {url}"
            )
        return response.content

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
