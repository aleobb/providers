import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.accounts import Account
from core.exceptions import DownloadError
from core.registry import get_provider
from providers.medife.accounts import parse_client_number
from providers.medife.config import MedifeConfig
from providers.medife.invoice import InvoiceService, parse_period, validate_pdf_url


def test_medife_is_registered_and_uses_standard_credentials():
    import providers
    provider = get_provider('medife')
    assert [f.name for f in provider.credential_fields] == ['email', 'password']
    assert provider.get_config().browser_stealth is False


def test_account_and_period_from_portal():
    assert parse_client_number('Estado de cuenta: Nro de cliente\n123456') == '123456'
    assert parse_period(' noviembre 2026 ') == '2026-11'
    with pytest.raises(DownloadError):
        parse_period('periodo no disponible')


@pytest.mark.parametrize('url', [
    'https://facturacion.medife.com.ar.ejemplo.com/a.pdf',
    'http://facturacion.medife.com.ar/a.pdf',
    'https://facturacion.medife.com.ar/a.html',
])
def test_rejects_unexpected_download_destinations(url):
    with pytest.raises(DownloadError):
        validate_pdf_url(url)


def make_row(period, file):
    row = MagicMock()
    cells = MagicMock()
    cell = SimpleNamespace(inner_text=AsyncMock(return_value=period))
    cells.nth.return_value = cell
    link = SimpleNamespace(get_attribute=AsyncMock(return_value=(
        f'https://facturacion.medife.com.ar/{file}.pdf'
    )))
    row.locator.side_effect = lambda selector: cells if selector == 'td' else link
    return row


@pytest.mark.parametrize('body,valid', [(b'%PDF-1.7\nfixture', True), (b'<html>login</html>', False)])
def test_download_selects_latest_unsorted_period_and_validates_content(tmp_path, monkeypatch, body, valid):
    account = Account('123456', 'Medife', '')
    fetch = AsyncMock(return_value=[account])
    monkeypatch.setattr('providers.medife.invoice.fetch_accounts', fetch)
    rows = MagicMock()
    rows.first.wait_for = AsyncMock()
    rows.all = AsyncMock(return_value=[
        make_row('diciembre 2025', 'old'), make_row('febrero 2026', 'latest'),
        make_row('enero 2026', 'middle'),
    ])
    page = MagicMock()
    page.locator.return_value.filter.return_value = rows
    response = SimpleNamespace(
        ok=True, status=200, url='https://facturacion.medife.com.ar/latest.pdf',
        body=AsyncMock(return_value=body), dispose=AsyncMock(),
    )
    page.context.request.get = AsyncMock(return_value=response)
    service = InvoiceService(page, MedifeConfig(output_dir=tmp_path))
    if valid:
        path = asyncio.run(service.download_for_account(account))
        assert path.name == 'medife_2026-02_123456_factura.pdf'
        assert path.read_bytes() == body
    else:
        with pytest.raises(DownloadError, match='no es un PDF'):
            asyncio.run(service.download_for_account(account))
        assert not list(tmp_path.iterdir())
    assert page.context.request.get.call_args.args[0].endswith('/latest.pdf')
    response.dispose.assert_awaited_once()


def test_does_not_download_another_clients_invoice(tmp_path, monkeypatch):
    monkeypatch.setattr('providers.medife.invoice.fetch_accounts', AsyncMock(
        return_value=[Account('999999', 'Medife', '')]
    ))
    page = MagicMock()
    service = InvoiceService(page, MedifeConfig(output_dir=tmp_path))
    with pytest.raises(DownloadError, match='no coincide'):
        asyncio.run(service.download_for_account(Account('123456', 'Medife', '')))
    page.context.request.get.assert_not_called()
