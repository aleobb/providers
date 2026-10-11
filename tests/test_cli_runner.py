import asyncio
import sys
import types
from types import SimpleNamespace

from core import cli
from core.accounts import Account
from core.exceptions import DownloadError
from core.provider import Provider


class _BaseFakeProvider(Provider):
    name = "fake"
    display_name = "Fake Provider"
    requires_credentials = False

    def __init__(self, accounts, tmp_path):
        self.accounts = accounts
        self.tmp_path = tmp_path
        self.download_calls = []
        self.saved = False
        self.logged_out = False
        self.closed = False

    def get_config(self):
        return SimpleNamespace(
            headless=True,
            email="fake@example.com",
            browser_user_data_dir=None,
        )

    async def login(self, _page, _context):
        pass

    async def fetch_accounts(self, _page, _context):
        return self.accounts

    async def download_invoice(self, page, context, account):
        self.download_calls.append((page, context, account.client_number))
        if account.client_number == "fail":
            raise DownloadError("boom")
        path = self.tmp_path / f"{account.client_number}.pdf"
        path.write_bytes(b"%PDF-1.4\n")
        return path

    async def save_session(self, _page, _context, _accounts):
        self.saved = True

    async def logout(self, _page, _context):
        self.logged_out = True

    async def close(self):
        self.closed = True


def _patch_cli_side_effects(monkeypatch):
    logged_ok = []
    logged_errors = []

    async def no_sleep(_seconds):
        pass

    async def no_popups(_page, *, label):
        return False

    monkeypatch.setattr("asyncio.sleep", no_sleep)
    monkeypatch.setattr(cli, "dismiss_popups", no_popups)
    monkeypatch.setattr(cli, "determine_invoice_period", lambda *_args: "2026-04-01")
    monkeypatch.setattr(cli.run_log, "log_ok", lambda *args: logged_ok.append(args))
    monkeypatch.setattr(
        cli.run_log, "log_error", lambda *args: logged_errors.append(args)
    )
    monkeypatch.setattr(cli.run_log, "log_run_start", lambda *_args: None)
    return logged_ok, logged_errors


def _install_fake_browser_session(monkeypatch, page=None, context=None):
    page = page or object()
    context = context or object()

    class FakeBrowserSession:
        def __init__(self, _config, **_options):
            pass

        async def __aenter__(self):
            return SimpleNamespace(page=page, context=context)

        async def __aexit__(self, *_args):
            pass

    monkeypatch.setattr(cli, "BrowserSession", FakeBrowserSession)
    return page, context


def test_run_provider_uses_saved_session_without_browser_for_all_accounts(
    monkeypatch, tmp_path
):
    accounts = [
        Account("ok", "OK", ""),
        Account("fail", "Fail", ""),
    ]

    class FakeProvider(_BaseFakeProvider):
        can_resume_session = True

        async def try_resume_session(self, data):
            assert data == {"saved": True}
            return self.accounts

    provider = FakeProvider(accounts, tmp_path)
    logged_ok, logged_errors = _patch_cli_side_effects(monkeypatch)
    monkeypatch.setattr("core.session_store.load", lambda _key: {"saved": True})
    monkeypatch.setattr(
        cli,
        "BrowserSession",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("saved session path must not open the browser")
        ),
    )

    result = asyncio.run(
        cli.run_provider(
            provider,
            debug=False,
            listar=False,
            todas=True,
            cuenta=None,
        )
    )

    assert result is False
    assert provider.download_calls == [(None, None, "ok"), (None, None, "fail")]
    assert [entry[1] for entry in logged_ok] == ["ok"]
    assert [entry[1] for entry in logged_errors] == ["fail"]
    assert provider.closed is True


def test_run_provider_lists_accounts_without_downloading(monkeypatch, tmp_path, capsys):
    accounts = [
        Account("123", "Casa", "Calle Uno"),
        Account("456", "Oficina", "Calle Dos"),
    ]
    provider = _BaseFakeProvider(accounts, tmp_path)
    _patch_cli_side_effects(monkeypatch)
    _install_fake_browser_session(monkeypatch)

    result = asyncio.run(
        cli.run_provider(
            provider,
            debug=False,
            listar=True,
            todas=False,
            cuenta=None,
        )
    )

    output = capsys.readouterr().out
    assert result is True
    assert "2 cuenta(s)" in output
    assert "Casa" in output
    assert "Oficina" in output
    assert provider.download_calls == []
    assert provider.saved is True
    assert provider.logged_out is True
    assert provider.closed is True


def test_run_provider_downloads_all_accounts_and_reports_partial_failure(
    monkeypatch, tmp_path, capsys
):
    accounts = [Account("ok", "Correcta", ""), Account("fail", "Fallida", "")]
    provider = _BaseFakeProvider(accounts, tmp_path)
    logged_ok, logged_errors = _patch_cli_side_effects(monkeypatch)
    page, context = _install_fake_browser_session(monkeypatch)

    result = asyncio.run(
        cli.run_provider(
            provider,
            debug=False,
            listar=False,
            todas=True,
            cuenta=None,
        )
    )

    output = capsys.readouterr()
    assert result is False
    assert provider.download_calls == [(page, context, "ok"), (page, context, "fail")]
    assert [entry[1] for entry in logged_ok] == ["ok"]
    assert [entry[1] for entry in logged_errors] == ["fail"]
    assert "Resumen Fake Provider" in output.out
    assert "FAIL N fail: boom" in output.err


def test_run_provider_downloads_only_the_requested_account(
    monkeypatch, tmp_path
):
    accounts = [Account("123", "Casa", ""), Account("456", "Oficina", "")]
    provider = _BaseFakeProvider(accounts, tmp_path)
    logged_ok, logged_errors = _patch_cli_side_effects(monkeypatch)
    page, context = _install_fake_browser_session(monkeypatch)

    result = asyncio.run(
        cli.run_provider(
            provider,
            debug=False,
            listar=False,
            todas=False,
            cuenta="2",
        )
    )

    assert result is True
    assert provider.download_calls == [(page, context, "456")]
    assert [entry[1] for entry in logged_ok] == ["456"]
    assert logged_errors == []


def test_run_provider_browser_path_uploads_successful_downloads(
    monkeypatch, tmp_path
):
    fake_page = object()
    fake_context = object()
    account = Account(
        "123",
        "Cuenta",
        "",
        extra={"banco": "Banco Test"},
    )
    provider = _BaseFakeProvider([account], tmp_path)
    logged_ok, logged_errors = _patch_cli_side_effects(monkeypatch)
    uploads = []

    def fake_upload(*args):
        uploads.append(args)

    fake_drive_module = types.ModuleType("integrations.drive")
    fake_drive_module.upload_invoice_to_drive = fake_upload
    monkeypatch.setitem(sys.modules, "integrations.drive", fake_drive_module)
    _install_fake_browser_session(monkeypatch, fake_page, fake_context)

    result = asyncio.run(
        cli.run_provider(
            provider,
            debug=False,
            listar=False,
            todas=True,
            cuenta=None,
            drive_uploader=object(),
            drive_root_id="root-folder",
        )
    )

    assert result is True
    assert provider.saved is True
    assert provider.logged_out is True
    assert provider.download_calls == [(fake_page, fake_context, "123")]
    assert [entry[1] for entry in logged_ok] == ["123"]
    assert logged_errors == []
    assert len(uploads) == 1
    assert uploads[0][3:6] == ("2026-04-01", tmp_path / "123.pdf", "Banco Test")
