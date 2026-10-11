from __future__ import annotations

import asyncio

from core.accounts import Account
from core.exceptions import DownloadError
from core.utils import dismiss_popups
from playwright.async_api import Page


class CardSelector:
    """Selects the active Visa card in the Prisma dashboard."""

    def __init__(self, page: Page):
        self.page = page

    async def select_if_needed(self, account: Account) -> None:
        last4 = account.client_number
        if await self._active_card_matches(last4):
            print(f"  [Visa] Tarjeta activa ya es ****{last4} — sin switch.")
            return

        await self._open_card_selector()
        await self._click_card_in_dropdown(last4)

        for _ in range(12):
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
        try:
            active = await self.page.evaluate(
                r"""() => {
                    const spans = Array.from(document.querySelectorAll('span'));
                    for (const s of spans) {
                        if (!s.offsetParent) continue;
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
        try:
            already_open = await self.page.locator("#cardContent").is_visible(
                timeout=300
            )
            if already_open:
                print("  [Visa] Panel de tarjetas ya estaba abierto.")
                return True
        except Exception:
            pass

        trigger_selectors = [
            "#cardsDropDown",
            "div.select-card",
            ".user-select-card-number div",
        ]
        for selector in trigger_selectors:
            try:
                element = self.page.locator(selector).first
                if await element.count() > 0 and await element.is_visible(timeout=500):
                    await element.click()
                    await asyncio.sleep(0.5)
                    opened = await self.page.locator("#cardContent").is_visible(
                        timeout=1000
                    )
                    if not opened:
                        opened = await self.page.locator(
                            "li.card-item.clearfix"
                        ).first.is_visible(timeout=500)
                    if opened:
                        print(
                            f"  [Visa] Panel de tarjetas abierto via ({selector})"
                        )
                        return True
                    print(
                        f"  [Visa] Click en {selector} pero panel no se abrio, "
                        "probando siguiente..."
                    )
            except Exception:
                pass

        print("  [Visa] No se pudo abrir el panel de tarjetas.")
        return False

    async def _click_card_in_dropdown(self, last4: str) -> None:
        call_result = await self.page.evaluate(
            r"""(last4) => {
                const lis = Array.from(document.querySelectorAll('li.card-item.clearfix'));
                const target = lis.find(li => (li.textContent || '').includes(last4));
                if (!target) return { ok: false, reason: 'no_li_match' };
                const oc = target.getAttribute('onclick') || '';
                const m = oc.match(/changeCard\(\s*['"]([^'"]+)['"]\s*\)/);
                if (m && typeof window.changeCard === 'function') {
                    try {
                        window.changeCard(m[1]);
                        return { ok: true, via: 'changeCard', token: m[1].substring(0, 20) + '...' };
                    } catch (e) {
                        return { ok: false, reason: 'changeCard_err:' + e.message };
                    }
                }
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
            try:
                await self.page.wait_for_load_state(
                    "domcontentloaded", timeout=10000
                )
            except Exception:
                pass
            await asyncio.sleep(0.8)
            await dismiss_popups(self.page, label="visa-card-switch")
            return

        print("  [Visa] Fallback a Playwright click por texto visible...")
        for locator_str in [
            "li.card-item.clearfix",
            "#cardContent li.card-item.clearfix",
            "ul.card-dropdown-menu li.card-item",
            "button, a, div, span, li",
        ]:
            items = self.page.locator(locator_str)
            count = await items.count()
            if count == 0:
                continue
            for index in range(min(count, 200)):
                item = items.nth(index)
                try:
                    text = (await item.text_content()) or ""
                    if last4 not in text:
                        continue
                    if not await item.is_visible(timeout=800):
                        continue
                    await item.click(timeout=3000, force=True)
                    print(
                        f"  [Visa] Click Playwright fallback "
                        f"'{locator_str}' ****{last4}"
                    )
                    try:
                        await self.page.wait_for_load_state(
                            "domcontentloaded", timeout=10000
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(0.8)
                    await dismiss_popups(
                        self.page, label="visa-card-switch-pw"
                    )
                    return
                except Exception as error:
                    print(
                        f"  [Visa] Playwright click error fallback "
                        f"[{locator_str}][{index}]: {error}"
                    )
            break

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
                await self.page.wait_for_load_state(
                    "domcontentloaded", timeout=10000
                )
            except Exception:
                pass
            await asyncio.sleep(0.8)
            await dismiss_popups(self.page, label="visa-card-switch-js")
