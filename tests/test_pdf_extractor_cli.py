import csv
import sys
import types
from types import SimpleNamespace

from integrations.pdf_extractor import cli as pdf_cli
from integrations.pdf_extractor.card_statement import parse_visa_nacion


def test_batch_cli_detects_card_layout_and_writes_csv(
    monkeypatch, tmp_path, capsys
):
    pdf_path = tmp_path / "resumen.pdf"
    pdf_path.write_bytes(b"fake pdf")
    csv_path = tmp_path / "datos.csv"
    text = (
        "VISA\n"
        "CIERRE ACTUAL: 18 Sep 26\n"
        "18 Sep 26 776.977,92 0,00 47.602,00 -,--\n"
        "VTO. ANTERIOR 10 Jun 26 SALDO ANTERIOR $ 56.000,00 "
        "U$S 0,00 PROXIMO CIERRE 30 Jul 26\n"
        "CIERRE ANTERIOR 28 May 26 PAGO MIN. ANT. $ 5.596,00 "
        "PROXIMO VTO. 12 Ago 26"
    )
    provider = SimpleNamespace(
        name="visa",
        display_name="Visa",
        invoice_data_patterns={},
        extract_card_statement_data=parse_visa_nacion,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["pdf-extractor", str(pdf_path), "--csv", str(csv_path)],
    )
    monkeypatch.setattr(
        pdf_cli,
        "_read_text",
        lambda path, *, max_pages: text if max_pages is None else "",
    )
    monkeypatch.setitem(sys.modules, "providers", types.ModuleType("providers"))
    monkeypatch.setattr("core.registry.get_provider", lambda _name: provider)

    assert pdf_cli.main() == 0

    assert "proveedor=Visa" in capsys.readouterr().out
    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["archivo"] == "resumen.pdf"
    assert rows[0]["proveedor"] == "Visa"
    assert rows[0]["banco"] == "Nación"
    assert rows[0]["importe"] == "776977.92"
