import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import browser
from core.browser import BrowserSession, browser_channel


def _arch(monkeypatch, system, machine):
    monkeypatch.setattr("core.browser.sys.platform", system)
    monkeypatch.setattr("core.browser.platform.machine", lambda: machine)


def test_channel_default_is_chrome_except_on_linux_arm(monkeypatch):
    monkeypatch.delenv("PROVIDERS_BROWSER_CHANNEL", raising=False)
    _arch(monkeypatch, "win32", "AMD64")
    assert browser_channel() == "chrome"
    _arch(monkeypatch, "darwin", "arm64")
    assert browser_channel() == "chrome"
    _arch(monkeypatch, "linux", "aarch64")
    assert browser_channel() is None


def test_channel_env_wins(monkeypatch):
    _arch(monkeypatch, "linux", "aarch64")
    monkeypatch.setenv("PROVIDERS_BROWSER_CHANNEL", "msedge")
    assert browser_channel() == "msedge"
    monkeypatch.setenv("PROVIDERS_BROWSER_CHANNEL", "chromium")
    assert browser_channel() is None


def _fake_playwright(monkeypatch, launches, fail_first=None):
    class Ctx:
        async def new_page(self):
            return object()

        async def close(self):
            pass

    class Chromium:
        async def launch_persistent_context(self, **options):
            launches.append(dict(options))
            if fail_first and len(launches) == 1:
                raise fail_first
            return Ctx()

    class PW:
        chromium = Chromium()

    class CM:
        async def __aenter__(self):
            return PW()

        async def __aexit__(self, *_):
            pass

    monkeypatch.setattr("core.browser.async_playwright", CM)


def _config(**extra):
    base = dict(
        headless=True,
        browser_stealth=False,
        browser_user_agent=None,
        browser_args=[],
        browser_user_data_dir=None,
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _run(config, profile="prov"):
    async def go():
        async with BrowserSession(config, profile_name=profile):
            pass

    asyncio.run(go())


def test_missing_chrome_falls_back_to_playwright_chromium(monkeypatch, tmp_path):
    monkeypatch.setattr("core.browser._PROFILES_BASE", tmp_path)
    monkeypatch.setenv("PROVIDERS_BROWSER_CHANNEL", "chrome")
    monkeypatch.delenv("PROVIDERS_BROWSER_EXECUTABLE", raising=False)
    launches = []
    error = Exception("Chromium distribution 'chrome' is not found at /opt/google/chrome/chrome")
    _fake_playwright(monkeypatch, launches, fail_first=error)
    _run(_config())
    assert launches[0]["channel"] == "chrome"
    assert "channel" not in launches[1]


def test_other_launch_errors_are_not_swallowed(monkeypatch, tmp_path):
    monkeypatch.setattr("core.browser._PROFILES_BASE", tmp_path)
    monkeypatch.setenv("PROVIDERS_BROWSER_CHANNEL", "chrome")
    _fake_playwright(monkeypatch, [], fail_first=Exception("boom"))
    with pytest.raises(Exception, match="boom"):
        _run(_config())


def test_executable_env_replaces_channel(monkeypatch, tmp_path):
    monkeypatch.setattr("core.browser._PROFILES_BASE", tmp_path)
    monkeypatch.setenv("PROVIDERS_BROWSER_CHANNEL", "chrome")
    monkeypatch.setenv("PROVIDERS_BROWSER_EXECUTABLE", "/usr/bin/chromium")
    launches = []
    _fake_playwright(monkeypatch, launches)
    _run(_config())
    assert launches[0]["executable_path"] == "/usr/bin/chromium"
    assert "channel" not in launches[0]


def test_missing_configured_profile_raises_unless_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr("core.browser._PROFILES_BASE", tmp_path / "base")
    monkeypatch.setenv("PROVIDERS_BROWSER_CHANNEL", "chromium")
    launches = []
    _fake_playwright(monkeypatch, launches)
    config = _config(headless=False, browser_user_data_dir=tmp_path / "no-existe", browser_args=["--x"])

    monkeypatch.delenv("PROVIDERS_PROFILE_FALLBACK", raising=False)
    with pytest.raises(FileNotFoundError):
        _run(config)

    monkeypatch.setenv("PROVIDERS_PROFILE_FALLBACK", "1")
    _run(config, profile="telecentro")
    assert launches[0]["user_data_dir"] == str(tmp_path / "base" / "telecentro")
    assert "--profile-directory=Default" not in launches[0]["args"]


@pytest.mark.skipif(os.name != "posix", reason="SingletonLock solo en POSIX")
def test_profile_in_use_is_reported_and_stale_lock_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr("core.browser._PROFILES_BASE", tmp_path)
    monkeypatch.setenv("PROVIDERS_BROWSER_CHANNEL", "chromium")
    launches = []
    _fake_playwright(monkeypatch, launches)
    profile = tmp_path / "prov"
    profile.mkdir()
    lock = profile / "SingletonLock"

    os.symlink(f"host-{os.getpid()}", lock)
    with pytest.raises(RuntimeError, match="abierto en otro navegador"):
        _run(_config())

    lock.unlink()
    os.symlink("host-999999999", lock)  # pid inexistente: lock viejo
    _run(_config())
    assert len(launches) == 1
