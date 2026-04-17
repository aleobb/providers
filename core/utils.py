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

    Busca botones de cierre/rechazo y hace click en el primero visible.
    Retorna la cantidad de popups cerrados.
    """
    # Selectores ordenados de mas especifico a mas generico.
    # Priorizamos "No", "Cancelar", "Cerrar" para NO confirmar nada accidentalmente.
    _DISMISS_SELECTORS = [
        # Botones de cierre explicitos
        '[aria-label="Cerrar"]',
        '[aria-label="cerrar"]',
        '[aria-label="Close"]',
        'button[class*="close"]',
        'button[class*="cerrar"]',
        # Textos de rechazo/omision
        'button:has-text("No, gracias")',
        'button:has-text("No gracias")',
        'button:has-text("Omitir")',
        'button:has-text("Saltar")',
        'button:has-text("Cerrar")',
        'button:has-text("cerrar")',
        'a:has-text("Cerrar")',
        'a:has-text("cerrar")',
        'button:has-text("Cancelar")',
        # Confirmacion generica de avisos / habilitacion de tarjetas / legales
        'button:has-text("Entendido")',
        'button:has-text("entendido")',
        'button:has-text("Aceptar")',
        'button:has-text("aceptar")',
        'button:has-text("De acuerdo")',
        'button:has-text("OK")',
        'button:has-text("Continuar")',
        # X tipico de modal
        'button:text-is("x")',
        'button:text-is("X")',
        'button:text-is("×")',
        'span:text-is("×")',
        # Material / Bootstrap
        '.modal-header button.close',
        'mat-dialog-container button[mat-dialog-close]',
        '.cdk-overlay-container button[mat-dialog-close]',
    ]

    closed = 0
    for selector in _DISMISS_SELECTORS:
        try:
            el = page.locator(selector).first
            if await el.count() > 0 and await el.is_visible(timeout=600):
                tag = label or "popup"
                print(f"  [dismiss] Cerrando {tag}: {selector}")
                await el.click()
                await asyncio.sleep(0.6)
                closed += 1
                break  # un click por ronda; el caller puede llamar varias veces
        except Exception:
            pass
    return closed
