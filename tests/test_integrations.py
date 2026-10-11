from integrations.drive_naming import get_drive_target
from providers.mastercard import MastercardProvider
from providers.visa import VisaProvider


def test_card_provider_owns_its_drive_naming():
    visa_target = get_drive_target(
        VisaProvider(), "2026-03", banco="Banco de prueba"
    )
    mastercard_target = get_drive_target(
        MastercardProvider(), "2026-04", banco="Banco de prueba"
    )

    assert visa_target.subfolder_parts == [
        "Tarjetas de Credito",
        "Visa",
        "Banco de prueba",
    ]
    assert visa_target.filename == (
        "Visa Banco de prueba - Resumen F.Cierre 2026-03-01.pdf"
    )
    assert mastercard_target.subfolder_parts == [
        "Tarjetas de Credito",
        "Mastercard",
        "Banco de prueba",
    ]
    assert mastercard_target.filename == (
        "Mastercard Banco de prueba - Resumen F.Cierre 2026-04-01.pdf"
    )
