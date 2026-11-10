import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from playwright.async_api import TimeoutError as PlaywrightTimeout

from core.credential_store import CredentialStore
from core.exceptions import ConfigurationError, LoginError
from providers.medife.config import MedifeConfig
from providers.medife.login import LoginOrchestrator


def login_page(mode):
    page = MagicMock()
    state = {'mode': mode}
    locators = {}
    for selector in ('#email', '#nrodoc', '#tipodoc', '#password'):
        locator = MagicMock()
        locator.fill = AsyncMock()
        locator.select_option = AsyncMock()
        locator.is_visible = AsyncMock(side_effect=lambda s=selector: (
            (s == '#nrodoc' and state['mode'] == 'document')
            or (s == '#email' and state['mode'] == 'email')
        ))
        locators[selector] = locator
    page.locator.side_effect = locators.__getitem__
    switch = MagicMock()
    async def switch_mode():
        state['mode'] = 'document'
    switch.click = AsyncMock(side_effect=switch_mode)
    submit = MagicMock()
    submit.click = AsyncMock()
    page.get_by_role.side_effect = lambda role, **kw: (
        switch if kw['name'] == 'Ingresar con mi número de documento' else submit
    )
    page.goto = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.wait_for_url = AsyncMock()
    page.get_by_text.return_value.wait_for = AsyncMock()
    return page, locators, submit


@pytest.mark.parametrize('mode', ['document', 'email'])
@pytest.mark.parametrize('kind', ['', 'LC'])
def test_login_uses_document_form_including_return_from_email(mode, kind):
    page, locators, submit = login_page(mode)
    config = MedifeConfig(tipo_documento=kind, documento_nacional_de_identidad='12345678', password='test-only')
    asyncio.run(LoginOrchestrator(page, config).execute())
    locators['#tipodoc'].select_option.assert_awaited_once_with(kind or 'DNI')
    locators['#nrodoc'].fill.assert_awaited_once_with('12345678')
    locators['#password'].fill.assert_awaited_once_with('test-only')
    locators['#email'].fill.assert_not_awaited()
    submit.click.assert_awaited_once()
    assert page.goto.await_args_list[-1].args[0] == config.invoices_url


def test_active_session_does_not_submit_credentials():
    page, locators, submit = login_page('active')
    asyncio.run(LoginOrchestrator(page, MedifeConfig()).execute())
    submit.click.assert_not_awaited()
    locators['#password'].fill.assert_not_awaited()


def test_old_email_only_profile_fails_before_submit():
    page, locators, submit = login_page('document')
    config = MedifeConfig(password='test-only')
    config.set_credentials({'email': 'unused@example.invalid', 'password': 'test-only'})
    with pytest.raises(LoginError, match='gestionar-credenciales'):
        asyncio.run(LoginOrchestrator(page, config).execute())
    submit.click.assert_not_awaited()
    locators['#password'].fill.assert_not_awaited()


def test_unsupported_document_type_fails_before_sending_number():
    page, locators, submit = login_page('document')
    config = MedifeConfig(tipo_documento='invalid', documento_nacional_de_identidad='12345678', password='test-only')
    with pytest.raises(ConfigurationError, match='Tipo de documento'):
        asyncio.run(LoginOrchestrator(page, config).execute())
    locators['#nrodoc'].fill.assert_not_awaited()
    submit.click.assert_not_awaited()


def test_login_timeout_reports_manual_verification_without_exposing_credentials():
    page, locators, submit = login_page('document')
    page.wait_for_url.side_effect = PlaywrightTimeout('timeout')
    config = MedifeConfig(documento_nacional_de_identidad='12345678', password='test-only')
    with pytest.raises(LoginError, match='--debug') as error:
        asyncio.run(LoginOrchestrator(page, config).execute())
    assert '12345678' not in str(error.value)
    assert 'test-only' not in str(error.value)


def test_existing_medife_schema_migrates_without_changing_other_providers_or_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv('PROVIDERS_CREDENTIALS_KEY', Fernet.generate_key().decode())
    store = CredentialStore(tmp_path / 'credentials.sqlite3')
    profile_id = store.add_profile('medife', 'Prueba', {'email': 'unused@example.invalid', 'password': 'test-only'})
    other_fields = store.get_credential_fields('edenor')
    with sqlite3.connect(store.database_path) as connection:
        medife_id = connection.execute("SELECT id FROM providers WHERE name='medife'").fetchone()[0]
        connection.execute('DELETE FROM provider_credential_fields WHERE provider_id=?', (medife_id,))
        connection.executemany(
            'INSERT INTO provider_credential_fields VALUES (?, ?, ?, ?, ?, ?)',
            [(medife_id, 'email', 'Email', 1, 0, 0), (medife_id, 'password', 'Contraseña', 1, 1, 1)],
        )
    for _ in range(2):
        store = CredentialStore(store.database_path)
        assert [f.name for f in store.get_credential_fields('medife')] == [
            'tipo_documento', 'documento_nacional_de_identidad', 'password'
        ]
        assert store.get_credential_fields('edenor') == other_fields
        assert store.get_profile(profile_id).credentials['password'] == 'test-only'
    config = MedifeConfig()
    config.set_credentials({'tipo_documento': ' lc ', 'documento_nacional_de_identidad': '12345678', 'password': 'test-only'})
    assert config.tipo_documento == 'LC'
    assert config.documento_nacional_de_identidad == '12345678'
