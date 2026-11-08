import pymupdf as fitz
import pytest

from app.errors import AppError
from app.services import pdf_reader
from tests.conftest import BODY, devanagari_font, make_pdf

LIMITS = dict(max_bytes=50 * 1024 * 1024, max_mb=50, max_pages=500, min_chars_per_page=50)


def _load(data: bytes, **kw):  # type: ignore[no-untyped-def]
    return pdf_reader.load_pdf(data, **{**LIMITS, **kw})


def _code(data: bytes, **kw) -> str:  # type: ignore[no-untyped-def]
    with pytest.raises(AppError) as ei:
        _load(data, **kw)
    return ei.value.code


def test_rejects_non_pdf() -> None:
    assert _code(b"PK\x03\x04 this is a zip file" * 10) == "not_pdf"


def test_rejects_corrupt_pdf() -> None:
    assert _code(b"%PDF-1.7\n garbage garbage") == "corrupt_pdf"


def test_rejects_too_large() -> None:
    assert _code(make_pdf([[(BODY, 11)]]), max_bytes=100, max_mb=0) == "file_too_large"


def test_rejects_encrypted() -> None:
    assert _code(make_pdf([[(BODY, 11)]], encrypt_password="secret")) == "encrypted_pdf"


def test_rejects_too_many_pages() -> None:
    assert _code(make_pdf([[(BODY, 11)]] * 5), max_pages=3) == "too_many_pages"


def test_rejects_scanned() -> None:
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page()
        page.draw_rect(fitz.Rect(50, 50, 500, 700), fill=(0.8, 0.8, 0.8))  # an "image" of a page
    assert _code(doc.tobytes()) == "scanned_pdf"


def test_rejects_legacy_text() -> None:
    gib = (
        "Hkkjr ,d fo'kky ns'k gSA ;gk¡ dbZ Hkk\"kk,¡ cksyh tkrh gSaA Hkkjr dh laL—fr cgqr iqjkuh gSA "
        "izdk'k la'ys\"k.k ,d tSo jklk;fud izfØ;k gS ftlesa gjs ikS/ks Hkkstu cukrs gSaA"
    )
    assert _code(make_pdf([[(gib, 11), (gib, 11)]] * 3)) == "legacy_font"


def test_english_book_extraction(english_book: bytes) -> None:
    loaded = _load(english_book)
    try:
        assert loaded.analysis.detected_lang == "en"
        texts = [p.text for p in loaded.paragraphs]
        assert not any("Science Textbook" in t for t in texts), "running header should be removed"
        assert not any(t.strip().isdigit() for t in texts), "page numbers should be removed"
        headings = [p for p in loaded.paragraphs if p.type == "heading"]
        assert any(p.text == "Chapter 1" for p in headings)
        chs = pdf_reader.detect_chapters(loaded.doc, loaded.paragraphs, 10)
        assert [(c.start_page, c.end_page) for c in chs] == [(1, 2), (3, 4), (5, 6)]
        assert chs[0].title == "Chapter 1: Topic number 1"
    finally:
        loaded.doc.close()


@pytest.mark.skipif(devanagari_font() is None, reason="no Devanagari font available")
def test_hindi_book_extraction() -> None:
    hi = "प्रकाश संश्लेषण वह प्रक्रिया है जिसमें हरे पौधे सूर्य के प्रकाश की उपस्थिति में भोजन बनाते हैं।"
    data = make_pdf([[("अध्याय 1", 20), (hi, 11), (hi, 11)], [("अध्याय 2", 20), (hi, 11)]], fontfile=devanagari_font())
    loaded = _load(data)
    try:
        assert loaded.analysis.detected_lang == "hi"
        assert any("प्रकाश संश्लेषण" in p.text for p in loaded.paragraphs)
        chs = pdf_reader.detect_chapters(loaded.doc, loaded.paragraphs, 10)
        assert [c.start_page for c in chs] == [1, 2]
    finally:
        loaded.doc.close()


def test_extract_images(tmp_path) -> None:  # type: ignore[no-untyped-def]
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), BODY[:80], fontsize=11)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 90), False)
    pix.set_rect(pix.irect, (200, 30, 30))
    page.insert_image(fitz.Rect(100, 150, 340, 330), pixmap=pix)
    doc2 = fitz.open(stream=doc.tobytes(), filetype="pdf")
    imgs = pdf_reader.extract_images(doc2, tmp_path)
    assert len(imgs) == 1 and imgs[0].page == 1
    assert (tmp_path / imgs[0].file).is_file()
