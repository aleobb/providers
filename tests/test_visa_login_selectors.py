from providers.visa.login import _SELECTOR_GROUPS


def test_visa_login_supports_modern_react_field_names():
    for field in ("documentType", "documentNumber", "username", "password", "code"):
        assert field in _SELECTOR_GROUPS
        assert any(field in selector for selector in _SELECTOR_GROUPS[field])
