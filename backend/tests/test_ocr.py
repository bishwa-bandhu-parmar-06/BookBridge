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


def test_scan_detection_variants() -> None:
    """Tiled scans, hidden OCR layers and title-only pages need OCR; blank pages don't."""
    from app.services import pdf_reader

    img = _photo(make_pdf([[(BODY, 11)]]))
    doc = fitz.open()
    tiled = doc.new_page(width=595, height=842)  # page made of 4 image strips
    for k in range(4):
        tiled.insert_image(fitz.Rect(0, 842 * k / 4, 595, 842 * (k + 1) / 4), stream=img)
    layered = doc.new_page(width=595, height=842)  # scan + invisible garbled OCR text
    layered.insert_image(layered.rect, stream=img)
    layered.insert_text((72, 100), "Il1 lI1l ; l1Il garbled " * 10, fontsize=8, render_mode=3)
    title = doc.new_page(width=595, height=842)  # vector "Chapter 1" only, no text layer
    title.draw_rect(fitz.Rect(200, 300, 400, 330), color=(0, 0, 0), fill=(0, 0, 0))
    doc.new_page(width=595, height=842)  # blank
    d2 = fitz.open(stream=doc.tobytes(), filetype="pdf")
    assert pdf_reader.is_invisible_text_layer(d2[1]) and not pdf_reader.is_invisible_text_layer(d2[0])
    book = pdf_reader.extract_book(d2)
    assert book.pages[1].blocks == []  # hidden OCR layer ignored
    assert ocr.scanned_pages(d2, pdf_reader.chars_per_page(book)) == [1, 2, 3]


def test_one_unreadable_page_does_not_stop_the_others(client) -> None:  # type: ignore[no-untyped-def]
    """Page 2 keeps failing: page 3 is still read and saved; the chapter can be continued later."""
    from app.deps import get_translator_dep
    from app.services.translator.base import InvalidResponseError as Bad
    from app.services.translator.mock import MockTranslator

    c, _ = client
    img = _photo(make_pdf([[(BODY, 11)]]))
    files = [("file", (f"p{i}.png", img, "image/png")) for i in range(3)]
    sid = c.post("/api/sessions", files=files, data={"source_lang": "hi"}).json()["session_id"]

    calls = {"n": 0}

    class Flaky(MockTranslator):
        def ocr_image(self, image, mime="image/jpeg"):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            if calls["n"] in (2, 3, 4):  # one page fails all its attempts
                raise Bad("unreadable")
            return super().ocr_image(image, mime)

    import app.services.ocr as ocr_mod

    app.dependency_overrides[get_translator_dep] = lambda: Flaky()
    orig_sleep, orig_conc = ocr_mod.time.sleep, ocr_mod.OCR_CONCURRENCY
    ocr_mod.time.sleep = lambda _s: None  # type: ignore[assignment]
    ocr_mod.OCR_CONCURRENCY = 1  # read pages in order so exactly page 2 keeps failing
    try:
        job = c.post(f"/api/sessions/{sid}/chapters/1/translate").json()["job_id"]
    finally:
        ocr_mod.time.sleep = orig_sleep  # type: ignore[assignment]
        ocr_mod.OCR_CONCURRENCY = orig_conc
    j = c.get(f"/api/jobs/{job}").json()
    assert j["status"] == "failed" and "Continue translation" in j["error"]
    ch = c.get(f"/api/sessions/{sid}/chapters/1").json()
    assert ch["status"] == "failed"

    # Next time everything reads fine: only the missing page is read again, then it translates.
    calls["n"] = 100
    assert c.post(f"/api/sessions/{sid}/chapters/1/translate").status_code == 202
    ch = c.get(f"/api/sessions/{sid}/chapters/1").json()
    assert ch["status"] == "review"
    assert sorted({p["page"] for p in ch["paragraphs"]}) == [1, 2, 3]
    assert calls["n"] == 101  # exactly one extra OCR call: the page that failed


def test_scanned_page_image_in_review(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    img = _photo(make_pdf([[(BODY, 11)]]))
    files = [("file", (f"p{i}.png", img, "image/png")) for i in range(2)]
    sid = c.post("/api/sessions", files=files, data={"source_lang": "hi"}).json()["session_id"]
    assert c.get(f"/api/sessions/{sid}/chapters/1").json()["scanned_pages"] == [1, 2]
    r = c.get(f"/api/sessions/{sid}/pages/2.jpg?width=400")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content[:3] == b"\xff\xd8\xff" and "private" in r.headers["cache-control"]
    assert c.get(f"/api/sessions/{sid}/pages/3.jpg").json()["error"] == "page_not_found"
    assert c.get("/api/sessions/" + "0" * 32 + "/pages/1.jpg").status_code == 404


def test_ocr_tables_keep_cells_and_rows_are_joined() -> None:
    blocks = [
        {"type": "heading", "level": 2, "text": "स्थल"},
        {"type": "table", "level": None, "text": "काल | स्थल"},
        {"type": "table", "level": None, "text": "ताम्रपाषाण | रंगपुर"},
        {"type": "table", "level": None, "text": "पुरापाषाण | सोहन"},
        {"type": "list_item", "level": None, "text": "• प्रश्न – उत्तर"},
        {"type": "table", "level": None, "text": "a | b | c"},
    ]
    paras = ocr.blocks_to_paragraphs(3, blocks)
    assert [p["type"] for p in paras] == ["heading", "table", "list_item", "table"]
    assert paras[1]["text"] == "काल | स्थल\nताम्रपाषाण | रंगपुर\nपुरापाषाण | सोहन"
    one = ocr.blocks_to_paragraphs(1, [{"type": "paragraph", "level": None, "text": "यह वाक्य है |"}])
    assert one[0]["text"] == "यह वाक्य है।"


def test_titled_numbered_boxes_become_heading_and_points() -> None:
    blocks = [{"type": "table", "level": None, "text":
               "संस्कृतियों का क्रम | 1. पैलियोलिथिक | 2. मेसोलिथिक\nबस्तियाँ | 1. राजस्थान | 2. मध्य प्रदेश"}]
    paras = ocr.blocks_to_paragraphs(1, blocks)
    assert [(p["type"], p["text"]) for p in paras] == [
        ("heading", "संस्कृतियों का क्रम"), ("list_item", "1. पैलियोलिथिक"), ("list_item", "2. मेसोलिथिक"),
        ("heading", "बस्तियाँ"), ("list_item", "1. राजस्थान"), ("list_item", "2. मध्य प्रदेश"),
    ]
    assert paras[0]["level"] == 3
    real = ocr.blocks_to_paragraphs(1, [{"type": "table", "level": None, "text": "काल | स्थल\nनवपाषाण | बुर्जहोम"}])
    assert [p["type"] for p in real] == ["table"]
