import asyncio
from types import SimpleNamespace

from playwright.async_api import TimeoutError as PlaywrightTimeout

from core.exceptions import DownloadError
from providers.claro.invoice import InvoiceService


class _Popup:
    def __init__(self, url, target_url=None):
        self.url = url
        self.target_url = target_url
        self.closed = False

    async def wait_for_url(self, predicate, *, timeout, wait_until):
        assert timeout == 15000
        assert wait_until == "domcontentloaded"
        if self.target_url and predicate(self.target_url):
            self.url = self.target_url
            return
        raise PlaywrightTimeout("popup URL timeout")

    async def close(self):
        self.closed = True


class _PopupExpectation:
    def __init__(self, popup):
        self.popup = popup

    @property
    def value(self):
        async def get_popup():
            return self.popup

        return get_popup()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Page:
    def __init__(self, popup):
        self.popup = popup
        self.clicked = False

    async def wait_for_selector(self, _selector, *, timeout):
        assert timeout == 1000

    def expect_popup(self, *, timeout):
        assert timeout == 15000
        return _PopupExpectation(self.popup)

    async def click(self, _selector):
        self.clicked = True


def _service(popup):
    page = _Page(popup)
    service = InvoiceService(
        page,
        SimpleNamespace(timeout_ms=1000),
    )
    return service, page


def test_claro_download_waits_for_popup_navigation_from_about_blank():
    popup = _Popup(
        "about:blank",
        "https://m-miclaro.claro.com.ar/factura/back/public/facturas/ultima?t=abc",
    )
    service, page = _service(popup)

    url = asyncio.run(service._click_download_and_capture_url())

    assert page.clicked is True
    assert url.endswith("/facturas/ultima?t=abc")
    assert popup.closed is True


def test_claro_download_reports_popup_that_never_navigates():
    popup = _Popup("about:blank")
    service, _page = _service(popup)

    try:
        asyncio.run(service._click_download_and_capture_url())
    except DownloadError as error:
        assert "se abrió, pero no navegó" in str(error)
        assert "about:blank" in str(error)
    else:
        raise AssertionError("Expected DownloadError for blank popup")

    assert popup.closed is True
