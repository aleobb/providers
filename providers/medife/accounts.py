import re

from playwright.async_api import Page

from core.accounts import Account
from core.exceptions import NavigationError
from .config import MedifeConfig


def parse_client_number(text: str) -> str:
    match = re.search(r'Estado de cuenta:\s*Nro de cliente\s*(\d+)\b', text, re.I)
    if not match:
        raise NavigationError('No se encontro el numero de cliente en facturacion de Medife.')
    return match.group(1)


async def fetch_accounts(page: Page, config: MedifeConfig) -> list[Account]:
    if page.url != config.invoices_url:
        await page.goto(config.invoices_url, timeout=config.timeout_ms)
    summary = page.get_by_text('Estado de cuenta:', exact=False)
    await summary.wait_for(state='visible', timeout=config.timeout_ms)
    number = parse_client_number(await summary.inner_text())
    # El portal muestra el cliente activo. Otros accesos usan perfiles de credenciales.
    return [Account(client_number=number, display_name='Medife', address='')]
