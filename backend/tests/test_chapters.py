import pymupdf as fitz

from app.services.pdf_reader import detect_chapters, fixed_chapters, match_chapter_heading
from app.services.text_cleaner import Paragraph
from tests.conftest import BODY, make_pdf


def test_english_chapter_regex() -> None:
    assert match_chapter_heading("Chapter 1") == ("chapter", "1")
    assert match_chapter_heading("CHAPTER ONE") == ("chapter", "one")
    assert match_chapter_heading("Unit 2: Algebra") == ("unit", "2")
    assert match_chapter_heading("Lesson 3 - The Rain") == ("lesson", "3")
    assert match_chapter_heading("UNIT – IV") == ("unit", "iv")
    assert match_chapter_heading("Chapter 12. Light") == ("chapter", "12")


def test_hindi_chapter_regex() -> None:
    assert match_chapter_heading("अध्याय 1") == ("अध्याय", "1")
    assert match_chapter_heading("पाठ 1 : वर्षा") == ("पाठ", "1")
    assert match_chapter_heading("इकाई 3") == ("इकाई", "3")
    assert match_chapter_heading("अध्याय – ५") == ("अध्याय", "5")
    assert match_chapter_heading("पाठ १२") == ("पाठ", "12")  # Devanagari digits
    assert match_chapter_heading("अध्याय दो") == ("अध्याय", "दो")


def test_non_chapters_rejected() -> None:
    for t in ["As seen in this chapter, motion is", "Chapters 1 and 2", "Unitary method", "पाठशाला में", "Lessons learnt"]:
        assert match_chapter_heading(t) is None, t


def test_toc_chapters() -> None:
    pages = [[(BODY, 11)] for _ in range(12)]
    data = make_pdf(pages, toc=[[1, "Motion", 3], [2, "Speed", 4], [1, "Force", 7], [1, "Gravitation", 10]])
    doc = fitz.open(stream=data, filetype="pdf")
    chs = detect_chapters(doc, [], 10)
    assert [(c.title, c.start_page, c.end_page) for c in chs] == [
        ("Front matter", 1, 2), ("Motion", 3, 6), ("Force", 7, 9), ("Gravitation", 10, 12),
    ]
    assert chs[1].method == "toc"


def _para(page: int, text: str, t: str = "heading") -> Paragraph:
    return Paragraph(id=f"p{page}", page=page, type=t, text=text, size=18)  # type: ignore[arg-type]


def test_heading_chapters_with_contents_page_and_title() -> None:
    paras = [
        _para(1, "Contents", "heading"),
        _para(1, "Chapter 1 Motion 1 Chapter 2 Force 5 Chapter 3 Work 9", "paragraph"),
        _para(2, "Chapter 1"), _para(2, "Motion"), _para(2, BODY, "paragraph"),
        _para(5, "Chapter 2"), _para(5, "Force"),
        _para(8, "Some text mentions Chapter 3 in passing.", "paragraph"),
        _para(9, "अध्याय ३ कार्य"),
    ]
    doc = fitz.open(stream=make_pdf([[(BODY, 11)]] * 12), filetype="pdf")
    chs = detect_chapters(doc, paras, 10)
    assert [(c.title, c.start_page, c.end_page) for c in chs] == [
        ("Front matter", 1, 1), ("Chapter 1: Motion", 2, 4), ("Chapter 2: Force", 5, 8), ("अध्याय ३ कार्य", 9, 12),
    ]
    assert chs[1].method == "headings"


def test_fixed_fallback() -> None:
    chs = fixed_chapters(23, 10)
    assert [(c.title, c.start_page, c.end_page) for c in chs] == [
        ("Pages 1–10", 1, 10), ("Pages 11–20", 11, 20), ("Pages 21–23", 21, 23),
    ]
    doc = fitz.open(stream=make_pdf([[(BODY, 11)]] * 23), filetype="pdf")
    assert detect_chapters(doc, [], 10)[0].method == "fixed"


# --- printed contents page --------------------------------------------------------------------

from app.services.pdf_reader import printed_page_offset  # noqa: E402
from app.services.text_cleaner import Block, Line, PageLines  # noqa: E402


def _footer_pages(n: int, offset: int) -> list[PageLines]:
    pages = []
    for i in range(1, n + 1):
        lines = [Line("body", 11, False, (50, 300, 500, 311))]
        if i > offset:
            lines.append(Line(str(i - offset), 9, False, (290, 780, 300, 790)))
        pages.append(PageLines(page=i, width=595, height=842, blocks=[Block(lines, (50, 300, 500, 790))]))
    return pages


def test_printed_page_offset() -> None:
    assert printed_page_offset(_footer_pages(30, 2)) == 2
    assert printed_page_offset(_footer_pages(30, 0)) == 0
    no_numbers = [PageLines(page=i, width=595, height=842, blocks=[]) for i in range(1, 10)]
    assert printed_page_offset(no_numbers) is None


def test_chapters_from_contents_page() -> None:
    contents = [
        _para(2, "विषय सूची", "heading"),
        _para(2, "• प्रागैतिहासिक काल ........................................ 5-10", "list_item"),
        _para(2, "• पुरापाषाण काल • मध्य पाषाण काल • विविध", "list_item"),
        _para(2, "• मौर्य साम्राज्य (322-184 ई. पू. तक) ............................ 11-17", "list_item"),
        _para(3, "Motion and its laws .............. 18", "paragraph"),
        _para(3, "• अन्तिम अध्याय ...................................... 25-29", "list_item"),
    ]
    doc = fitz.open(stream=make_pdf([[(BODY, 11)]] * 32), filetype="pdf")
    chs = detect_chapters(doc, contents, 10, _footer_pages(32, 2))
    assert chs[0].method == "contents"
    assert [(c.title, c.start_page, c.end_page) for c in chs] == [
        ("Front matter", 1, 6),
        ("प्रागैतिहासिक काल", 7, 12),
        ("मौर्य साम्राज्य (322-184 ई. पू. तक)", 13, 19),
        ("Motion and its laws", 20, 26),
        ("अन्तिम अध्याय", 27, 32),
    ]


def test_contents_page_must_be_increasing() -> None:
    contents = [
        _para(2, "A ........ 10", "paragraph"),
        _para(2, "B ........ 5", "paragraph"),
        _para(2, "C ........ 20", "paragraph"),
    ]
    doc = fitz.open(stream=make_pdf([[(BODY, 11)]] * 25), filetype="pdf")
    assert detect_chapters(doc, contents, 10, _footer_pages(25, 0))[0].method == "fixed"
