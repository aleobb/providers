from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path

import httpx
from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeout

from core.accounts import Account
from core.exceptions import DownloadError, InvoiceNotFoundError
from core.utils import dismiss_popups, unique_path
from .config import VisaConfig
from .interceptor import NetworkInterceptor


class InvoiceService:
    def __init__(
        self,
        page: Page,
        context: BrowserContext,
        interceptor: NetworkInterceptor,
        config: VisaConfig,
    ):
        self.page = page
        self.context = context
        self.interceptor = interceptor
        self.config = config

    async def download_for_account(self, account: Account) -> Path:
        period, pdf_bytes = await self._get_invoice(account)

        dest_dir = self.config.ensure_output_dir()
        dest_path = unique_path(
            dest_dir / f"visa_{period}_{account.client_number}_resumen.pdf"
        )
        dest_path.write_bytes(pdf_bytes)
        return dest_path

    # ------------------------------------------------------------------ main flow

    async def _get_invoice(self, account: Account) -> tuple[str, bytes]:
        """
        Obtiene el PDF del ultimo resumen.

        Estrategia 1: navegar a la pagina de resumen y capturar via interceptor o download event.
        Estrategia 2: buscar link PDF directo en la pagina.
        """
        await self._navigate_to_dashboard()

        # Limpiar capturas anteriores para este account
        prev_count = len(self.interceptor.captured)

        period = await self._navigate_to_resumen(account)

        # Estrategia 1: download event del browser
        pdf_bytes = await self._try_download_event()
        if pdf_bytes:
            return period, pdf_bytes

        # Estrategia 2: popup con URL al PDF
        pdf_bytes = await self._try_popup_download()
        if pdf_bytes:
            return period, pdf_bytes

        # Estrategia 3: interceptar URL de descarga del trafico capturado
        new_entries = self.interceptor.captured[prev_count:]
        pdf_url = self._find_pdf_url_in_captured(new_entries)
        if pdf_url:
            print(f"  [Visa] Descargando via URL interceptada: {pdf_url}")
            pdf_bytes = await self._fetch_url(pdf_url)
            return period, pdf_bytes

        # Estrategia 4: link directo en la pagina
        pdf_url = await self._find_pdf_link_in_dom()
        if pdf_url:
            print(f"  [Visa] Descargando via link en DOM: {pdf_url}")
            pdf_bytes = await self._fetch_url(pdf_url)
            return period, pdf_bytes

        raise DownloadError(
            "No se pudo descargar el PDF del resumen de Visa. "
            "Ejecutar con --debug para inspeccionar manualmente."
        )

    # ------------------------------------------------------------------ navigation

    async def _navigate_to_dashboard(self) -> None:
        # Siempre navegar al dashboard para asegurar que la lista de tarjetas
        # este disponible y con la tarjeta por defecto (no la ultima seleccionada).
        # Esto es critico para el segundo+ account: tras el resumen del primero
        # la URL sigue siendo mistarjetas pero el contenido no es el card-list.
        await self.page.goto(self.config.portal_url, timeout=self.config.timeout_ms)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(0.6)
        # Un solo pase de dismiss_popups (los bucles generan loops visibles de scroll)
        await dismiss_popups(self.page, label="visa")

    async def _navigate_to_resumen(self, account: Account) -> str:
        """
        Hace click en 'Ver Resumen' para el account dado.
        Si hay multiples tarjetas, primero selecciona la correcta.
        Retorna el periodo detectado (YYYY-MM).
        """
        # Si hay mas de una tarjeta, intentar seleccionar la correcta
        await self._select_card_if_needed(account)

        clicked = await self._click_ver_resumen()
        if not clicked:
            await self._dump_dashboard_links()
            raise DownloadError(
                f"No se encontro el boton 'Resumen de Cuenta' para Visa ****{account.client_number}."
            )

        # El portal es jQuery/JSP: el contenido carga en la misma pagina via AJAX.
        # Esperamos networkidle + pausa extra para que el DOM se actualice.
        try:
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(2)
        print(f"  [Visa] Resumen cargado. URL: {self.page.url}")

        # Verificar si hay resumen disponible para esta tarjeta
        await self._assert_resumen_disponible(account)

        return await self._extract_period()

    async def _assert_resumen_disponible(self, account: Account) -> None:
        """
        Verifica que haya un resumen disponible para esta tarjeta.
        Si no hay resumen (tarjeta sin actividad, periodo cerrado, etc.)
        lanza InvoiceNotFoundError en lugar de DownloadError.
        """
        _NO_RESUMEN_TEXTS = [
            "no tiene resumen",
            "no hay resumen",
            "sin resumen",
            "no posee resumen",
            "no existen resumenes",
            "no se encontr",        # "no se encontró resumen"
            "no disponible",
        ]
        try:
            body = (await self.page.inner_text("body", timeout=3000)).lower()
            for txt in _NO_RESUMEN_TEXTS:
                if txt in body:
                    raise InvoiceNotFoundError(
                        f"Visa ****{account.client_number}: no hay resumen disponible."
                    )
        except InvoiceNotFoundError:
            raise
        except Exception:
            pass

    async def _select_card_if_needed(self, account: Account) -> None:
        """
        Selecciona la tarjeta indicada en el portal de mistarjetas.

        El portal tiene un boton "Seleccione otra tarjeta" que despliega una lista
        de <LI class="card-selection-div">.  Hay que:
          1. Verificar si la tarjeta activa ya es la buscada (evita switch innecesario).
          2. Hacer click en "Seleccione otra tarjeta" para abrir el dropdown.
          3. Esperar a que los LI queden visibles.
          4. Hacer click en el LI que corresponde a los 4 digitos buscados.
          5. Verificar que el switch ocurrio (la tarjeta activa muestra los 4 digitos).
        """
        last4 = account.client_number

        # Short-circuit: si la tarjeta activa ya es la buscada, no hace falta switchear
        if await self._active_card_matches(last4):
            print(f"  [Visa] Tarjeta activa ya es ****{last4} — sin switch.")
            return

        # Abrir el selector
        opened = await self._open_card_selector()
        if not opened:
            print(f"  [Visa] Advertencia: no se pudo abrir el selector de tarjetas para ****{last4}.")
            return

        await asyncio.sleep(0.6)

        # Clickear el LI del selector
        await self._click_card_in_dropdown(last4)

        # Verificar que el switch fue efectivo
        for _ in range(10):  # hasta 5s
            if await self._active_card_matches(last4):
                print(f"  [Visa] Switch confirmado: tarjeta activa = ****{last4}.")
                return
            await asyncio.sleep(0.5)
        print(f"  [Visa] Advertencia: no pude confirmar el switch a ****{last4}.")

    async def _active_card_matches(self, last4: str) -> bool:
        """
        Devuelve True si la tarjeta activa del header del portal muestra los 4 digitos.

        Lee el header especifico (clase 'user-info grid-7 omega') que dropit.js
        usa como trigger y que cambia al hacer el switch. Evita falsos positivos
        de banners laterales que muestran otras tarjetas.
        """
        try:
            return await self.page.evaluate(
                r"""(last4) => {
                    // El header del portal (trigger dropit) muestra la tarjeta activa.
                    // Formato: "| Banco \n TARJETA N°: XXXX XXXX XXXX NNNN"
                    const HEADER_SELS = [
                        '.user-info.grid-7.omega',
                        '.user-info',
                        '.header.container-12',
                        'li.dropit-trigger',
                    ];
                    for (const sel of HEADER_SELS) {
                        const el = document.querySelector(sel);
                        if (el && el.offsetParent !== null) {
                            const text = el.textContent || '';
                            if (text.includes(last4)) return true;
                        }
                    }
                    return false;
                }""",
                last4,
            )
        except Exception:
            return False

    async def _open_card_selector(self) -> bool:
        """
        Abre el dropdown de seleccion de tarjeta.

        El portal Prisma usa dropit.js: el trigger es el header que muestra
        el banco y el numero de la tarjeta activa (clase 'user-info grid-7 omega').
        NO hay un boton con texto 'Seleccione otra tarjeta'.
        """
        # 1. Playwright: clases conocidas del header / dropit trigger
        playwright_selectors = [
            'li.dropit-trigger',               # dropit.js trigger estandar
            '.user-info.grid-7.omega',          # header con banco + numero activo
            '.grid-5.box-right',               # seccion derecha del header
            'div.user-info',                    # fallback
        ]
        for sel in playwright_selectors:
            try:
                el = self.page.locator(sel).first
                if await el.count() > 0 and await el.is_visible(timeout=500):
                    await el.click()
                    print(f"  [Visa] Dropdown abierto via ({sel})")
                    return True
            except Exception:
                pass

        # 2. JS: buscar LI con '|' como primer caracter (indicador de dropit trigger)
        result = await self.page.evaluate(
            r"""() => {
                // El trigger dropit.js tiene el caracter '|' al inicio del texto
                const lis = Array.from(document.querySelectorAll('li'));
                const trigger = lis.find(li =>
                    li.offsetParent !== null &&
                    (li.textContent || '').trimStart().startsWith('|')
                );
                if (trigger) {
                    trigger.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                    try { trigger.click(); } catch(e) {}
                    return { ok: true, tag: 'LI', cls: trigger.className,
                             text: trigger.textContent.trim().substring(0, 50) };
                }
                // Fallback: el DIV .user-info (header con banco activo)
                const uinfo = document.querySelector('.user-info');
                if (uinfo && uinfo.offsetParent !== null) {
                    uinfo.click();
                    return { ok: true, tag: 'DIV', cls: uinfo.className,
                             text: uinfo.textContent.trim().substring(0, 50) };
                }
                return { ok: false };
            }"""
        )
        if result.get("ok"):
            print(f"  [Visa] Dropdown abierto via JS (<{result['tag']}> cls={result.get('cls','')!r})")
            return True

        print("  [Visa] No se pudo abrir el dropdown de tarjetas.")
        return False

    async def _click_card_in_dropdown(self, last4: str) -> None:
        """
        Con el dropdown ya abierto, clickea el LI que corresponde a last4.
        En modo debug muestra el dump del DOM para diagnostico.
        """
        # Solo volcar DOM en modo debug (headless=False) para no ralentizar produccion
        if not self.config.headless:
            await self._dump_card_selector_elements(last4)

        result = await self.page.evaluate(
            r"""(last4) => {
                // Orden de preferencia: card-selection-div (dropdown), luego card-item (sidebar)
                const selectors = [
                    'li.card-selection-div',
                    'li.card-item',
                    'li.card-item.clearfix',
                    'li[class*="card-selection"]',
                    'li[class*="card-item"]',
                ];
                for (const sel of selectors) {
                    const items = Array.from(document.querySelectorAll(sel));
                    const target = items.find(li => (li.textContent || '').includes(last4));
                    if (target) {
                        target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                        try { target.click(); } catch(e) {}
                        return { clicked: true, cls: target.className,
                                 text: target.textContent.trim().substring(0, 80) };
                    }
                }

                // Fallback: cualquier LI que contenga los 4 digitos (visible o no —
                // en dropit.js los items del dropdown son hidden hasta que el trigger se abre)
                const anyLi = Array.from(document.querySelectorAll('li'))
                    .find(el => (el.textContent || '').includes(last4));
                if (anyLi) {
                    anyLi.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                    try { anyLi.click(); } catch(e) {}
                    return { clicked: true, fallback: true, cls: anyLi.className,
                             text: anyLi.textContent.trim().substring(0, 80) };
                }

                return { clicked: false };
            }""",
            last4,
        )

        if result.get("clicked"):
            fb = " (fallback)" if result.get("fallback") else ""
            cls = result.get("cls", "")
            print(f"  [Visa] Tarjeta ****{last4} seleccionada{fb} (.{cls}): {result.get('text','')!r}")
            await asyncio.sleep(1.0)
            try:
                await self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            # Un solo pase de dismiss_popups (sin bucles que generen scroll loops)
            await dismiss_popups(self.page, label="visa-card-switch")
        else:
            print(f"  [Visa] No se encontro LI para ****{last4} en el dropdown.")
            print(f"  [Visa] Se descargara la tarjeta activa en lugar de ****{last4}.")

    async def _dump_card_selector_elements(self, last4: str) -> None:
        """Muestra los LI del selector de tarjetas que contienen los 4 digitos."""
        try:
            items = await self.page.evaluate(
                r"""(last4) => {
                    return Array.from(document.querySelectorAll(
                        'li.card-selection-div, li[class*="card-selection"], li[class*="card-item"], li'
                    ))
                    .filter(el => (el.textContent || '').includes(last4))
                    .slice(0, 8)
                    .map(el => ({
                        tag: el.tagName,
                        cls: el.className || '',
                        text: el.textContent.trim().substring(0, 100),
                        visible: el.offsetParent !== null
                    }));
                }""",
                last4,
            )
            if items:
                print(f"  [Visa] LIs con ****{last4}:")
                for item in items:
                    vis = "V" if item["visible"] else "H"
                    print(f"    [{vis}] <LI .{item['cls'][:40]}>: {item['text']!r}")
            else:
                print(f"  [Visa] No hay LIs con '{last4}' en DOM.")
        except Exception as e:
            print(f"  [Visa] Error en dump: {e}")

    async def _click_ver_resumen(self) -> bool:
        """
        Navega a la pagina de resumen de la tarjeta activa.

        En el portal Prisma el acceso al resumen puede ser:
        - <button type='submit' class='button right white-button'>Ver resumen</button>
        - <a href='#'>Ver Resumen completo</a>
        - o items de submenu dropit (ocultos hasta hover)

        Usamos Playwright primero (mas confiable para botones submit) y luego JS.
        """
        # Textos posibles del boton/link de resumen
        _RESUMEN_TEXTS = [
            "Ver resumen",
            "Ver Resumen",
            "Resumen de Cuenta",
            "Resumen de cuenta",
            "Ver Resumen completo",
            "Resumen Digital",
            "Mi Resumen",
        ]

        # 1. Playwright: buscar botones visibles (es un <button submit> en el dashboard)
        for text in _RESUMEN_TEXTS:
            for tag in ["button", "a"]:
                try:
                    el = self.page.locator(f'{tag}:has-text("{text}")').first
                    if await el.count() > 0 and await el.is_visible(timeout=400):
                        print(f"  [Visa] Click resumen via Playwright: <{tag}> '{text}'")
                        await el.click()
                        return True
                except Exception:
                    pass

        # 2. JS: buscar en <a> y <button> (incluso ocultos — dropit submenu)
        clicked = await self.page.evaluate(
            """(texts) => {
                const els = Array.from(document.querySelectorAll('a, button'));
                for (const text of texts) {
                    const target = els.find(e => (e.textContent || '').trim() === text);
                    if (target) {
                        target.click();
                        return text;
                    }
                }
                return null;
            }""",
            _RESUMEN_TEXTS,
        )
        if clicked:
            print(f"  [Visa] JS click en: '{clicked}'")
            return True
        return False

    async def _dump_dashboard_links(self) -> None:
        """Vuelca todos los links visibles del dashboard para diagnostico."""
        try:
            print("  [Visa] Links en el dashboard:")
            links = await self.page.query_selector_all("a")
            for link in links[:40]:
                text = (await link.inner_text()).strip()
                href = await link.get_attribute("href") or ""
                if text:
                    print(f"    <a href={href!r}> {text!r}")
        except Exception as e:
            print(f"  [Visa] No se pudieron leer los links: {e}")

    async def _dump_resumen_links(self) -> None:
        """Vuelca links de la pagina de resumen para diagnostico."""
        try:
            print("  [Visa] Links en la pagina de resumen:")
            links = await self.page.query_selector_all("a")
            for link in links[:50]:
                text = (await link.inner_text()).strip()
                href = await link.get_attribute("href") or ""
                if text:
                    print(f"    <a href={href!r}> {text!r}")
        except Exception as e:
            print(f"  [Visa] No se pudieron leer links del resumen: {e}")

    async def _close_popup(self) -> None:
        for selector in [
            'a:has-text("cerrar")',
            'button:has-text("Cancelar")',
            'button:has-text("cerrar")',
            '[aria-label="cerrar"]',
        ]:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0 and await el.is_visible(timeout=2000):
                    await el.click()
                    await asyncio.sleep(0.5)
                    return
            except Exception:
                pass

    # ------------------------------------------------------------------ download strategies

    async def _try_download_event(self) -> bytes | None:
        """Intenta capturar un evento de descarga del browser."""
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
        except Exception as e:
            print(f"  [Visa] Download event fallo: {e}")
        return None

    async def _try_popup_download(self) -> bytes | None:
        """Intercepta popup/nueva pestana con URL al PDF."""
        try:
            async with self.page.expect_popup(timeout=3000) as popup_info:
                await self._click_download_button()
            popup = await popup_info.value
            await popup.wait_for_load_state("domcontentloaded", timeout=15000)
            pdf_url = popup.url
            await popup.close()

            if pdf_url and pdf_url not in ("about:blank", ""):
                print(f"  [Visa] PDF via popup: {pdf_url}")
                data = await self._fetch_url(pdf_url)
                if data[:4] == b"%PDF":
                    return data
        except PlaywrightTimeout:
            pass
        except Exception as e:
            print(f"  [Visa] Popup strategy fallo: {e}")
        return None

    async def _click_download_button(self) -> None:
        # Textos del portal Prisma para el link de descarga (en orden de prioridad)
        # Confirmado por dump: 'a:has-text("Descargar / Imprimir")' es el real
        candidates = [
            'a:has-text("Descargar / Imprimir")',
            'a:has-text("Descargar / imprimir")',
            'a:has-text("Descargar resumen")',
            'a:has-text("Descargar Resumen")',
            'a:has-text("Descargar")',
            'a:has-text("Descargar PDF")',
            'a:has-text("PDF")',
            'a[href*="descargar"]',
            'a[href*="download"]',
            'a[href*=".pdf"]',
        ]
        for selector in candidates:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0 and await el.is_visible(timeout=2000):
                    print(f"  [Visa] Click descarga: {selector}")
                    await el.click()
                    return
            except Exception:
                pass
        # Si no encontramos ningun link de descarga, volcar los links visibles
        await self._dump_resumen_links()
        raise DownloadError("No se encontro link de descarga en la pagina de resumen de Visa")

    def _find_pdf_url_in_captured(self, entries: list[dict]) -> str | None:
        """Busca en las capturas del interceptor una URL de descarga de PDF."""
        for entry in entries:
            url = entry.get("url", "")
            # URLs tipicas de descarga
            if any(kw in url.lower() for kw in ("pdf", "resumen", "download", "factura", "comprobante")):
                if entry.get("status") == 200:
                    return url
        return None

    async def _find_pdf_link_in_dom(self) -> str | None:
        """Busca links a PDFs en el DOM de la pagina."""
        base = "https://mistarjetas.prismamediosdepago.com"
        try:
            links = await self.page.query_selector_all(
                "a[href*='.pdf'], a[href*='pdf'], a[href*='resumen'], a[href*='download']"
            )
            for link in links:
                href = await link.get_attribute("href")
                if href:
                    if href.startswith("/"):
                        href = base + href
                    return href
        except Exception as e:
            print(f"  [Visa] Error buscando links PDF: {e}")
        return None

    # ------------------------------------------------------------------ helpers

    async def _extract_period(self) -> str:
        """Extrae el periodo del resumen (YYYY-MM) desde el texto de la pagina."""
        try:
            text = await self.page.inner_text("body")
            meses = {
                'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
                'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
                'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12',
            }
            m = re.search(
                r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
                r'septiembre|octubre|noviembre|diciembre)\s+(\d{4})',
                text, re.IGNORECASE,
            )
            if m:
                mes = meses.get(m.group(1).lower(), '01')
                return f"{m.group(2)}-{mes}"

            m2 = re.search(r'(\d{2})/(\d{4})', text)
            if m2:
                return f"{m2.group(2)}-{m2.group(1)}"

            m3 = re.search(r'20\d\d-\d\d', text)
            if m3:
                return m3.group(0)
        except Exception:
            pass
        return datetime.now().strftime("%Y-%m")

    async def _fetch_url(self, url: str) -> bytes:
        """Descarga una URL con las cookies del browser."""
        cookies = {c["name"]: c["value"] for c in await self.context.cookies()}
        async with httpx.AsyncClient(
            cookies=cookies,
            follow_redirects=True,
            timeout=60,
            verify=False,
        ) as client:
            r = await client.get(url)
            if r.status_code >= 400:
                raise DownloadError(
                    f"HTTP {r.status_code} descargando PDF de Visa desde {url}"
                )
            return r.content
