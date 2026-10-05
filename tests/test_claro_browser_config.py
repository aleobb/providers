from providers.claro.config import ClaroConfig


def test_claro_uses_chromes_real_user_agent_without_stealth():
    config = ClaroConfig(email="user@example.com", password="secret")

    assert config.browser_user_agent is None
    assert config.browser_stealth is False
    assert "--disable-blink-features=AutomationControlled" in config.browser_args
