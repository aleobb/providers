from providers.visa.accounts import _card_dict_to_account


def test_intercepted_account_preserves_issuing_bank():
    account = _card_dict_to_account(
        {
            "cardNumber": "4111111111118947",
            "bankName": "Banco de la cuenta",
            "holderName": "Titular",
        }
    )

    assert account is not None
    assert account.extra["banco"] == "Banco de la cuenta"
    assert "Banco de la cuenta" in account.display_name
