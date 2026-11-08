"""Scanned books and photos: upload, OCR on translate (mock OCR), and rules."""

from __future__ import annotations

import pymupdf as fitz
import pytest

from app.config import Settings, get_settings
from app.main import app
from app.services import ocr
from app.services.translator.base import InvalidResponseError, parse_ocr_response
from tests.conftest import BODY, make_pdf


def _photo(text_pdf: bytes, fmt: str = "png") -> bytes:
    """A 'photo' of a page: the page rendered to an image."""
    doc = fitz.open(stream=text_pdf, filetype="pdf")
    pix = doc[0].get_pixmap(dpi=60)
    return pix.tobytes(fmt)


def _scanned_pdf(pages: int = 2) -> bytes:
    """A PDF whose pages are only images (no text layer)."""
    img = _photo(make_pdf([[(BODY, 11)]]))
    out = fitz.open()
    for _ in range(pages):
        page = out.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=img)
    return out.tobytes()


def test_parse_ocr_response() -> None:
    blocks = parse_ocr_response('{"blocks": [{"type": "heading", "level": 2, "text": " अध्याय "}, '
                                '{"type": "weird", "text": "x"}, {"type": "list_item", "text": "  "}, '
                                '{"type": "heading", "level": 9, "text": "h"}]}')
    assert blocks == [
        {"type": "heading", "level": 2, "text": "अध्याय"},
        {"type": "paragraph", "level": None, "text": "x"},
        {"type": "heading", "level": 3, "text": "h"},
    ]
    with pytest.raises(InvalidResponseError):
        parse_ocr_response("not json")


def test_images_to_pdf_and_scan_detection() -> None:
    pdf = ocr.images_to_pdf([_photo(make_pdf([[(BODY, 11)]])), _photo(make_pdf([[(BODY, 11)]]), "jpeg")])
    doc = fitz.open(stream=pdf, filetype="pdf")
    assert doc.page_count == 2
    assert ocr.scanned_pages(doc, {1: 0, 2: 0}) == [1, 2]
    assert ocr.scanned_pages(doc, {1: 500, 2: 0}) == [2]  # page 1 has a real text layer
    assert ocr.image_type(b"hello") is None


def test_photo_upload_ocr_and_translate(client) -> None:  # type: ignore[no-untyped-def]
    c, root = client
    photos = [("file", ("page1.jpg", _photo(make_pdf([[(BODY, 11)]]), "jpeg"), "image/jpeg")),
              ("file", ("page2.png", _photo(make_pdf([[(BODY, 11)]])), "image/png"))]
    r = c.post("/api/sessions", files=photos)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page_count"] == 2 and body["source_lang"] == "hi"  # detected by reading page 1 (mock OCR)
    assert any("scanned page" in w for w in body["warnings"])
    sid = body["session_id"]
    assert c.post(f"/api/sessions/{sid}/chapters/1/translate").status_code == 202
    ch = c.get(f"/api/sessions/{sid}/chapters/1").json()
    assert ch["status"] == "review"
    texts = [p["translated"] for p in ch["paragraphs"]]
    assert "[EN] • हड़प्पा सभ्यता की खोज किस वर्ष की गई थी – वर्ष 1921 में" in texts
    assert any(p["type"] == "table" for p in ch["paragraphs"])
    assert len([p for p in ch["paragraphs"] if p["page"] == 2]) == 3  # page 2 read during the job


def test_scanned_pdf_is_accepted_when_ocr_is_available(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    r = c.post("/api/sessions", files={"file": ("scan.pdf", _scanned_pdf(), "application/pdf")}, data={"source_lang": "hi"})
    assert r.status_code == 200, r.text
    assert r.json()["source_lang"] == "hi"


def test_scanned_rejected_without_ocr(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    app.dependency_overrides[get_settings] = lambda: Settings(translator="gemini", gemini_api_key="", _env_file=None)  # type: ignore[call-arg]
    r = c.post("/api/sessions", files={"file": ("scan.pdf", _scanned_pdf(), "application/pdf")})
    assert r.status_code == 400 and r.json()["error"] == "scanned_pdf"
    assert "AI" in r.json()["message"]


def test_bad_uploads(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    assert c.post("/api/sessions", files={"file": ("x.txt", b"hello there", "text/plain")}).json()["error"] == "not_pdf"
    mixed = [("file", ("a.pdf", make_pdf([[(BODY, 11)]]), "application/pdf")),
             ("file", ("b.png", _photo(make_pdf([[(BODY, 11)]])), "image/png"))]
    assert c.post("/api/sessions", files=mixed).json()["error"] == "unsupported_file"


def test_full_page_scans_are_not_copied_as_figures(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from app.services.pdf_reader import extract_images

    doc = fitz.open(stream=_scanned_pdf(1), filetype="pdf")
    assert extract_images(doc, tmp_path) == []


def test_title_from_headings() -> None:
    from app.services.translation import title_from_headings

    part_then_chapter = [
        {"type": "heading", "level": 1, "original": "प्राचीन इतिहास"},
        {"type": "heading", "level": 2, "original": "प्रागैतिहासिक काल"},
        {"type": "list_item", "level": None, "original": "• q – a"},
    ]
    assert title_from_headings(part_then_chapter) == "प्रागैतिहासिक काल"
    assert title_from_headings([{"type": "heading", "level": 2, "original": "पाठ 1"}]) == "पाठ 1"
    assert title_from_headings([{"type": "list_item", "level": None, "original": "x"}]) is None
