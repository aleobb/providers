from __future__ import annotations

import asyncio
from pathlib import Path
from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeout

from core.accounts import Account
from core.exceptions import DownloadError, InvoiceNotFoundError
from core.utils import dismiss_popups, unique_path
from .card_selector import CardSelector
from .config import VisaConfig
from .download_strategies import DownloadStrategies
from .interceptor import NetworkInterceptor
from .periods import extract_period


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
        self._card_selector = CardSelector(page)
        self._download_strategies = DownloadStrategies(
            page, context, self._dump_resumen_links
        )

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
        pdf_bytes = await self._download_strategies.try_download_event()
        if pdf_bytes:
            return period, pdf_bytes

        # Estrategia 2: popup con URL al PDF
        pdf_bytes = await self._download_strategies.try_popup_download()
        if pdf_bytes:
            return period, pdf_bytes

        # Estrategia 3: interceptar URL de descarga del trafico capturado
        new_entries = self.interceptor.captured[prev_count:]
        pdf_url = self._download_strategies.find_pdf_url_in_captured(new_entries)
        if pdf_url:
            print(f"  [Visa] Descargando via URL interceptada: {pdf_url}")
            pdf_bytes = await self._download_strategies.fetch_url(pdf_url)
            return period, pdf_bytes

        # Estrategia 4: link directo en la pagina
        pdf_url = await self._download_strategies.find_pdf_link_in_dom()
        if pdf_url:
            print(f"  [Visa] Descargando via link en DOM: {pdf_url}")
            pdf_bytes = await self._download_strategies.fetch_url(pdf_url)
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
            await self.page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(0.6)
        # Un solo pase de dismiss_popups (los bucles generan loops visibles de scroll)
        await dismiss_popups(self.page, label="visa")
        # Popup especifico del portal: "Habilitá tus tarjetas" / "Habilitar tarjetas"
        await self._dismiss_visa_popups()

        try:
            await self.page.locator(
                '#cardsDropDown, li.card-item.clearfix, button:has-text("Ver resumen")'
            ).first.wait_for(state="attached", timeout=self.config.timeout_ms)
        except PlaywrightTimeout:
            state = await self.page.evaluate(
                """() => ({
                    title: document.title,
                    body: (document.body?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 240),
                    url: location.href,
                })"""
            )
            raise DownloadError(
                "Visa no mostró los controles del dashboard. "
                f"URL: {state['url']}; título: {state['title']!r}; "
                f"contenido: {state['body']!r}"
            )

    async def _dismiss_visa_popups(self) -> None:
        """
        Cierra popups/modales especificos del portal Prisma que pueden bloquear
        la interaccion (ej: 'Habilitá tus tarjetas', banner de novedades, etc).
        Ejecuta todo en JS para evitar races con animaciones.
        """
        result = await self.page.evaluate(
            r"""() => {
                const log = [];
                // 1) Modal 'Habilitar Tarjetas' / 'Habilitá tus tarjetas'
                //    Suele ser un div con botones 'Cerrar', 'Más tarde', 'Omitir', etc.
                const TEXTS_CLOSE = [
                    'Más tarde', 'Mas tarde', 'Más Tarde',
                    'Omitir', 'Saltar', 'Cerrar',
                    'No, gracias', 'No gracias',
                    'Ahora no', 'Recordarme más tarde',
                    'Entendido', 'Aceptar y continuar'
                ];
                const clickables = Array.from(document.querySelectorAll('a, button, span, div'));
                for (const el of clickables) {
                    if (!(el.offsetParent)) continue;
                    const t = (el.textContent || '').trim();
                    if (TEXTS_CLOSE.includes(t) && t.length < 40) {
                        try { el.click(); log.push('cerrado_texto:' + t); }
                        catch (e) {}
                    }
                }
                // 2) Cruz de cierre (X) en modales
                const xBtns = Array.from(document.querySelectorAll(
                    '[aria-label="Cerrar"], [aria-label="Close"], ' +
                    '.modal .close, .modal-close, ' +
                    '.popup .close, .popup-close, ' +
                    'a.close-modal, button.close-modal, ' +
                    'a[onclick*="close"], div[onclick*="close"]'
                ));
                for (const x of xBtns) {
                    if (!x.offsetParent) continue;
                    try { x.click(); log.push('cerrado_x:' + (x.className || x.tagName)); }
                    catch (e) {}
                }
                // 3) Detectar si quedo algun overlay bloqueante
                const blockers = Array.from(document.querySelectorAll('*'))
                    .filter(el => {
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return (s.position === 'fixed')
                            && el.offsetParent !== null
                            && r.width > window.innerWidth * 0.5
                            && r.height > window.innerHeight * 0.3
                            && parseInt(s.zIndex || '0') > 100;
                    })
                    .slice(0, 3)
                    .map(el => ({
                        tag: el.tagName,
                        cls: (el.className || '').substring(0, 60),
                        text: (el.textContent || '').trim().substring(0, 80),
                    }));
                return { log, blockers };
            }"""
        )
        if result.get("log"):
            print(f"  [Visa] Popups cerrados: {result['log']}")
        if result.get("blockers"):
            print(f"  [Visa] Overlays residuales: {result['blockers']}")
        # Pausa breve para que el modal termine de cerrarse
        if result.get("log"):
            await asyncio.sleep(0.5)

    async def _navigate_to_resumen(self, account: Account) -> str:
        """
        Hace click en 'Ver Resumen' para el account dado.
        Si hay multiples tarjetas, primero selecciona la correcta.
        Retorna el periodo detectado (YYYY-MM).
        """
        # Si hay mas de una tarjeta, intentar seleccionar la correcta
        await self._card_selector.select_if_needed(account)

        clicked = await self._click_ver_resumen()
        if not clicked:
            await self._dump_dashboard_links()
            raise DownloadError(
                f"No se encontro el boton 'Resumen de Cuenta' para Visa ****{account.client_number}."
            )

        # El portal es jQuery/JSP: el contenido carga en la misma pagina via AJAX.
        # Esperamos networkidle + pausa extra para que el DOM se actualice.
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
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
        - <input type='submit' value='Ver resumen'>
        - <button type='submit'>Ver resumen</button>
        - <a href='#'>Ver Resumen completo</a>
        - o items de submenu dropit (ocultos hasta hover)

        Priorizamos el submit real; no hacemos click en contenedores de texto.
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

        # 1. El portal JSF renderiza el submit como input, no como button.
        submits = self.page.locator('input[type="submit"]')
        for index in range(await submits.count()):
            try:
                el = submits.nth(index)
                value = (await el.get_attribute("value") or "").strip()
                if "resumen" in value.lower() and await el.is_visible(timeout=400):
                    print(f"  [Visa] Click resumen via input submit: {value!r}")
                    await el.click()
                    return True
            except Exception:
                pass

        # 2. Buscar botones/enlaces accionables visibles.
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

        # 3. Fallback JS limitado a controles accionables para evitar falsos positivos.
        clicked = await self.page.evaluate(
            """(texts) => {
                const els = Array.from(document.querySelectorAll(
                    'a, button, input[type="submit"], [role="button"]'
                )).filter(el => el.offsetParent !== null);
                for (const text of texts) {
                    const match = els.find(e => {
                        const t = (e.value || e.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                        return t.includes(text.toLowerCase()) || t.includes(text.toLowerCase().replace(/\\s+/g, ''));
                    });
                    if (match) {
                        try {
                            match.click();
                            return text;
                        } catch (e) {
                            return text;
                        }
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

    async def _extract_period(self) -> str:
        return await extract_period(self.page)

    async def aclose(self) -> None:
        await self._download_strategies.aclose()
