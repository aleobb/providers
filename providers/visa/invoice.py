from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

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

    async def _select_card_if_needed(self, account: Account) -> None:
        """
        Selecciona la tarjeta indicada en el portal de mistarjetas.

        El portal muestra un panel lateral con <li class="card-item clearfix"> por
        cada tarjeta. El panel se abre haciendo click en el header (area del banco
        + numero activo). Los LI pasan de hidden a visible cuando el panel esta abierto.

        IMPORTANTE: los <li class="card-selection-div"> son de dropit.js para el
        menu "Mas..." (Estado de Cuenta / Resumen Anual) y NUNCA se muestran al
        usuario como selector de tarjetas. No usarlos para el switch.
        """
        last4 = account.client_number

        # Short-circuit: si la tarjeta activa ya es la buscada, no hace falta switchear
        if await self._active_card_matches(last4):
            print(f"  [Visa] Tarjeta activa ya es ****{last4} — sin switch.")
            return

        # Algunas respuestas del portal solo insertan las tarjetas al abrir el panel.
        await self._open_card_selector()
        await self._click_card_in_dropdown(last4)

        # Verificar que el switch ocurrio
        for _ in range(12):  # hasta 6s
            if await self._active_card_matches(last4):
                print(f"  [Visa] Switch confirmado: tarjeta activa = ****{last4}.")
                return
            await asyncio.sleep(0.5)
        raise DownloadError(
            f"Visa no confirmó el cambio a la tarjeta ****{last4}. "
            f"Tarjeta activa: {await self._active_card_number() or 'desconocida'}; "
            f"URL: {self.page.url}"
        )

    async def _active_card_number(self) -> str | None:
        try:
            return await self.page.evaluate(
                r"""() => {
                    const spans = Array.from(document.querySelectorAll('span'));
                    for (const span of spans) {
                        if (!span.offsetParent || span.closest('#cardContent')) continue;
                        const match = (span.textContent || '').match(/XXXX\s+XXXX\s+XXXX\s+(\d{4})/);
                        if (match) return match[1];
                    }
                    return null;
                }"""
            )
        except Exception:
            return None

    async def _active_card_matches(self, last4: str) -> bool:
        """
        Devuelve True si la tarjeta activa del header muestra los 4 digitos.

        CRITICO: NO usar .user-info.grid-7.omega ni similares — esos contenedores
        incluyen <script> con los 12 tokens que contienen todos los last4, causando
        falsos positivos para cualquier tarjeta.

        Usa el <span> visible con patron "XXXX XXXX XXXX NNNN" FUERA de #cardContent
        (el panel de seleccion). Ese span es unico y corresponde a la tarjeta activa.
        """
        try:
            active = await self.page.evaluate(
                r"""() => {
                    const spans = Array.from(document.querySelectorAll('span'));
                    for (const s of spans) {
                        if (!s.offsetParent) continue;
                        // Excluir cualquier span dentro de #cardContent (panel de seleccion)
                        let p = s;
                        let inPanel = false;
                        while (p) {
                            if (p.id === 'cardContent') { inPanel = true; break; }
                            p = p.parentElement;
                        }
                        if (inPanel) continue;
                        const m = (s.textContent || '').match(/XXXX\s+XXXX\s+XXXX\s+(\d{4})/);
                        if (m) return m[1];
                    }
                    return null;
                }"""
            )
            return active == last4
        except Exception:
            return False

    async def _open_card_selector(self) -> bool:
        """
        Abre el dropdown de seleccion de tarjeta.

        Estructura real (confirmada con DevTools):
          <div class="select-card" id="cardsDropDown" onclick="doOpenMenuCard()">
            | Banco  TARJETA N°: XXXX 3464
          </div>
          <div id="cardContent" class="card-toggler-efect" style="display:none">
            <ul class="card-dropdown-menu">
              <li class="card-item clearfix">...</li>
              ...
            </ul>
          </div>

        Cuando el dropdown esta abierto:
          - #cardsDropDown muestra 'Seleccione otra tarjeta' y tiene onclick="doCloseMenuCard()"
          - #cardContent tiene style="display:block"
          - los li.card-item.clearfix son visibles
        """
        # Si ya esta abierto (cardContent visible), no hacer nada
        try:
            already_open = await self.page.locator('#cardContent').is_visible(timeout=300)
            if already_open:
                print("  [Visa] Panel de tarjetas ya estaba abierto.")
                return True
        except Exception:
            pass

        # Trigger: div#cardsDropDown (identificado por DevTools)
        trigger_selectors = [
            '#cardsDropDown',          # ID exacto del trigger
            'div.select-card',         # clase del trigger
            '.user-select-card-number div',  # contenedor del trigger
        ]
        for sel in trigger_selectors:
            try:
                el = self.page.locator(sel).first
                if await el.count() > 0 and await el.is_visible(timeout=500):
                    await el.click()
                    await asyncio.sleep(0.5)
                    # Verificar apertura: #cardContent visible o li.card-item.clearfix visible
                    opened = await self.page.locator('#cardContent').is_visible(timeout=1000)
                    if not opened:
                        opened = await self.page.locator('li.card-item.clearfix').first.is_visible(timeout=500)
                    if opened:
                        print(f"  [Visa] Panel de tarjetas abierto via ({sel})")
                        return True
                    print(f"  [Visa] Click en {sel} pero panel no se abrio, probando siguiente...")
            except Exception:
                pass

        print("  [Visa] No se pudo abrir el panel de tarjetas.")
        return False

    async def _click_card_in_dropdown(self, last4: str) -> None:
        """
        Cambia la tarjeta activa llamando directamente a la funcion JSF del portal.

        Estructura confirmada por debug dump:
          <li class="card-item clearfix"
              onclick="changeCard('<token_base64>')">
            ...XXXX XXXX XXXX 3464...
          </li>

        `changeCard(token)` es una funcion global que setea el hidden input
        `header:cardSelectorFrm:selectedCardHidden` y submit-ea el form JSF
        `header:cardSelectorFrm`. La pagina recarga con la tarjeta nueva activa.

        Estrategia preferida: leer el onclick del LI correcto y ejecutar
        directamente `changeCard(token)`. Fallback: Playwright click sobre el LI.
        """
        # 1) Preferente: extraer token del onclick y llamar changeCard(token)
        call_result = await self.page.evaluate(
            r"""(last4) => {
                const lis = Array.from(document.querySelectorAll('li.card-item.clearfix'));
                const target = lis.find(li => (li.textContent || '').includes(last4));
                if (!target) return { ok: false, reason: 'no_li_match' };
                const oc = target.getAttribute('onclick') || '';
                // onclick = "changeCard('TOKEN')"
                const m = oc.match(/changeCard\(\s*['"]([^'"]+)['"]\s*\)/);
                if (m && typeof window.changeCard === 'function') {
                    try {
                        window.changeCard(m[1]);
                        return { ok: true, via: 'changeCard', token: m[1].substring(0, 20) + '...' };
                    } catch (e) {
                        return { ok: false, reason: 'changeCard_err:' + e.message };
                    }
                }
                // Fallback: ejecutar el onclick raw
                if (oc) {
                    try {
                        (new Function(oc)).call(target);
                        return { ok: true, via: 'onclick_raw' };
                    } catch (e) {
                        return { ok: false, reason: 'onclick_err:' + e.message };
                    }
                }
                return { ok: false, reason: 'sin_onclick' };
            }""",
            last4,
        )
        print(f"  [Visa] changeCard({last4}): {call_result}")

        if call_result.get("ok"):
            # El form submit hace una navegacion — esperar recarga del dashboard
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(0.8)
            await dismiss_popups(self.page, label="visa-card-switch")
            return

        # 2) Fallback: Playwright click sobre cualquier elemento visible que contenga el 4digito
        # (por si la estructura cambio o no hay li.card-item.clearfix en el DOM)
        print(f"  [Visa] Fallback a Playwright click por texto visible...")
        for locator_str in [
            'li.card-item.clearfix',
            '#cardContent li.card-item.clearfix',
            'ul.card-dropdown-menu li.card-item',
            'button, a, div, span, li',
        ]:
            items = self.page.locator(locator_str)
            count = await items.count()
            if count == 0:
                continue
            for i in range(min(count, 200)):
                item = items.nth(i)
                try:
                    text = (await item.text_content()) or ''
                    if last4 not in text:
                        continue
                    # Evitar elementos ocultos / no clickeables
                    if not await item.is_visible(timeout=800):
                        continue
                    await item.click(timeout=3000, force=True)
                    print(f"  [Visa] Click Playwright fallback '{locator_str}' ****{last4}")
                    try:
                        await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    await asyncio.sleep(0.8)
                    await dismiss_popups(self.page, label="visa-card-switch-pw")
                    return
                except Exception as e:
                    print(f"  [Visa] Playwright click error fallback [{locator_str}][{i}]: {e}")
            break

        # 3) Ultimo recurso: buscar por texto visible usando JS y hacer click directamente
        clicked = await self.page.evaluate(
            r"""(last4) => {
                const candidates = Array.from(document.querySelectorAll('button, a, div, span, li'));
                for (const el of candidates) {
                    if (!el || !el.isConnected) continue;
                    const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
                    if (!t.includes(last4)) continue;
                    try {
                        el.click();
                        return { ok: true, tag: el.tagName, text: t.slice(0, 120) };
                    } catch (e) {
                        return { ok: false, reason: String(e) };
                    }
                }
                return { ok: false, reason: 'no_clickable_target' };
            }""",
            last4,
        )
        print(f"  [Visa] Fallback JS por texto: {clicked}")
        if clicked.get("ok"):
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(0.8)
            await dismiss_popups(self.page, label="visa-card-switch-js")
            return

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
        # El portal puede renderizar la accion como enlace, boton o submit.
        clickables = self.page.locator(
            'a, button, input[type="button"], input[type="submit"], '
            '[role="button"], [onclick]'
        )
        for index in range(await clickables.count()):
            try:
                el = clickables.nth(index)
                if not await el.is_visible(timeout=300):
                    continue
                label = " ".join(filter(None, [
                    await el.text_content(),
                    await el.get_attribute("value"),
                    await el.get_attribute("title"),
                    await el.get_attribute("aria-label"),
                ])).strip().lower()
                if not re.search(r"descarg|imprim|pdf", label):
                    continue
                print(f"  [Visa] Click descarga en control: {label[:100]!r}")
                await el.click()
                return
            except Exception:
                pass

        # El resumen puede estar embebido y no ofrecer un control de descarga.
        embedded_pdf = await self._find_pdf_link_in_dom()
        if embedded_pdf:
            print(f"  [Visa] PDF embebido detectado: {embedded_pdf}")
            return

        # Si no encontramos una accion, volcar los controles y links para diagnostico.
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
        """Busca links o visores embebidos que apunten al PDF del resumen."""
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
        except Exception as e:
            print(f"  [Visa] Error buscando links PDF: {e}")
        return None

    # ------------------------------------------------------------------ helpers

    async def _extract_period(self) -> str:
        """
        Extrae el período del resumen desde el texto de la página.

        Intenta obtener YYYY-MM-DD (fecha de cierre completa) buscando patrones
        del tipo "Fecha de Cierre: DD/MM/YYYY" o "F. Cierre DD-MM-YYYY".
        Si no la encuentra, cae a YYYY-MM.
        """
        try:
            text = await self.page.inner_text("body")

            # --- Intentar fecha de cierre completa (DD/MM/YYYY o DD-MM-YYYY) ---
            cierre_patterns = [
                r'fecha\s+de\s+cierre\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})',
                r'f\.?\s*cierre\s*[:\-]?\s*(\d{2})[/\-](\d{2})[/\-](\d{4})',
                r'cierre\s*[:\-]\s*(\d{2})[/\-](\d{2})[/\-](\d{4})',
            ]
            for pat in cierre_patterns:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    day, month, year = m.group(1), m.group(2), m.group(3)
                    return f"{year}-{month}-{day}"

            # --- Fallback: nombre de mes + año ---
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
