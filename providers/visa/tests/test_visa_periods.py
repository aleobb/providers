import asyncio

from providers.visa.periods import extract_period


class _Page:
    def __init__(self, text):
        self.text = text

    async def inner_text(self, _selector):
        return self.text


def test_visa_periods_prefer_full_closing_date():
    assert asyncio.run(
        extract_period(_Page("Fecha de Cierre: 05/06/2026"))
    ) == "2026-06-05"


def test_visa_periods_support_month_name_and_year():
    assert asyncio.run(
        extract_period(_Page("Resumen cerrado en abril 2026"))
    ) == "2026-04"
