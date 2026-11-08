"""PDF generation. HTML rendering is always tested; actual PDF output needs WeasyPrint's
system libraries (Pango) and is skipped with a clear reason when they are missing."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pymupdf as fitz
import pytest

from app.services import pdf_writer
from app.services.pdf_writer import ImageRef, build_blocks, render_book_html, render_chapter_html

needs_weasyprint = pytest.mark.skipif(
    not pdf_writer.weasyprint_available(),
    reason="WeasyPrint system libraries (Pango) not installed — see README",
)

CONJUNCTS = ["क्षत्रिय", "श्रद्धा", "द्वितीय", "प्रकाश संश्लेषण", "विद्यार्थी", "ज्ञान", "त्रिभुज", "कृषि", "हृदय", "स्त्री"]

STATE = {"book_title": "विज्ञान & \"Science\"", "source_lang": "en", "target_lang": "hi"}


def _para(pid: str, page: int, typ: str, original: str, translated: str | None, level: int | None = None) -> dict:
    return {"id": pid, "page": page, "type": typ, "level": level, "original": original, "translated": translated,
            "flagged": False, "edited": False, "error": translated is None}


CHAPTER = {
    "id": "1", "title": "Chapter 1: Motion", "translated_title": "अध्याय 1: गति",
    "start_page": 1, "end_page": 2, "status": "approved",
    "paragraphs": [
        _para("a", 1, "heading", "Chapter 1", "अध्याय 1", 1),
        _para("b", 1, "heading", "Motion", "गति", 2),
        _para("c", 1, "paragraph", "Kshatriya", " ".join(CONJUNCTS)),
        _para("d", 1, "formula", "2H₂ + O₂ → 2H₂O", "2H₂ + O₂ → 2H₂O"),
        _para("e", 2, "heading", "Speed", "चाल (Speed)", 2),
        _para("f", 2, "list_item", "1. Distance", "1. दूरी"),
        _para("g", 2, "paragraph", "Not yet", None),
    ],
}


def test_blocks_order_images_and_title_dedup() -> None:
    blocks = build_blocks(CHAPTER, [ImageRef(1, "p0001_x5.png", 900), ImageRef(9, "other.png", 100)])
    kinds = [b["kind"] for b in blocks]
    # leading "Chapter 1" / "Motion" headings are dropped (they repeat the chapter title)
    assert kinds == ["paragraph", "formula", "image", "heading", "list_item", "paragraph"]
    img = blocks[2]
    assert img["src"] == "images/p0001_x5.png" and img["width_pt"] == 480  # capped to content width
    assert blocks[1]["text"] == "2H₂ + O₂ → 2H₂O"
    assert blocks[-1]["untranslated"] is True and blocks[-1]["text"] == "Not yet"


def test_chapter_html() -> None:
    html = render_chapter_html(STATE, CHAPTER, [])
    assert '<html lang="hi">' in html
    assert "अध्याय 1: गति" in html and "क्षत्रिय" in html
    assert 'font-family: "Noto Sans Devanagari", "Noto Sans"' in html
    assert "NotoSansDevanagari-Regular.ttf" in html
    assert 'class="formula"' in html and '<h3 class="lvl2">चाल (Speed)</h3>' in html
    assert "&#34;" not in html.split("</style>")[0], "CSS must not be HTML-escaped"
    assert "विज्ञान" not in html.split("</style>")[0], "no book title (e.g. publisher name) in page headers"


def test_book_html_has_contents() -> None:
    ch2 = {**CHAPTER, "id": "2", "translated_title": "अध्याय 2: बल", "title": "Chapter 2: Force"}
    html = render_book_html(STATE, [CHAPTER, ch2], [])
    assert "विषय सूची" in html and 'href="#chapter-1"' in html and 'href="#chapter-2"' in html
    assert "अंग्रेज़ी → हिंदी" in html


def _pdf_text(pdf: bytes) -> str:
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        return "\n".join(p.get_text() for p in doc)
    finally:
        doc.close()


def _fonts(pdf: bytes) -> set[str]:
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        return {f[3] for p in doc for f in p.get_fonts()}
    finally:
        doc.close()


@needs_weasyprint
def test_devanagari_conjuncts_render(tmp_path: Path) -> None:
    pdf = pdf_writer.html_to_pdf(render_chapter_html(STATE, CHAPTER, []), tmp_path)
    assert pdf.startswith(b"%PDF")
    fonts = _fonts(pdf)
    assert any("NotoSansDevanagari" in f.replace("-", "") for f in fonts), fonts


def _render_body(text: str, tmp_path: Path) -> bytes:
    ch = {**CHAPTER, "translated_title": "क", "paragraphs": [_para("x", 1, "paragraph", "x", text)]}
    doc = fitz.open(stream=pdf_writer.html_to_pdf(render_chapter_html(STATE, ch, []), tmp_path), filetype="pdf")
    try:
        return doc[0].get_pixmap(dpi=150, clip=fitz.Rect(40, 120, 555, 220)).samples
    finally:
        doc.close()


@needs_weasyprint
@pytest.mark.parametrize("word", ["क्षत्रिय", "श्रद्धा", "द्वितीय"])
def test_conjuncts_are_shaped(word: str, tmp_path: Path) -> None:
    """With shaping, क्ष is one conjunct glyph; with a ZWNJ after the halant it must instead
    show the explicit halant form. Without shaping (e.g. ReportLab) both look identical."""
    broken = word.replace("्", "्‌")  # forbid every conjunct
    assert _render_body(word, tmp_path) != _render_body(broken, tmp_path)


@needs_weasyprint
def test_book_pdf_with_image(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 40), False)
    pix.set_rect(pix.irect, (30, 120, 200))
    pix.save(str(tmp_path / "images" / "p0001_x5.png"))
    ch2 = {**CHAPTER, "id": "2", "translated_title": "अध्याय 2: बल"}
    pdf = pdf_writer.html_to_pdf(render_book_html(STATE, [CHAPTER, ch2], [ImageRef(1, "p0001_x5.png", 200)]), tmp_path)
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        assert doc.page_count >= 4  # cover, contents, 2 chapters
        assert sum(len(p.get_images()) for p in doc) >= 2
        contents = doc[1].get_text()
        assert "विषय सूची" in contents and "अध्याय 2: बल" in contents
    finally:
        doc.close()


# --- API -----------------------------------------------------------------------------------


def _setup_session(client):  # type: ignore[no-untyped-def]
    from tests.conftest import BODY, make_pdf

    c, root = client
    pages = [[("Chapter 1", 20), (BODY, 11)], [("Chapter 2", 20), (BODY, 11)]]
    sid = c.post("/api/sessions", files={"file": ("my book.pdf", make_pdf(pages))}).json()["session_id"]
    return c, root, sid


def test_pdf_endpoints_status_rules(client) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = _setup_session(client)
    r = c.get(f"/api/sessions/{sid}/chapters/1/pdf")
    assert r.status_code == 409 and r.json()["error"] == "chapter_wrong_status"
    r = c.get(f"/api/sessions/{sid}/book.pdf")
    assert r.status_code == 409 and r.json()["error"] == "no_approved_chapters"


@needs_weasyprint
def test_pdf_endpoints(client) -> None:  # type: ignore[no-untyped-def]
    c, root, sid = _setup_session(client)
    assert c.post(f"/api/sessions/{sid}/chapters/1/translate").status_code == 202
    r = c.get(f"/api/sessions/{sid}/chapters/1/pdf")  # review status is enough for a chapter
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "my_book_ch1_hi.pdf" in r.headers["content-disposition"]
    assert "[HI]" in _pdf_text(r.content)
    assert (root / sid / "outputs" / "chapter_1.pdf").is_file()

    assert c.post(f"/api/sessions/{sid}/chapters/1/approve").status_code == 200
    r = c.get(f"/api/sessions/{sid}/book.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_split_answer() -> None:
    from app.services.pdf_writer import split_answer

    assert split_answer("• Who discovered it first – Robert Bruce Foote") == ("• Who discovered it first", "Robert Bruce Foote")
    assert split_answer("• Pre-historic age – 2500000 BC – 10000 BC – three") == ("• Pre-historic age – 2500000 BC – 10000 BC", "three")
    assert split_answer("No answer here") == ("No answer here", None)
    assert split_answer("well-known hyphen-words") == ("well-known hyphen-words", None)
    assert split_answer("• खेड़ा सत्याग्रह का नेतृत्व किसने किया था -महात्मा गाँधी ने") == (
        "• खेड़ा सत्याग्रह का नेतृत्व किसने किया था", "महात्मा गाँधी ने")


def test_answer_rendered_bold() -> None:
    ch = {**CHAPTER, "paragraphs": [_para("q", 1, "list_item", "x", "• Which age? – The Stone Age")]}
    html = render_chapter_html(STATE, ch, [])
    assert '<span class="q">• Which age?</span>' in html and '<span class="a">– The Stone Age</span>' in html



def test_tables_and_boxes_rendered() -> None:
    from app.services.pdf_writer import build_blocks, parse_table

    assert parse_table("Scholar | Date\nJohn Marshall | 3250 BC 2750 BC\nRagged") == [
        ["Scholar", "Date"], ["John Marshall", "3250 BC 2750 BC"], ["Ragged", ""],
    ]
    paras = [
        _para("t", 1, "table", "विद्वान | तिथि", "Scholar | Date\nJohn Marshall | 3250 BC"),
        {**_para("h", 1, "heading", "विशेष तथ्य", "Special Facts", 3), "group": "b1_0"},
        {**_para("l", 1, "list_item", "1. क", "1. Because they had urban facilities"), "group": "b1_0"},
        _para("q", 1, "list_item", "x", "• After the box – Yes"),
    ]
    ch = {**CHAPTER, "title": "Unrelated", "paragraphs": paras}
    blocks = build_blocks(ch, [])
    assert [b["kind"] for b in blocks] == ["table", "box", "list_item"]
    assert [b["kind"] for b in blocks[1]["blocks"]] == ["heading", "list_item"]
    html = render_chapter_html(STATE, ch, [])
    assert "<th>Scholar</th>" in html and "<td>John Marshall</td>" in html
    assert '<div class="box">' in html and 'class="lvl3 in-box"' in html


@needs_weasyprint
def test_book_layout_pdf_renders(tmp_path: Path) -> None:
    paras = [
        _para("h2", 1, "heading", "x", "General Factual Details", 2),
        _para("h3", 1, "heading", "x", "Discovery of Indus sites", 3),
        _para("q", 1, "list_item", "x", "• In which year was the Harappan Civilization discovered – In the year 1921"),
        _para("t", 1, "table", "x", "Scholar | Date\nJohn Marshall | 3250 BC 2750 BC\nErnest Mackay | 2800 BC 2500 BC"),
        {**_para("b", 1, "heading", "x", "Special Facts", 3), "group": "b1_0"},
        {**_para("b2", 1, "list_item", "x", "1. Because they had urban facilities"), "group": "b1_0"},
    ]
    ch = {**CHAPTER, "title": "Unrelated", "paragraphs": paras}
    pdf = pdf_writer.html_to_pdf(render_chapter_html(STATE, ch, []), tmp_path)
    text = _pdf_text(pdf)
    for s in ["General Factual Details", "In the year 1921", "John Marshall", "Special Facts"]:
        assert s in text, s



def test_table_title_row_spans_columns() -> None:
    from app.services.pdf_writer import table_view

    view = table_view([["", "Major Sites", ""], ["No.", "Name", "Year"], ["1.", "Harappa", "1921"]])
    assert [r["kind"] for r in view] == ["title", "head", "body"]
    assert view[0] == {"kind": "title", "cells": ["Major Sites"], "span": 3}


@needs_weasyprint
def test_preview_endpoints(client) -> None:  # type: ignore[no-untyped-def]
    c, root, sid = _setup_session(client)
    assert c.get(f"/api/sessions/{sid}/chapters/1/preview").status_code == 409  # not translated yet
    assert c.post(f"/api/sessions/{sid}/chapters/1/translate").status_code == 202
    info = c.get(f"/api/sessions/{sid}/chapters/1/preview").json()
    assert info["pages"] >= 1 and info["width_pt"] > 500 and info["version"] > 0
    r = c.get(f"/api/sessions/{sid}/chapters/1/preview/1.png?width=600")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert r.headers["cache-control"] == "no-store"
    assert c.get(f"/api/sessions/{sid}/chapters/1/preview/99.png").json()["error"] == "preview_not_ready"
    assert c.get(f"/api/sessions/{sid}/chapters/1/preview/1.png?width=50").status_code == 422

    assert c.get(f"/api/sessions/{sid}/book/preview").json()["error"] == "no_approved_chapters"
    assert c.post(f"/api/sessions/{sid}/chapters/1/approve").status_code == 200
    book = c.get(f"/api/sessions/{sid}/book/preview").json()
    assert book["pages"] >= 3  # cover, contents, chapter
    assert c.get(f"/api/sessions/{sid}/book/preview/1.png").status_code == 200


def test_chapter_start_prints_each_title_once() -> None:
    from app.services.pdf_writer import chapter_view

    ch = {
        "id": "2", "title": "प्रागैतिहासिक काल", "translated_title": "Prehistoric Period",
        "start_page": 6, "end_page": 6, "status": "review",
        "paragraphs": [
            _para("a", 6, "heading", "प्राचीन इतिहास", "Ancient History", 1),         # part title
            _para("b", 6, "heading", "प्रागैतिहासिक काल", "Prehistoric Period", 1),   # repeats chapter title
            _para("c", 6, "heading", "पुरापाषाण काल", "Paleolithic Period", 2),       # first section
            _para("d", 6, "heading", "पुरापाषाण काल", "Paleolithic Period", 2),       # accidental repeat
            _para("e", 6, "list_item", "x", "• The period without written evidence – Prehistoric Period"),
        ],
    }
    view = chapter_view(ch, [])
    assert view["parts"] == ["Ancient History"]
    assert view["title"] == "Prehistoric Period"
    assert [(b["kind"], b["text"]) for b in view["blocks"]] == [
        ("heading", "Paleolithic Period"),
        ("list_item", "• The period without written evidence – Prehistoric Period"),
    ]
    html = render_chapter_html({**STATE, "target_lang": "en"}, ch, [])
    body = html.split("<body>")[1]
    assert body.count("Prehistoric Period") == 2  # chapter banner + the answer text only
    assert body.count("Ancient History") == 1 and body.index("Ancient History") < body.index("chapter-title")
    assert "प्रागैतिहासिक" not in body
