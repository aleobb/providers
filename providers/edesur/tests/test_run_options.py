from providers.edesur import EdesurProvider


def test_edesur_applies_its_provider_specific_url_option():
    provider = EdesurProvider()
    url = "https://example.com/invoice"

    provider.apply_run_options(url=url)

    assert provider.get_config().docuprint_url == url
