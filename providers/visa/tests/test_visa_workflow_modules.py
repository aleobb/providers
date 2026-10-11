import asyncio

from core.accounts import Account
from providers.visa.card_selector import CardSelector
from providers.visa.download_strategies import DownloadStrategies
from providers.visa.logout import LogoutService


class _Page:
    url = "https://mistarjetas.example.test/socios/app/"

    async def evaluate(self, _script):
        return "1234"

    def locator(self, _selector):
        raise AssertionError("The active card should not be switched")


def test_card_selector_keeps_the_current_card_selected():
    selector = CardSelector(_Page())

    asyncio.run(selector.select_if_needed(Account("1234", "Visa", "")))


def test_download_strategy_uses_the_first_successful_matching_capture():
    strategy = DownloadStrategies(_Page(), object(), _empty_async_callback)
    entries = [
        {"url": "https://portal.example.test/summary", "status": 404},
        {"url": "https://portal.example.test/statement.pdf", "status": 200},
        {"url": "https://portal.example.test/other.pdf", "status": 200},
    ]

    assert (
        strategy.find_pdf_url_in_captured(entries)
        == "https://portal.example.test/statement.pdf"
    )


def test_logout_success_detection_recognizes_only_logged_out_routes():
    assert LogoutService._logout_succeeded(
        "https://mycards.example.test/"
    )
    assert LogoutService._logout_succeeded(
        "https://mistarjetas.example.test/login"
    )
    assert not LogoutService._logout_succeeded(
        "https://mistarjetas.example.test/socios/app/"
    )


async def _empty_async_callback():
    pass
