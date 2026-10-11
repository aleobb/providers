from providers.visa import VisaProvider


def test_visa_owns_its_invoice_date_format():
    provider = VisaProvider()

    assert provider.extract_invoice_date("CIERRE ACTUAL: 26 Mar 26") == (
        "2026-03-26"
    )
