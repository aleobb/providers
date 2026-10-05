from __future__ import annotations

import asyncio
import re

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from .config import VisaConfig
from .interceptor import NetworkInterceptor


async def fetch_accounts(
    page: Page,
    context: BrowserContext,
    interceptor: NetworkInterceptor,
    config: VisaConfig,
) -> list[Account]:
    """
    Obtiene las tarjetas del portal de Visa/Prisma donde el titular coincide
    con VISA_TITULAR (si esta configurado).

    Estrategia 1: parsear responses de la API capturadas por el interceptor.
    Estrategia 2: leer el DOM del dashboard.
    Fallback: cuenta unica identificada por DNI.
    """
    # Asegurar que estamos en el dashboard
    if "mistarjetas" not in page.url:
        await page.goto(config.portal_url, timeout=config.timeout_ms)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=config.timeout_ms)
        except Exception:
            pass
        await asyncio.sleep(3)

    await _close_popup(page)
    print(f"  [Visa] Dashboard: {page.url}")

    # --- Estrategia 1: datos del interceptor de red ---
    accounts = _parse_from_interceptor(interceptor)

    # --- Estrategia 2: DOM del dashboard ---
    if not accounts:
        accounts = await _parse_from_dom(page)

    # --- Filtrar por titular si esta configurado ---
    if accounts and config.titular:
        accounts = _filter_by_titular(accounts, config.titular)
        if accounts:
            print(f"  [Visa] {len(accounts)} tarjeta(s) de '{config.titular}'.")
        else:
            print(f"  [Visa] Advertencia: ninguna tarjeta matcheo el titular '{config.titular}'.")
            print(f"  [Visa] Revisando todas las tarjetas encontradas...")
            # Re-parsear sin filtro y mostrar titulares disponibles
            all_accounts = _parse_from_interceptor(interceptor) or await _parse_from_dom(page)
            titulares = {a.extra.get("titular", "?") for a in all_accounts}
            print(f"  [Visa] Titulares disponibles: {titulares}")
            accounts = all_accounts  # fallback: todas
    elif accounts:
        print(f"  [Visa] {len(accounts)} tarjeta(s) encontradas (sin filtro de titular).")

    if accounts:
        return accounts

    # --- Fallback ---
    print("  [Visa] No se encontraron tarjetas - usando cuenta unica")
    return [Account(
        client_number=config.documento_nacional_de_identidad,
        display_name=config.usuario,
        address="",
    )]


def _filter_by_titular(accounts: list[Account], titular: str) -> list[Account]:
    """
    Filtra cuentas cuyo titular coincida con el nombre buscado.

    El portal almacena el nombre en formato 'APELLIDO/NOMBRE' (ej: 'BEN/ALEJANDRO O')
    mientras que VISA_TITULAR usa 'Nombre Apellido' (ej: 'Alejandro Osvaldo Ben').
    Usamos overlap de palabras: si al menos 2 palabras de >= 3 letras coinciden,
    consideramos que es la misma persona.

    Ademas filtramos por card_type == 'Titular' si el portal reporta ese campo,
    de modo que las tarjetas adicionales (de otras personas) queden excluidas.
    """
    # Palabras significativas del titular buscado (>= 3 chars)
    config_words = {
        w for w in re.sub(r"[^a-z]", " ", titular.lower()).split()
        if len(w) >= 3
    }

    filtered = []
    for acc in accounts:
        card_type = acc.extra.get("card_type", "")
        t = acc.extra.get("titular", "")

        # Si tenemos info de tipo: solo incluir Titular, excluir Adicional
        if card_type:
            if card_type.lower() != "titular":
                continue
            filtered.append(acc)
            continue

        # Sin info de tipo: caer a matching por palabras
        t_words = {
            w for w in re.sub(r"[^a-z]", " ", t.lower()).split()
            if len(w) >= 3
        }
        if len(config_words & t_words) >= 2:
            filtered.append(acc)

    return filtered


def _parse_from_interceptor(interceptor: NetworkInterceptor) -> list[Account]:
    """Busca datos de tarjetas en los responses capturados."""
    accounts: list[Account] = []
    seen: set[str] = set()

    for entry in interceptor.captured:
        body = entry.get("body")
        if not isinstance(body, (dict, list)):
            continue

        candidates: list[dict] = []
        if isinstance(body, list):
            candidates = [item for item in body if isinstance(item, dict)]
        elif isinstance(body, dict):
            for key in ("cards", "tarjetas", "accounts", "data", "cuentas"):
                if key in body and isinstance(body[key], list):
                    candidates = [item for item in body[key] if isinstance(item, dict)]
                    break
            if not candidates:
                candidates = [body]

        for item in candidates:
            acc = _card_dict_to_account(item)
            if acc and acc.client_number not in seen:
                seen.add(acc.client_number)
                accounts.append(acc)

    return accounts


def _card_dict_to_account(item: dict) -> Account | None:
    last4: str | None = None
    for key in ("cardNumber", "card_number", "numero", "number", "pan"):
        val = str(item.get(key, ""))
        digits = re.sub(r"\D", "", val)
        if len(digits) >= 4:
            last4 = digits[-4:]
            break
    if not last4:
        return None

    banco = ""
    for key in ("bankName", "bank_name", "banco", "financialEntity", "brand"):
        val = str(item.get(key, "")).strip()
        if val and val.lower() not in ("none", "null", ""):
            banco = val
            break

    titular = ""
    for key in ("holderName", "holder_name", "titular", "name", "nombre"):
        val = str(item.get(key, "")).strip()
        if val and val.lower() not in ("none", "null", ""):
            titular = val
            break

    extra: dict[str, str] = {"titular": titular}
    for key in ("cardNumber", "card_number", "id", "cardId"):
        if key in item:
            extra[key] = str(item[key])

    display = f"Visa {banco} ****{last4}" if banco else f"Tarjeta ****{last4}"
    if titular:
        display += f" ({titular})"
    return Account(client_number=last4, display_name=display, address="", extra=extra)


