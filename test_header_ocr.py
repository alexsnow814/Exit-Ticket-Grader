from types import SimpleNamespace

import fitz
import grader


def test_embedded_header_ignores_question_names():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((30, 40), "Extra")
    page.insert_text((30, 400), "Jane Smith")
    matches = grader.identify_pages(doc.tobytes(), ["Jane Smith"])
    doc.close()
    assert matches[0].student is None
    assert "Jane" not in matches[0].ocr_text


def test_scanned_headers_are_small_and_all_pages_retained(monkeypatch):
    shapes = []
    def recognize(image):
        shapes.append(image.shape)
        return SimpleNamespace(txts=["Jane Smith"] if len(shapes) == 1 else [])
    monkeypatch.setattr(grader, "_ocr_engine", lambda: recognize)
    doc = fitz.open()
    doc.new_page(width=2400, height=3200)
    doc.new_page()
    matches = grader.identify_pages(doc.tobytes(), ["Jane Smith"])
    doc.close()
    assert len(matches) == 2
    assert matches[0].student == "Jane Smith"
    assert matches[1].student is None
    assert all(width <= 1400 and height < 500 for height, width, _ in shapes)


def test_header_import_failure_preserves_page(monkeypatch):
    def unavailable():
        raise ImportError("unavailable")
    monkeypatch.setattr(grader, "_ocr_engine", unavailable)
    doc = fitz.open()
    doc.new_page()
    assert grader.identify_pages(doc.tobytes(), ["Jane Smith"])[0].student is None
    doc.close()
