import asyncio

from providers.mastercard import login as mastercard_login
from providers.mastercard.config import MastercardConfig


class _Response:
    status = 200
    url = "https://misconsultas.com.ar/mfa/validation"

    async def json(self):
        return {"token": "jwt-token"}


class _OtpInput:
    def __init__(self, page):
        self.page = page

    async def wait_for(self, **kwargs):
        assert kwargs == {"state": "visible", "timeout": self.page.timeout_ms}

    async def fill(self, value):
        self.page.otp = value

    async def press(self, key):
        assert key == "Enter"
        await self.page.response_handler(_Response())


class _Page:
    url = "https://misconsultas.com.ar/socios/login"

    def __init__(self):
        self.timeout_ms = 30000
        self.otp = ""
        self.response_handler = None

    async def goto(self, *args, **kwargs):
        pass

    async def wait_for_load_state(self, *args, **kwargs):
        pass

    async def wait_for_selector(self, *args, **kwargs):
        pass

    async def fill(self, *args, **kwargs):
        pass

    async def click(self, *args, **kwargs):
        pass

    async def inner_text(self, *args, **kwargs):
        return ""

    def on(self, event, handler):
        assert event == "response"
        self.response_handler = handler

    def remove_listener(self, event, handler):
        assert event == "response"
        assert handler is self.response_handler

    def locator(self, selector):
        assert selector == "#digitosTarjeta"
        return _OtpInput(self)


class _Context:
    async def cookies(self):
        return []


def test_mastercard_requests_authenticator_code_in_console_and_submits_it(monkeypatch):
    async def skip_sleep(_):
        pass

    monkeypatch.setattr(mastercard_login.asyncio, "sleep", skip_sleep)
    prompts = []

    def enter_code(prompt):
        prompts.append(prompt)
        return "123456"

    monkeypatch.setattr("builtins.input", enter_code)
    page = _Page()
    config = MastercardConfig(email="user@example.com", password="secret")

    token = asyncio.run(mastercard_login.do_login(page, _Context(), config))

    assert prompts == ["  Codigo actual de Authenticator: "]
    assert page.otp == "123456"
    assert token == "jwt-token"
