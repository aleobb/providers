from __future__ import annotations

import asyncio
from pathlib import Path


def unique_path(base: Path) -> Path:
    """Return a non-colliding path by appending _2, _3, etc."""
    if not base.exists():
        return base
    stem, suffix = base.stem, base.suffix
    counter = 2
    while True:
        candidate = base.parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


async def dismiss_popups(page, *, label: str = "") -> int:
    """
    Cierra modals/popups genericos que aparecen en cualquier portal
    (habilitacion de tarjetas, cookies, avisos legales, etc.).

    Busca botones de cierre/rechazo ESPECIFICOS y hace click en el primero visible.
    Retorna la cantidad de popups cerrados.

    IMPORTANTE: los selectores deben ser muy especificos. No usar patrones como
    `button[class*="close"]` o `a:has-text("cerrar")` porque matchean botones de
    navegacion normales (ej. dropit.js en el portal Visa crea menus con clases
    tipo `*-layer` que seran interpretadas como modales).
    """
    _DISMISS_SELECTORS = [
        # Botones de cierre con aria-label EXACTO (muy especifico)
        '[aria-label="Cerrar"]',
        '[aria-label="Close"]',
        # Textos muy especificos de popups/avisos (poco riesgo de falso positivo)
        'button:has-text("No, gracias")',
        'button:has-text("No gracias")',
        'button:has-text("Omitir")',
        'button:has-text("Saltar")',
        'button:has-text("Entendido")',
        'button:has-text("entendido")',
        # Material / Bootstrap estandar (scoped a contenedor de dialog)
        '.modal-header button.close',
        'mat-dialog-container button[mat-dialog-close]',
        '.cdk-overlay-container button[mat-dialog-close]',
    ]

    closed = 0
    for selector in _DISMISS_SELECTORS:
        try:
            el = page.locator(selector).first
            if await el.count() > 0 and await el.is_visible(timeout=400):
                tag = label or "popup"
                print(f"  [dismiss] Cerrando {tag}: {selector}")
                await el.click()
                await asyncio.sleep(0.4)
                closed += 1
                break  # un click por ronda; el caller puede llamar varias veces
        except Exception:
            pass
    return closed
