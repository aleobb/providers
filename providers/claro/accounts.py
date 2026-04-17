from __future__ import annotations

import asyncio
import base64
from urllib.parse import urlparse, unquote

from playwright.async_api import Page

from core.accounts import Account
from .config import ClaroConfig

# Selector de los botones de cuenta en /elegirservicio
_SWITCH_BTN = '.SwitchButton-module_switchButton__yOnRv'


async def fetch_accounts(page: Page, config: ClaroConfig) -> list[Account]:
    """
    Navega a /elegirservicio, hace click en cada botón de cuenta para capturar
    el billNumber (número de línea) codificado en la URL resultante.
    Devuelve todos los accounts del usuario.
    """
    accounts: list[Account] = []
    seen_names: set[str] = set()
    index = 0

    while True:
        await page.goto(config.elegir_url, timeout=config.timeout_ms)
        await page.wait_for_load_state("networkidle", timeout=config.timeout_ms)
        await asyncio.sleep(1)

        buttons = await page.query_selector_all(_SWITCH_BTN)
        if index >= len(buttons):
            break

        btn = buttons[index]
        display_name = (await btn.inner_text()).strip()

        # El botón "Agregar" no es una cuenta real
        if display_name.lower() == "agregar" or display_name in seen_names:
            index += 1
            continue

        # Clic en el botón → navega a /{base64(billNumber)}/home
        await btn.click()
        await page.wait_for_load_state("networkidle", timeout=config.timeout_ms)
        await asyncio.sleep(1)

        bill_number = _extract_bill_number(page.url)
        if bill_number:
            accounts.append(
                Account(
                    client_number=bill_number,
                    display_name=display_name,
                    address="",
                )
            )
            seen_names.add(display_name)

        index += 1

    return accounts


def _extract_bill_number(url: str) -> str:
    """
    Extrae el billNumber del path de la URL.
    Ejemplo: https://m-miclaro.claro.com.ar/MTE1NzAwNDE1MQ%3D%3D/home
             → decode URL → MTE1NzAwNDE1MQ==
             → decode base64 → 1157004151
    """
    try:
        path = urlparse(url).path  # /MTE1NzAwNDE1MQ%3D%3D/home
        parts = [p for p in path.split("/") if p]
        if not parts:
            return ""
        b64 = unquote(parts[0])   # MTE1NzAwNDE1MQ==
        return base64.b64decode(b64).decode("utf-8")
    except Exception:
        return ""
