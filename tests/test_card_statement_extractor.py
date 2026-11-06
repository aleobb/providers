from decimal import Decimal

from integrations.pdf_extractor.card_statement import (
    detect_card_provider,
    parse_mastercard_bbva,
    parse_mastercard_icbc,
    parse_visa_nacion,
    parse_visa_statement,
)


def test_extracts_visa_nacion_statement_fields():
    text = (
        "VISA\n"
        "CIERRE ACTUAL: 18 Sep 26\n"
        "18 Sep 26 776.977,92 0,00 47.602,00 -,--\n"
        "VTO. ANTERIOR 10 Jun 26 SALDO ANTERIOR $ 56.000,00 "
        "U$S 0,00 PROXIMO CIERRE 30 Jul 26\n"
        "CIERRE ANTERIOR 28 May 26 PAGO MIN. ANT. $ 5.596,00 "
        "PROXIMO VTO. 12 Ago 26"
    )

    data = parse_visa_nacion(text)

    assert data is not None
    assert data.bank_name == "Nación"
    assert data.current_due_date == "2026-09-18"
    assert data.next_due_date == "2026-08-12"
    assert data.current_closing_date == "2026-09-18"
    assert data.next_closing_date == "2026-07-30"
    assert data.amount_ars == Decimal("776977.92")
    assert data.amount_usd == Decimal("0.00")
    assert detect_card_provider(text) == "visa"


def test_extracts_visa_nacion_row_with_no_minimum_payment():
    text = (
        "VISA CLASSIC\n"
        "CUENTA NACION AHORRO\n"
        "BEN ALEJANDRO OSVALDO CIERRE ACTUAL: 22 Oct 26\n"
        "JACINTO ROSSO 698 VENCIMIENTO SALDO $ SALDO U$S "
        "PAGO MIN.$ PAGO MIN.U$S\n"
        "1834 TEMPERLEY 04 Nov 26 1,27- 0,00 -,-- -,--\n"
        "VTO. ANTERIOR 0 7 O c t 2 6 SALDO ANTERIOR $ "
        "4 0 4 8 0 , 0 0 U$S 0 , 0 0 PROXIMO CIERRE 19 Nov 26\n"
        "CIERRE ANTERIOR 2 4 S e p 2 6 PAGO MIN. ANT. $ "
        "8 4 8 0 , 0 0 PROXIMO VTO. 02 Dic 26"
    )

    data = parse_visa_statement(text)

    assert data is not None
    assert data.bank_name == "Nación"
    assert data.current_due_date == "2026-11-04"
    assert data.next_due_date == "2026-12-02"
    assert data.current_closing_date == "2026-10-22"
    assert data.next_closing_date == "2026-11-19"
    assert data.amount_ars == Decimal("-1.27")
    assert data.amount_usd == Decimal("0.00")


def test_extracts_mastercard_bbva_statement_fields():
    text = (
        "MASTERCARD BANCO BBVA\n"
        "CIERRE ACTUAL 18-Sep-26\n"
        "VENCIMIENTO ACTUAL 30-Sep-26\n"
        "SALDO ACTUAL $ 10.500,00\n"
        "SALDO ACTUAL U$S 12,25\n"
        "PRÓXIMO CIERRE 20-Oct-26\n"
        "PRÓXIMO VENCIMIENTO 01-Nov-26"
    )

    data = parse_mastercard_bbva(text)

    assert data is not None
    assert data.bank_name == "BBVA"
    assert data.current_due_date == "2026-09-30"
    assert data.next_due_date == "2026-11-01"
    assert data.current_closing_date == "2026-09-18"
    assert data.next_closing_date == "2026-10-20"
    assert data.amount_ars == Decimal("10500.00")
    assert data.amount_usd == Decimal("12.25")
    assert detect_card_provider(text) == "mastercard"


def test_extracts_mastercard_bbva_consolidated_table_layout():
    text = (
        "Mastercard Internacional CONSOLIDADO\n"
        "AVBB\n"
        "ocnaB\n"
        "CIERRE ACTUAL VENCIMIENTO ACTUAL SALDO ACTUAL $ "
        "SALDO ACTUAL U$S PAGO MÍNIMO $\n"
        "29-Oct-26 11-Nov-26 404.204,00 27,56 33.165,00\n"
        "CIERRE ANTERIOR VENCIMIENTO ANTERIOR PRÓXIMO CIERRE "
        "PRÓXIMO VENCIMIENTO\n"
        "Otros períodos\n"
        "01-Oct-26 09-Oct-26 26-Nov-26 09-Dic-26\n"
    )

    data = parse_mastercard_bbva(text)

    assert data is not None
    assert data.bank_name == "BBVA"
    assert data.current_closing_date == "2026-10-29"
    assert data.current_due_date == "2026-11-11"
    assert data.next_closing_date == "2026-11-26"
    assert data.next_due_date == "2026-12-09"
    assert data.amount_ars == Decimal("404204.00")
    assert data.amount_usd == Decimal("27.56")
    assert detect_card_provider(text) == "mastercard"