async def _parse_from_dom(page: Page) -> list[Account]:
    """
    Extrae tarjetas del portal jQuery usando JS.

    Estrategia 1: leer los <LI class="card-selection-div"> del selector de tarjetas.
      Cada LI tiene: numero enmascarado, titular (APELLIDO/NOMBRE), banco, tipo
      (Titular / Adicional).  Esto es la fuente mas confiable.

    Estrategia 2: TreeWalker sobre todo el DOM (fallback si no hay LIs).
    """
    seen: set[str] = set()
    accounts: list[Account] = []

    try:
        raw = await page.evaluate(
            r"""() => {
                const results = [];
                const seen   = new Set();

                // ---- Estrategia 1: LI.card-selection-div ----
                const cardLis = document.querySelectorAll(
                    'li.card-selection-div, li[class*="card-selection"], li[class*="card-item"]'
                );

                for (const li of cardLis) {
                    const text = (li.textContent || '').trim();

                    // Ultimos 4 digitos del numero enmascarado
                    const numM = /[Xx*X\u2022]{4}[\s\xa0]*(\d{4})/.exec(text);
                    if (!numM) continue;
                    const last4 = numM[1];
                    if (seen.has(last4)) continue;
                    seen.add(last4);

                    // Tipo: Titular / Adicional
                    const typeM = /\(\s*(Titular|Adicional)\s*\)/i.exec(text);
                    const cardType = typeM ? typeM[1] : '';

                    // Lineas utiles (sin espacios, sin la linea del numero)
                    const lines = text.split('\n')
                        .map(l => l.trim())
                        .filter(l => l.length > 1 && !/[Xx*X\u2022]{4}/.test(l)
                                     && !/Titular|Adicional/.test(l)
                                     && !l.startsWith('('));

                    let titular = '';
                    let banco   = '';
                    for (const line of lines) {
                        // Titular: suele ser TODO MAYUSCULAS con / (formato APELLIDO/NOMBRE)
                        if (!titular && /^[A-Z\u00C0-\u00DC\/\s]{3,}$/.test(line)) {
                            titular = line;
                            continue;
                        }
                        // Banco: primera linea que quede despues del titular
                        if (titular && !banco) {
                            banco = line;
                        }
                    }

                    results.push({ last4, titular, banco, cardType });
                }

                if (results.length > 0) return results;

                // ---- Estrategia 2: TreeWalker (fallback) ----
                const numPat   = /[X*x]{4}[\s-]*[X*x]{4}[\s-]*[X*x]{4}[\s-]*(\d{4})/;
                const shortPat = /[X*x]{4}[\s-]*(\d{4})/;
                const walker   = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null
                );
                let node;
                while ((node = walker.nextNode())) {
                    const text = node.textContent || '';
                    const m    = numPat.exec(text) || shortPat.exec(text);
                    if (!m) continue;
                    const last4 = m[1];
                    if (seen.has(last4)) continue;
                    seen.add(last4);

                    // Contexto del ancestro mas cercano
                    let ctx = '';
                    let el  = node.parentElement;
                    for (let i = 0; i < 6 && el; i++) {
                        const tag = el.tagName.toLowerCase();
                        if (['li','tr','div','article','section'].includes(tag)) {
                            ctx = (el.textContent || '').trim();
                            break;
                        }
                        el = el.parentElement;
                    }
                    results.push({ last4, titular: '', banco: '', cardType: '', ctx });
                }
                return results;
            }"""
        )

        for item in raw:
            last4     = item["last4"]
            titular   = item.get("titular", "")
            banco     = item.get("banco", "")
            card_type = item.get("cardType", "")

            # Fallback cuando viene de TreeWalker: intentar extraer titular del ctx
            if not titular and item.get("ctx"):
                ctx = item["ctx"]
                m = re.search(r'([A-Z]{2,}(?:/[A-Z]{2,})+(?:\s+[A-Z]{1,})*)', ctx)
                if m:
                    titular = m.group(1)

            extra = {"titular": titular, "card_type": card_type}
            if banco:
                extra["banco"] = banco

            if card_type:
                display = f"Visa {banco} ({card_type}) ****{last4}" if banco else f"Visa ({card_type}) ****{last4}"
            else:
                display = f"Visa {banco} ****{last4}" if banco else f"Tarjeta ****{last4}"
            if titular:
                display += f" - {titular}"

            if last4 not in seen:
                seen.add(last4)
                accounts.append(Account(
                    client_number=last4,
                    display_name=display,
                    address="",
                    extra=extra,
                ))

    except Exception as e:
        print(f"  [Visa] Error parseando DOM: {e}")

    return accounts


async def _close_popup(page: Page) -> None:
    for selector in [
        'a:has-text("cerrar")', 'button:has-text("Cancelar")',
        'button:has-text("cerrar")', '[aria-label="cerrar"]',
    ]:
        try:
            el = page.locator(selector).first
            if await el.count() > 0 and await el.is_visible(timeout=2000):
                await el.click()
                await asyncio.sleep(0.5)
                return
        except Exception:
            pass
