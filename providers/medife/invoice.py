import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from core.accounts import Account
from core.exceptions import DownloadError, InvoiceNotFoundError
from core.utils import unique_path
from .accounts import fetch_accounts
from .config import MedifeConfig

_MONTHS = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
}


def parse_period(text: str) -> str:
    match = re.fullmatch(r'\s*([a-z]+)\s+(\d{4})\s*', text.lower())
    if not match or match.group(1) not in _MONTHS:
        raise DownloadError('Periodo de factura Medife no reconocido.')
    return f'{match.group(2)}-{_MONTHS[match.group(1)]:02d}'


def validate_pdf_url(url: str) -> None:
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.netloc != 'facturacion.medife.com.ar'
            or not parts.path.lower().endswith('.pdf')):
        raise DownloadError('Enlace PDF de Medife inesperado.')


class InvoiceService:
    def __init__(self, page: Page, config: MedifeConfig):
        self.page = page
        self.config = config

    async def download_for_account(self, account: Account) -> Path:
        current = (await fetch_accounts(self.page, self.config))[0]
        if current.client_number != account.client_number:
            raise DownloadError('El cliente activo de Medife no coincide con la cuenta solicitada.')
        # Solo filas de la tabla: el portal duplica las tarjetas para vista móvil.
        rows = self.page.locator('table tbody tr').filter(
            has=self.page.locator('a[href*="facturacion.medife.com.ar/"]')
        )
        try:
            await rows.first.wait_for(state='attached', timeout=self.config.timeout_ms)
        except PlaywrightTimeout as error:
            raise InvoiceNotFoundError('No hay facturas disponibles en Medife.') from error
        invoices = []
        for row in await rows.all():
            cells = row.locator('td')
            period = parse_period(await cells.nth(1).inner_text())
            href = await row.locator('a').get_attribute('href')
            if href:
                validate_pdf_url(href)
                invoices.append((period, href))
        if not invoices:
            raise InvoiceNotFoundError('No hay facturas disponibles en Medife.')
        period, url = max(invoices, key=lambda item: item[0])
        response = await self.page.context.request.get(url, timeout=self.config.timeout_ms)
        try:
            if not response.ok:
                raise DownloadError(f'HTTP {response.status} al descargar PDF de Medife.')
            validate_pdf_url(response.url)
            content = await response.body()
            if not content.startswith(b'%PDF-'):
                raise DownloadError('Medife devolvio contenido que no es un PDF.')
            path = unique_path(self.config.ensure_output_dir() / (
                f'medife_{period}_{account.client_number}_factura.pdf'
            ))
            path.write_bytes(content)
            return path
        finally:
            await response.dispose()
