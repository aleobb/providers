"""
Script de sesion de debug para el portal Visa/Prisma.

Uso:
    python visa_debug_session.py

Abre el portal en un browser visible. En cada paso presiona ENTER en la terminal
y el script vuelca el estado del DOM en dump_step_XX.txt para diagnostico.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

from providers.visa.config import VisaConfig

DUMP_DIR = Path(__file__).parent / "visa_debug_dumps"
DUMP_DIR.mkdir(exist_ok=True)

_STEP = 0


async def dump_state(page, label: str) -> None:
    global _STEP
    _STEP += 1
    fname = DUMP_DIR / f"step_{_STEP:02d}_{label}.txt"

    lines = []
    lines.append(f"=== URL: {page.url} ===")

    # Todos los links visibles
    links = await page.evaluate(r"""() => {
        return Array.from(document.querySelectorAll('a'))
            .filter(a => a.offsetParent !== null)
            .slice(0, 60)
            .map(a => ({
                text: (a.textContent || '').trim().substring(0, 80),
                href: a.getAttribute('href') || '',
                cls:  a.className || '',
            }));
    }""")
    lines.append("\n--- LINKS VISIBLES ---")
    for l in links:
        lines.append(f"  <a href={l['href']!r} class={l['cls']!r}> {l['text']!r}")

    # Todos los botones visibles
    btns = await page.evaluate(r"""() => {
        return Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]'))
            .filter(b => b.offsetParent !== null)
            .slice(0, 40)
            .map(b => ({
                text: (b.textContent || b.value || '').trim().substring(0, 80),
                cls:  b.className || '',
                type: b.type || '',
            }));
    }""")
    lines.append("\n--- BOTONES VISIBLES ---")
    for b in btns:
        lines.append(f"  <button type={b['type']!r} class={b['cls']!r}> {b['text']!r}")

    # LIs del selector de tarjetas (visibles o no)
    card_lis = await page.evaluate(r"""() => {
        return Array.from(document.querySelectorAll('li'))
            .filter(li => /card|tarjeta|\d{4}/i.test(li.className + li.textContent))
            .slice(0, 20)
            .map(li => ({
                cls:     li.className || '',
                text:    li.textContent.trim().substring(0, 120),
                visible: li.offsetParent !== null,
            }));
    }""")
    lines.append("\n--- LIs con 'card' o numero ---")
    for li in card_lis:
        vis = "V" if li["visible"] else "H"
        lines.append(f"  [{vis}] <li class={li['cls']!r}> {li['text']!r}")

    # HTML completo del dropdown cuando esta abierto (dropit-open)
    dropdown_html = await page.evaluate(r"""() => {
        // Buscar el UL del dropdown: dropit-menu, o UL dentro del trigger
        const openLi = document.querySelector('li.dropit-open, li.dropit-trigger.dropit-open, li.dropit-trigger');
        if (!openLi) return { found: false };
        const ul = openLi.querySelector('ul');
        if (!ul) return { found: true, html: openLi.outerHTML.substring(0, 3000) };
        return {
            found: true,
            dropitOpen: openLi.classList.contains('dropit-open'),
            ulCls: ul.className,
            ulDisplay: window.getComputedStyle(ul).display,
            ulVisibility: window.getComputedStyle(ul).visibility,
            ulItems: Array.from(ul.querySelectorAll('li')).map(li => ({
                cls: li.className,
                display: window.getComputedStyle(li).display,
                visible: li.offsetParent !== null,
                text: li.textContent.trim().substring(0, 100),
                hasA: li.querySelector('a') ? true : false,
                aHref: li.querySelector('a') ? li.querySelector('a').getAttribute('href') : '',
                onclick: li.getAttribute('onclick') || '',
            })),
            triggerA: openLi.querySelector(':scope > a') ? {
                text: openLi.querySelector(':scope > a').textContent.trim().substring(0, 60),
                href: openLi.querySelector(':scope > a').getAttribute('href'),
                cls:  openLi.querySelector(':scope > a').className,
            } : null,
        };
    }""")
    lines.append("\n--- DROPDOWN DROPIT (estructura interna) ---")
    if dropdown_html.get("found"):
        lines.append(f"  dropit-open: {dropdown_html.get('dropitOpen')}")
        lines.append(f"  ul.class: {dropdown_html.get('ulCls')!r}  display={dropdown_html.get('ulDisplay')!r}  visibility={dropdown_html.get('ulVisibility')!r}")
        trigger_a = dropdown_html.get("triggerA")
        if trigger_a:
            lines.append(f"  trigger <a>: text={trigger_a['text']!r} href={trigger_a['href']!r} cls={trigger_a['cls']!r}")
        for item in (dropdown_html.get("ulItems") or []):
            vis = "V" if item["visible"] else "H"
            lines.append(f"  [{vis}] <li cls={item['cls']!r} display={item['display']!r} hasA={item['hasA']} onclick={item['onclick']!r}> {item['text']!r}")
    else:
        lines.append("  (no se encontro li.dropit-trigger)")

    # jQuery event handlers del trigger (si jQuery esta disponible)
    jquery_events = await page.evaluate(r"""() => {
        if (typeof $ === 'undefined' && typeof jQuery === 'undefined') return { noJQ: true };
        const jq = typeof $ !== 'undefined' ? $ : jQuery;
        const trigger = jq('li.dropit-trigger');
        if (!trigger.length) return { noTrigger: true };
        const events = jq._data ? jq._data(trigger[0], 'events') : null;
        const triggerA = trigger.find('> a');
        const aEvents = triggerA.length && jq._data ? jq._data(triggerA[0], 'events') : null;
        return {
            liEvents: events ? Object.keys(events) : [],
            aEvents: aEvents ? Object.keys(aEvents) : [],
            hasDropit: typeof jq.fn.dropit !== 'undefined',
        };
    }""")
    lines.append("\n--- JQUERY EVENTS en dropit-trigger ---")
    if jquery_events.get("noJQ"):
        lines.append("  jQuery no disponible")
    else:
        lines.append(f"  li events: {jquery_events.get('liEvents')}")
        lines.append(f"  a  events: {jquery_events.get('aEvents')}")
        lines.append(f"  dropit plugin: {jquery_events.get('hasDropit')}")

    # Inspeccion profunda del primer li.card-item.clearfix (estructura, handlers, form)
    card_item_info = await page.evaluate(r"""() => {
        const lis = Array.from(document.querySelectorAll('li.card-item.clearfix'));
        if (!lis.length) return { found: false };
        const sample = lis[0];
        let form = sample.closest('form');
        const jq = (typeof $ !== 'undefined') ? $ : (typeof jQuery !== 'undefined' ? jQuery : null);
        const events = (jq && jq._data) ? jq._data(sample, 'events') : null;
        // funciones globales que parezcan selectores de tarjeta
        const fns = Object.keys(window).filter(k => {
            try {
                return typeof window[k] === 'function'
                    && /card|tarjet|select|switch|change/i.test(k);
            } catch(e) { return false; }
        }).slice(0, 30);
        // hijos directos del li para ver <a>, <input>, etc
        const kids = Array.from(sample.children).map(c => ({
            tag: c.tagName,
            cls: c.className || '',
            onclick: c.getAttribute('onclick') || '',
            href: c.tagName === 'A' ? c.getAttribute('href') : '',
            name: c.getAttribute('name') || '',
            value: c.tagName === 'INPUT' ? c.value : '',
        }));
        return {
            found: true,
            total: lis.length,
            cls: sample.className,
            onclick: sample.getAttribute('onclick') || '',
            dataAttrs: Array.from(sample.attributes)
                .filter(a => a.name.startsWith('data-') || a.name === 'id' || a.name === 'name')
                .map(a => `${a.name}=${a.value}`),
            innerHTMLSample: sample.outerHTML.substring(0, 800),
            jqEvents: events ? Object.keys(events) : [],
            form: form ? {
                id: form.id,
                name: form.getAttribute('name') || '',
                action: form.getAttribute('action') || '',
                method: form.getAttribute('method') || '',
                hiddenInputs: Array.from(form.querySelectorAll('input[type=hidden]'))
                    .slice(0, 15)
                    .map(i => ({ name: i.name, value: i.value })),
            } : null,
            children: kids,
            globalFns: fns,
        };
    }""")
    lines.append("\n--- li.card-item.clearfix (estructura interna) ---")
    if card_item_info.get("found"):
        lines.append(f"  total: {card_item_info['total']}  cls: {card_item_info['cls']!r}")
        lines.append(f"  onclick: {card_item_info['onclick']!r}")
        lines.append(f"  data/id/name: {card_item_info['dataAttrs']}")
        lines.append(f"  jQuery events: {card_item_info['jqEvents']}")
        form = card_item_info.get("form")
        if form:
            lines.append(f"  FORM parent: id={form['id']!r} name={form['name']!r} action={form['action']!r} method={form['method']!r}")
            for hi in form["hiddenInputs"]:
                lines.append(f"    <input type=hidden name={hi['name']!r} value={hi['value']!r}>")
        else:
            lines.append("  (sin <form> padre)")
        lines.append("  children:")
        for c in card_item_info["children"]:
            lines.append(f"    <{c['tag']} cls={c['cls']!r} onclick={c['onclick']!r} href={c['href']!r} name={c['name']!r} value={c['value']!r}>")
        lines.append(f"  globalFns (card/select/switch): {card_item_info['globalFns']}")
        lines.append(f"  outerHTML[:800]:\n    {card_item_info['innerHTMLSample']}")
    else:
        lines.append("  (no hay li.card-item.clearfix en DOM)")

    # Modales / overlays activos (role=dialog, .modal, posicion fixed)
    modals = await page.evaluate(r"""() => {
        const fixed = Array.from(document.querySelectorAll('*'))
            .filter(el => {
                const s = window.getComputedStyle(el);
                return (s.position === 'fixed' || s.position === 'absolute')
                    && el.offsetParent !== null
                    && el.getBoundingClientRect().width > 100
                    && el.getBoundingClientRect().height > 50
                    && parseInt(s.zIndex || '0') > 10;
            })
            .slice(0, 10)
            .map(el => ({
                tag:    el.tagName,
                cls:    el.className || '',
                role:   el.getAttribute('role') || '',
                zIndex: window.getComputedStyle(el).zIndex,
                text:   el.textContent.trim().substring(0, 120),
                w:      Math.round(el.getBoundingClientRect().width),
                h:      Math.round(el.getBoundingClientRect().height),
            }));
        return fixed;
    }""")
    lines.append("\n--- OVERLAYS / MODALES (fixed/absolute z>10) ---")
    if modals:
        for m in modals:
            lines.append(f"  <{m['tag']} role={m['role']!r} class={m['cls']!r} z={m['zIndex']} {m['w']}x{m['h']}> {m['text']!r}")
    else:
        lines.append("  (ninguno)")

    # Elemento con texto 'Salir' o 'Cerrar sesion' (visible o no)
    salir = await page.evaluate(r"""() => {
        const TEXTS = ['Salir', 'salir', 'SALIR', 'Cerrar sesi\u00f3n', 'Cerrar sesion'];
        return Array.from(document.querySelectorAll('a, button'))
            .filter(el => TEXTS.some(t => (el.textContent || '').trim() === t))
            .map(el => ({
                tag:     el.tagName,
                text:    (el.textContent || '').trim(),
                href:    el.getAttribute('href') || '',
                cls:     el.className || '',
                visible: el.offsetParent !== null,
                parent:  el.parentElement ? (el.parentElement.className || el.parentElement.tagName) : '',
            }));
    }""")
    lines.append("\n--- ELEMENTOS 'Salir' / 'Cerrar sesion' ---")
    if salir:
        for s in salir:
            vis = "V" if s["visible"] else "H"
            lines.append(f"  [{vis}] <{s['tag']} href={s['href']!r} class={s['cls']!r} parent={s['parent']!r}> {s['text']!r}")
    else:
        lines.append("  (no encontrado)")

    # Input selector de tarjetas (boton 'Seleccione otra tarjeta')
    sel_btn = await page.evaluate(r"""() => {
        const targets = ['Seleccione otra tarjeta', 'otra tarjeta', 'Seleccione'];
        return Array.from(document.querySelectorAll('input, button, a, div, span'))
            .filter(el => targets.some(t => (el.value || el.textContent || '').includes(t)))
            .slice(0, 5)
            .map(el => ({
                tag:     el.tagName,
                text:    (el.value || el.textContent || '').trim().substring(0, 80),
                cls:     el.className || '',
                type:    el.type || '',
                visible: el.offsetParent !== null,
            }));
    }""")
    lines.append("\n--- BOTON 'Seleccione otra tarjeta' ---")
    if sel_btn:
        for b in sel_btn:
            vis = "V" if b["visible"] else "H"
            lines.append(f"  [{vis}] <{b['tag']} type={b['type']!r} class={b['cls']!r}> {b['text']!r}")
    else:
        lines.append("  (no encontrado)")

    # Numero enmascarado de la tarjeta ACTIVA (fuera del selector)
    active_card = await page.evaluate(r"""() => {
        const pat = /[X*x\u2022]{4}[\s\xa0-]*(\d{4})/g;
        const selLis = new Set(document.querySelectorAll(
            'li.card-selection-div, li[class*="card-selection"], li[class*="card-item"]'
        ));
        const results = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
        let node;
        while ((node = walker.nextNode())) {
            const text = node.textContent || '';
            let m;
            while ((m = pat.exec(text)) !== null) {
                let el = node.parentElement;
                let inSel = false;
                while (el) {
                    if (selLis.has(el)) { inSel = true; break; }
                    el = el.parentElement;
                }
                if (!inSel) {
                    results.push({
                        last4:   m[1],
                        context: text.trim().substring(0, 80),
                    });
                }
            }
        }
        return results;
    }""")
    lines.append("\n--- TARJETA ACTIVA en dashboard (fuera del selector) ---")
    if active_card:
        for c in active_card:
            lines.append(f"  ****{c['last4']}: {c['context']!r}")
    else:
        lines.append("  (no detectada)")

    output = "\n".join(lines)
    fname.write_text(output, encoding="utf-8")
    print(f"\n[DUMP] {fname.name}")
    print(f"  URL: {page.url}")
    if active_card:
        print(f"  Tarjeta activa: {[c['last4'] for c in active_card]}")
    if salir:
        for s in salir:
            vis = "V" if s["visible"] else "H"
            print(f"  Salir [{vis}]: href={s['href']!r} cls={s['cls']!r}")


async def main():
    config = VisaConfig()

    print("=" * 60)
    print("  SESION DE DEBUG - PORTAL VISA/PRISMA")
    print("=" * 60)
    print()
    print("Se abre el browser. Navega manualmente.")
    print("Presiona ENTER en esta terminal para hacer un dump del DOM.")
    print("Escribe 'q' + ENTER para terminar.")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
        )
        context = await browser.new_context()
        page = await context.new_page()

        # Intentar restaurar sesion guardada para saltear login + OTP
        session_restored = False
        if config.session_file.exists():
            print("Encontre sesion guardada, intentando restaurarla...")
            try:
                data = json.loads(config.session_file.read_text(encoding="utf-8"))
                cookies = data.get("cookies", [])
                if cookies:
                    await context.add_cookies(cookies)
                    await page.goto(config.portal_url, timeout=30000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    url = page.url
                    if "mistarjetas" in url and "/app/" in url and "login" not in url.lower():
                        print(f"Sesion restaurada! Dashboard: {url}")
                        session_restored = True
                    else:
                        print(f"Sesion expirada ({url}). Vas a tener que loguearte.")
                        await context.clear_cookies()
            except Exception as e:
                print(f"Error restaurando sesion: {e}")

        if not session_restored:
            await page.goto("https://mycards.prismamediosdepago.com/", timeout=30000)
            print(f"Browser abierto en login: {page.url}")
            print("Loga manualmente (incluido OTP). Una vez en el dashboard, presiona ENTER.")
        else:
            print("Ya estas en el dashboard. Presiona ENTER para el primer dump.")

        print()
        print("Instrucciones de grabacion (a partir del dashboard):")
        print("  ENTER [etiqueta] -> vuelca el DOM con esa etiqueta")
        print("  Sugerencias de pasos:")
        print("    - ENTER 'dashboard'          (en el home con la tarjeta default)")
        print("    - ENTER 'selector_abierto'   (despues de click en 'Seleccione otra tarjeta')")
        print("    - ENTER 'tarjeta_cambiada'   (despues de click en una tarjeta distinta)")
        print("    - ENTER 'popup'              (si aparece popup de habilitacion)")
        print("    - ENTER 'resumen'            (en la pagina de resumen)")
        print("    - ENTER 'menu_usuario'       (con el menu de usuario desplegado)")
        print("    - ENTER 'salir'              (antes/despues de hacer click en Salir)")
        print()

        loop = asyncio.get_event_loop()

        while True:
            # Leer input de forma no-blocking
            try:
                cmd = await loop.run_in_executor(None, input, "ENTER=dump / q=salir > ")
            except (EOFError, KeyboardInterrupt):
                break

            if cmd.strip().lower() == "q":
                break

            # Etiqueta descriptiva opcional
            label = cmd.strip().replace(" ", "_") if cmd.strip() else "step"
            try:
                await dump_state(page, label)
            except Exception as e:
                print(f"  Error en dump: {e}")

        await browser.close()
        print()
        print(f"Dumps guardados en: {DUMP_DIR}")
        print(f"Total: {_STEP} dumps")


if __name__ == "__main__":
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
        loop.close()
    else:
        asyncio.run(main())
