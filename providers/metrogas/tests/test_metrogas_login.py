import asyncio
from types import SimpleNamespace

from providers.metrogas.login import LoginOrchestrator


class _Input:
    def __init__(self, value):
        self.value = value
        self.filled_values = []

    async def wait_for(self, **kwargs):
        pass

    async def input_value(self):
        return self.value

    async def fill(self, value):
        self.filled_values.append(value)
        self.value = value


class _Button:
    async def click(self):
        pass


class _Locator:
    def __init__(self, element):
        self.first = element


class _Page:
    def __init__(self, email):
        self.email_input = _Input(email)
        self.submit_button = _Button()

    def locator(self, selector):
        if selector == "#j_username, input[name='j_username']":
            return _Locator(self.email_input)
        return _Locator(self.submit_button)


def _run_email_step(prefilled_email):
    page = _Page(prefilled_email)
    orchestrator = LoginOrchestrator(
        page,
        SimpleNamespace(email="user@example.com", timeout_ms=1000),
    )

    async def no_error(step):
        assert step == "email"

    orchestrator._check_for_error = no_error
    asyncio.run(orchestrator._fill_email())
    return page.email_input.filled_values


def test_metrogas_login_keeps_precompleted_email():
    assert _run_email_step("user@example.com") == []


def test_metrogas_login_replaces_different_precompleted_email():
    assert _run_email_step("other@example.com") == ["user@example.com"]


def test_metrogas_login_fills_empty_email():
    assert _run_email_step("") == ["user@example.com"]
