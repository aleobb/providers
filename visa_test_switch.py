"""
Test aislado del switch de tarjetas Visa.

Restaura sesion guardada, toma screenshot del estado inicial, intenta
cambiar a otra tarjeta, y toma screenshot del resultado.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

from providers.visa.config import VisaConfig

DUMP_DIR = Path(__file__).parent / "visa_switch_test"
DUMP_DIR.mkdir(exist_ok=True)


async def take_shot(page, name: str) -> Path:
    path = DUMP_DIR / f"{name}.png"
    await page.screenshot(path=str(path), full_page=False)
    print(f"  [shot] {path}")
    return path


async def header_text(page) -> str:
    """
    Extrae SOLO los 4 digitos de la tarjeta activa del header.
    Evita leer el innerText de containers que incluyen <script>.
    """
    try:
        return await page.evaluate(
            r"""() => {
                // El hidden input del form JSF guarda el token de la tarjeta activa
                const hidden = document.getElementById('header:cardSelectorFrm:selectedCardHidden');
                const hiddenVal = hidden ? hidden.value : '';
                // El <span> con los 4 digitos visibles en el header esta fuera de #cardContent
                const spans = Array.from(document.querySelectorAll('span'))
                    .filter(s => {
                        if (!s.offsetParent) return false;
                        // Excluir los que estan dentro del panel de seleccion
                        let p = s;
                        while (p) {
                            if (p.id === 'cardContent') return false;
                            p = p.parentElement;
                        }
                        return /XXXX\s+XXXX\s+XXXX\s+\d{4}/.test(s.textContent || '');
                    })
                    .map(s => (s.textContent || '').replace(/\s+/g, ' ').trim());
                return JSON.stringify({ visible_spans: spans, hiddenToken: hiddenVal.substring(0, 40) });
            }"""
        )
    except Exception as e:
        return f"(err: {e})"


async def active_last4(page) -> str | None:
    """Devuelve los 4 digitos de la tarjeta activa mostrada en el header."""
    try:
        return await page.evaluate(
            r"""() => {
                // Buscar spans visibles con patron XXXX XXXX XXXX NNNN fuera de #cardContent
                const spans = Array.from(document.querySelectorAll('span'));
                for (const s of spans) {
                    if (!s.offsetParent) continue;
                    let p = s;
                    let inPanel = false;
                    while (p) { if (p.id === 'cardContent') { inPanel = true; break; } p = p.parentElement; }
                    if (inPanel) continue;
                    const m = (s.textContent || '').match(/XXXX\s+XXXX\s+XXXX\s+(\d{4})/);
                    if (m) return m[1];
                }
                return null;
            }"""
        )
    except Exception:
        return None


async def list_cards(page) -> list[dict]:
    return await page.evaluate(
        r"""() => {
            return Array.from(document.querySelectorAll('li.card-item.clearfix'))
                .map(li => {
                    const oc = li.getAttribute('onclick') || '';
                    const m = oc.match(/changeCard\(\s*['"]([^'"]+)['"]\s*\)/);
                    const last4Match = (li.textContent || '').match(/(\d{4})(?:\s|$)/);
                    return {
                        last4: last4Match ? last4Match[1] : '????',
                        token: m ? m[1] : '',
                        text: (li.textContent || '').replace(/\s+/g, ' ').trim().substring(0, 80),
                    };
                });
        }"""
    )


async def main():
    config = VisaConfig()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context()
        page = await context.new_page()

        if config.session_file.exists():
            data = json.loads(config.session_file.read_text(encoding="utf-8"))
            await context.add_cookies(data.get("cookies", []))
            await page.goto(config.portal_url, timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            if "login" in page.url.lower() or "mycards" in page.url.lower():
                print("[WARN] Sesion expirada. Logueate manualmente.")
                await page.goto("https://mycards.prismamediosdepago.com/", timeout=30000)
                input("Presiona ENTER una vez que estes en el dashboard... ")
        else:
            print("[INFO] Sin sesion guardada. Logueate manualmente en el browser.")
            await page.goto("https://mycards.prismamediosdepago.com/", timeout=30000)
            input("Presiona ENTER una vez que estes en el dashboard... ")
            # Guardar cookies para reutilizar
            cookies = await context.cookies()
            config.session_file.write_text(
                json.dumps({"cookies": cookies}, indent=2), encoding="utf-8"
            )
            print(f"[INFO] Sesion guardada en {config.session_file}")
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(1.5)

        print(f"\nURL: {page.url}")
        initial_last4 = await active_last4(page)
        print(f"Header activo: ****{initial_last4}")
        print(f"Header debug: {await header_text(page)}")
        await take_shot(page, "01_initial")

        cards = await list_cards(page)
        print(f"\nTarjetas detectadas ({len(cards)}):")
        for c in cards:
            print(f"  ****{c['last4']}  token={c['token'][:30]}...")

        # Elegir una tarjeta DISTINTA a la que este activa
        target = None
        for c in cards:
            if c["last4"] != initial_last4 and c["token"]:
                target = c
                break

        if not target:
            print("[ERROR] No encontre una tarjeta distinta para probar switch.")
            await browser.close()
            return

        print(f"\n>>> Switcheando a ****{target['last4']} via changeCard('{target['token'][:20]}...')")

        # Detectar modales bloqueantes
        blockers = await page.evaluate(
            r"""() => Array.from(document.querySelectorAll('*'))
                .filter(el => {
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.position === 'fixed'
                        && el.offsetParent !== null
                        && r.width > 300 && r.height > 200
                        && parseInt(s.zIndex || '0') > 100;
                })
                .slice(0, 5)
                .map(el => ({
                    tag: el.tagName,
                    cls: (el.className || '').substring(0, 80),
                    text: (el.textContent || '').trim().substring(0, 120),
                }));
            """
        )
        print(f"\nModales bloqueantes antes del switch: {blockers}")

        # Llamar changeCard directamente
        call = await page.evaluate(
            r"""(token) => {
                if (typeof window.changeCard !== 'function') {
                    return { ok: false, reason: 'no_changeCard_fn' };
                }
                try {
                    window.changeCard(token);
                    return { ok: true };
                } catch (e) {
                    return { ok: false, reason: e.message };
                }
            }""",
            target["token"],
        )
        print(f"changeCard() -> {call}")

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(2.0)

        final_last4 = await active_last4(page)
        print(f"\nHeader activo final: ****{final_last4}")
        print(f"Switch OK? {final_last4 == target['last4']}")
        print(f"Header debug: {await header_text(page)}")
        await take_shot(page, "02_after_switch")

        print("\nListo. Screenshots en:", DUMP_DIR)
        await browser.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
        loop.close()
    else:
        asyncio.run(main())