def test_extracts_mastercard_icbc_statement_fields():
    text = (
        "MASTERCARD ENTIDAD:\n"
        "U$S 0,0018-jun.-26 10-jul.-26\n"
        "100.000,00 5.000,00 datos adicionales\n"
        "0,00 20-jul.-26 10-ago.-26"
    )

    data = parse_mastercard_icbc(text)

    assert data is not None
    assert data.bank_name == "ICBC"
    assert data.current_due_date == "2026-07-10"
    assert data.next_due_date == "2026-08-10"
    assert data.current_closing_date == "2026-06-18"
    assert data.next_closing_date == "2026-07-20"
    assert data.amount_ars == Decimal("100000.00")
    assert data.amount_usd == Decimal("0.00")
    assert detect_card_provider(text) == "mastercard"


def test_extracts_labelled_mastercard_icbc_statement_fields():
    text = (
        "MASTERCARD INTERNACIONAL\n"
        "Estado de cuenta al: 25-jun.-26 "
        "Saldo actual: $ 123.456,78 U$S 12,25\n"
        "Vencimiento actual: 10-jul.-26 Pago Minimo: $ 5.000,00\n"
        "Cierre Anterior: 28-may.-26 Compras Anteriores: $ 100,00 "
        "U$S 1,00 Proximo Cierre: 25-jul.-26\n"
        "Vencimiento Anterior: 10-jun.-26 Pago Minimo Anterior: $ 4.000,00 "
        "Proximo Vencimiento: 10-ago.-26\n"
        "Industrial and Commercial Bank of China (Argentina) S.A.U."
    )

    data = parse_mastercard_icbc(text)

    assert data is not None
    assert data.bank_name == "ICBC"
    assert data.current_due_date == "2026-07-10"
    assert data.next_due_date == "2026-08-10"
    assert data.current_closing_date == "2026-06-25"
    assert data.next_closing_date == "2026-07-25"
    assert data.amount_ars == Decimal("123456.78")
    assert data.amount_usd == Decimal("12.25")
    assert detect_card_provider(text) == "mastercard"


def test_unknown_layout_is_not_assumed_to_be_visa():
    assert parse_visa_nacion("VISA sin datos de resumen") is None
    assert detect_card_provider("un resumen no reconocido") is None


def test_extracts_visa_layout_with_prefixed_due_row_and_spaced_month():
    text = (
        "VISA SIGNATURE\n"
        "CIERRE ACTUAL: 29 Oct 26\n"
        "VENCIMIENTO SALDO $ SALDO U$S PAGO MIN.$ PAGO MIN.U$S\n"
        "CAPITAL 11 Nov 26 123.456,78 0,00 12.345,00 -,--\n"
        "VTO. ANTERIOR 01 O c t 26 SALDO ANTERIOR $ 100,00 "
        "PROXIMO CIERRE 26 Nov 26\n"
        "CIERRE ANTERIOR 20 O c t 26 PAGO MIN. ANT. $ 10,00 "
        "PROXIMO VTO. 04 Dic 26"
    )

    data = parse_visa_statement(text)

    assert data is not None
    assert data.bank_name is None
    assert data.current_due_date == "2026-11-11"
    assert data.next_due_date == "2026-12-04"
    assert data.current_closing_date == "2026-10-29"
    assert data.next_closing_date == "2026-11-26"
    assert data.amount_ars == Decimal("123456.78")
    assert data.amount_usd == Decimal("0.00")
    assert detect_card_provider(text) == "visa"


def test_detects_bbva_from_visa_statement_footer():
    text = (
        "VISA CLASSIC\n"
        "CIERRE ACTUAL: 29 Oct 26\n"
        "VENCIMIENTO SALDO $ SALDO U$S PAGO MIN.$ PAGO MIN.U$S\n"
        "CAP.FEDERAL 11 Nov 26 1.237.599,37 0,03- 80.000,00 -,--\n"
        "VTO. ANTERIOR 09 Oct 26 SALDO ANTERIOR $ 664.510,74 "
        "U$S 3,01 PROXIMO CIERRE 26 Nov 26\n"
        "CIERRE ANTERIOR 01 Oct 26 PAGO MIN. ANT. $ 47.180,00 "
        "PROXIMO VTO. 09 Dic 26\n"
        "Para más información consultá www.bbva.com.ar"
    )

    data = parse_visa_statement(text)

    assert data is not None
    assert data.bank_name == "BBVA"
    assert data.current_due_date == "2026-11-11"
    assert data.amount_usd == Decimal("-0.03")


def test_extracts_visa_balance_when_year_touches_amount_and_usd_has_dash():
    text = (
        "VISA\n"
        "CIERRE ACTUAL: 29 Oct 26\n"
        "VENCIMIENTO SALDO $ SALDO U$S PAGO MIN.$ PAGO MIN.U$S\n"
        "CAPITAL 11 Nov 261.234,56 0,03- 80.000,00 -,--\n"
        "VTO. ANTERIOR 09 Oct 26 SALDO ANTERIOR $ 100,00 "
        "PROXIMO CIERRE 26 Nov 26\n"
        "CIERRE ANTERIOR 01 Oct 26 PAGO MIN. ANT. $ 10,00 "
        "PROXIMO VTO. 09 Dic 26"
    )

    data = parse_visa_statement(text)

    assert data is not None
    assert data.current_due_date == "2026-11-11"
    assert data.amount_ars == Decimal("1234.56")
    assert data.amount_usd == Decimal("-0.03")
    assert data.next_due_date == "2026-12-09"
    assert data.current_closing_date == "2026-10-29"
    assert data.next_closing_date == "2026-11-26"
