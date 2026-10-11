import asyncio
from pathlib import Path
from types import SimpleNamespace

from core import cli
from core.browser import BrowserSession
from core.config import BaseProviderConfig
from core.provider import Provider
from providers.telecentro.config import TelecentroConfig


def test_parse_args_enables_nosession(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--proveedor", "telecentro", "--todas", "--nosession"],
    )

    args = cli.parse_args()

    assert args["nosession"] is True
    assert args["proveedor"] == "telecentro"
    assert args["todas"] is True


def test_parse_args_disables_nosession_by_default(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py", "--proveedor", "telecentro"])

    assert cli.parse_args()["nosession"] is False


def test_telecentro_uses_unpatched_chrome_with_automation_control_disabled():
    config = TelecentroConfig(email="user@example.com", password="secret")

    assert config.browser_stealth is False
    assert config.browser_user_agent is None
    assert "--disable-blink-features=AutomationControlled" in config.browser_args


def test_additional_browser_args_are_disabled_for_other_providers_by_default():
    config = BaseProviderConfig(email="user@example.com", password="secret")

    assert config.browser_args == []


def test_fresh_browser_session_uses_and_removes_an_empty_temporary_profile(
    monkeypatch,
):
    launch_options = {}
    temporary_profile = None

    class FakeBrowserContext:
        async def new_page(self):
            return object()

        async def close(self):
            pass

    class FakeChromium:
        async def launch_persistent_context(self, **options):
            nonlocal launch_options
            launch_options = options
            return FakeBrowserContext()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightContext:
        async def __aenter__(self):
            return FakePlaywright()

        async def __aexit__(self, *_args):
            pass

    monkeypatch.setattr("core.browser.async_playwright", FakePlaywrightContext)
    config = TelecentroConfig(
        email="user@example.com",
        password="secret",
        headless=False,
    )
    configured_profile = config.browser_user_data_dir

    async def exercise():
        nonlocal temporary_profile
        async with BrowserSession(
            config, profile_name="telecentro", fresh_profile=True
        ) as session:
            temporary_profile = Path(launch_options["user_data_dir"])
            assert temporary_profile.is_dir()
            assert temporary_profile != configured_profile
            assert "--profile-directory=Default" not in launch_options["args"]
            assert "--disable-blink-features=AutomationControlled" in launch_options["args"]

    asyncio.run(exercise())

    assert temporary_profile is not None
    assert not temporary_profile.exists()


def test_run_provider_nosession_skips_saved_session_and_session_persistence(
    monkeypatch,
):
    browser_options = {}
    fake_page = object()
    fake_context = object()
    account = SimpleNamespace(
        client_number="123",
        display_name="Test",
        display=lambda _index: "Test account",
    )

    class FakeProvider(Provider):
        name = "telecentro"
        display_name = "Telecentro"
        requires_credentials = False

        def get_config(self):
            return SimpleNamespace(
                headless=True,
                email="user@example.com",
                browser_user_data_dir=Path("configured-profile"),
            )

        async def login(self, _page, _context):
            pass

        async def fetch_accounts(self, _page, _context):
            return [account]

        async def download_invoice(self, _page, _context, _account):
            raise NotImplementedError

        async def save_session(self, _page, _context, _accounts):
            raise AssertionError("--nosession must not persist a session")

    class FakeBrowserSession:
        def __init__(self, _config, **options):
            browser_options.update(options)

        async def __aenter__(self):
            return SimpleNamespace(page=fake_page, context=fake_context)

        async def __aexit__(self, *_args):
            pass

    async def no_sleep(_seconds):
        pass

    async def no_popups(_page, *, label):
        return False

    monkeypatch.setattr(cli, "BrowserSession", FakeBrowserSession)
    monkeypatch.setattr(cli, "dismiss_popups", no_popups)
    monkeypatch.setattr("asyncio.sleep", no_sleep)
    monkeypatch.setattr(
        "core.session_store.load",
        lambda _provider: (_ for _ in ()).throw(
            AssertionError("--nosession must not load a saved session")
        ),
    )

    result = asyncio.run(
        cli.run_provider(
            FakeProvider(),
            debug=False,
            listar=True,
            todas=False,
            cuenta=None,
            nosession=True,
        )
    )

    assert result is True
    assert browser_options["fresh_profile"] is True
