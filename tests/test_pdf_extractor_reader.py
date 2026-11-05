from types import SimpleNamespace

from integrations.pdf_extractor import extractor


def test_reader_defaults_to_first_two_pages(monkeypatch, tmp_path):
    pages = [
        SimpleNamespace(extract_text=lambda value=value: value)
        for value in ("página 1", "página 2", "página 3")
    ]

    class FakePdf:
        def __enter__(self):
            return SimpleNamespace(pages=pages)

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(extractor.pdfplumber, "open", lambda _path: FakePdf())

    assert extractor._read_text(tmp_path / "factura.pdf") == "página 1\npágina 2"


def test_reader_can_process_all_pages_for_batch_mode(monkeypatch, tmp_path):
    pages = [
        SimpleNamespace(extract_text=lambda value=value: value)
        for value in ("página 1", "página 2", "página 3")
    ]

    class FakePdf:
        def __enter__(self):
            return SimpleNamespace(pages=pages)

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(extractor.pdfplumber, "open", lambda _path: FakePdf())

    assert (
        extractor._read_text(tmp_path / "factura.pdf", max_pages=None)
        == "página 1\npágina 2\npágina 3"
    )
