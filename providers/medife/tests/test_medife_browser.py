import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from providers.medife import MedifeProvider
from providers.medife.browser import apply_context_stealth
from providers.medife.login import LoginOrchestrator


def test_stealth_registers_init_script_once_on_the_persistent_context():
    # Usa el paquete real y un contexto mínimo, sin abrir portales ni credenciales.
    context = SimpleNamespace(add_init_script=AsyncMock())
    asyncio.run(apply_context_stealth(context))
    context.add_init_script.assert_awaited_once()
    script = context.add_init_script.await_args.args[0]
    assert 'navigator.webdriver' in script
    # Instalarlo en el contexto cubre recargas, pestañas e iframes siguientes.
    # Una segunda llamada no debe acumular los mismos parches.
    with pytest.warns(UserWarning, match='already'):
        asyncio.run(apply_context_stealth(context))
    context.add_init_script.assert_awaited_once()


@pytest.mark.parametrize('enabled', [True, False])
def test_stealth_applied_before_login_and_can_be_disabled(monkeypatch, enabled):
    monkeypatch.setenv('MEDIFE_STEALTH_ENABLED', str(enabled).lower())
    monkeypatch.setenv('MEDIFE_MANUAL_LOGIN', 'false')
    provider = MedifeProvider()
    events = []
    context = SimpleNamespace()
    async def apply(target):
        assert target is context
        events.append('stealth')
    async def execute(self):
        events.append('navigate')
    monkeypatch.setattr('providers.medife.apply_context_stealth', apply)
    monkeypatch.setattr(LoginOrchestrator, 'execute', execute)
    asyncio.run(provider.login(SimpleNamespace(), context))
    assert events == (['stealth', 'navigate'] if enabled else ['navigate'])
