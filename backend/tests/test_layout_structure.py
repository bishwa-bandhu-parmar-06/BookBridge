"""Book structure from drawings: tables, boxes, section bands, sub-headings, footers."""

from app.services.layout import PageLayout, TableGrid
from app.services.text_cleaner import (
    Block,
    Line,
    PageLines,
    _table_rows,
    build_paragraphs,
    is_page_number,
    remove_headers_footers,
    table_to_text,
)


def L(text: str, x0: float, y0: float, x1: float, size: float = 12, bold: bool = False) -> Line:  # noqa: N802
    return Line(text, size, bold, (x0, y0, x1, y0 + 12))


def test_table_rows_from_grid_with_wrapped_cell() -> None:
    grid = TableGrid(bbox=(77, 595, 302, 713), col_x=[77, 171, 302], row_y=[595, 613, 713])
    lines = [
        L("विद्वान", 82, 598, 120, bold=True), L("निर्धारित तिथि", 176, 598, 250, bold=True),
        L("जान मार्शल", 82, 616, 130), L("3250 ई०पू० 2750 ई०पू०", 176, 616, 280),
        L("अर्नेस्ट मैके", 82, 632, 135), L("2800 ई०पू० 2500 ई०पू०", 176, 632, 280),
        L("(अनुमान)", 176, 646, 230),  # wrapped second line of the date cell
        L("फेयर सर्विस", 82, 662, 130), L("2000 ई०पू० 1500 ई०पू०", 176, 662, 275),
    ]
    rows = _table_rows(lines, grid)
    assert rows == [
        ["विद्वान", "निर्धारित तिथि"],
        ["जान मार्शल", "3250 ई०पू० 2750 ई०पू०"],
        ["अर्नेस्ट मैके", "2800 ई०पू० 2500 ई०पू० (अनुमान)"],
        ["फेयर सर्विस", "2000 ई०पू० 1500 ई०पू०"],
    ]
    assert table_to_text(rows).splitlines()[1] == "जान मार्शल | 3250 ई०पू० 2750 ई०पू०"


def test_page_structure_bands_boxes_tables_subheadings() -> None:
    layout = PageLayout(
        bands=[(73, 123, 304, 142)],
        boxes=[(312, 534, 538, 609)],
        tables=[TableGrid(bbox=(77, 595, 302, 713), col_x=[77, 171, 302], row_y=[595, 613, 713])],
    )
    blocks = [
        Block([L("सामान्य तथ्यात्मक विवरण", 123, 126, 259, size=15.9, bold=True)], (123, 126, 259, 138)),
        Block([L("• सैन्धव स्थल की खोज एवं नगर नियोजन", 310, 122, 500, size=12, bold=True)], (310, 122, 500, 134)),
        Block([
            L("•  सिन्धु सभ्यता को आर्यों से पूर्व रखे जाने का कारण", 328, 500, 540),
            L("– मृदभाण्ड", 480, 514, 540, bold=True),
            L("विशेष तथ्य", 390, 538, 450, bold=True),  # inside the box, same PDF block as the answer
            L("1. क्योंकि इनके पास नगरीय सुविधा थी", 330, 556, 520, bold=True),
        ], (310, 500, 540, 570)),
        Block([L("विद्वान", 82, 598, 120, bold=True), L("निर्धारित तिथि", 176, 598, 250, bold=True),
               L("जान मार्शल", 82, 616, 130), L("3250 ई०पू०", 176, 616, 240)], (77, 595, 302, 713)),
    ]
    page = PageLines(page=1, width=612, height=792, blocks=blocks, layout=layout)
    paras = build_paragraphs([page], remove_running=False)
    got = [(p.type, p.level, p.group, p.text) for p in paras]
    assert got == [
        ("heading", 2, None, "सामान्य तथ्यात्मक विवरण"),
        ("heading", 3, None, "सैन्धव स्थल की खोज एवं नगर नियोजन"),
        ("list_item", None, None, "• सिन्धु सभ्यता को आर्यों से पूर्व रखे जाने का कारण – मृदभाण्ड"),
        ("heading", 3, "b1_0", "विशेष तथ्य"),
        ("list_item", None, "b1_0", "1. क्योंकि इनके पास नगरीय सुविधा थी"),
        ("table", None, None, "विद्वान | निर्धारित तिथि\nजान मार्शल | 3250 ई०पू०"),
    ]


def test_footer_variants_removed() -> None:
    assert is_page_number("11`") and is_page_number("‘12’")
    pages = []
    for i in range(1, 8):
        footer = [L("समग्र इतिहास", 72, 719 if i % 2 else 732, 125), L("YCT", 519, 720, 542)]
        if i == 5:
            footer = [L(f"{i} YCT", 480, 725, 542)]  # number and publisher merged into one line
        lines = [L(f"Body text {i}.", 72, 300, 400), *footer]
        pages.append(PageLines(page=i, width=612, height=792, blocks=[Block(lines, (72, 300, 542, 744))]))
    texts = [ln.text for p in remove_headers_footers(pages) for b in p.blocks for ln in b.lines]
    assert texts == [f"Body text {i}." for i in range(1, 8)]


def test_detached_bullet_starts_a_new_point() -> None:
    blocks = [
        Block([
            L("• हड़प्पा स्थल कच्छ क्षेत्र में हैं – देसलपुर", 310, 100, 540),
            L("•", 310, 116, 318),  # bullet reported as its own line
        ], (310, 100, 540, 128)),
        Block([L("धौलावीरा किस द्वीप पर है – खडीर", 328, 118, 540)], (328, 118, 540, 130)),
    ]
    page = PageLines(page=1, width=612, height=792, blocks=blocks)
    texts = [p.text for p in build_paragraphs([page], remove_running=False)]
    assert texts == ["• हड़प्पा स्थल कच्छ क्षेत्र में हैं – देसलपुर", "• धौलावीरा किस द्वीप पर है – खडीर"]


def test_side_by_side_chart_becomes_a_grid() -> None:
    """Page 6 of the YCT book: a chart title, three branches with dates, then questions —
    all stored in ONE PDF block."""
    lines = [
        L("प्रागैतिहासिक काल", 151, 324, 225, bold=True),
        L("निम्नपुरापाषाण युग", 78, 372, 144), L("मध्यपुरापाषाण युग", 155, 372, 219), L("उच्चपुरापाषाण युग", 231, 372, 297),
        L("(2500000 ई.पू. से", 79, 388, 143), L("100000 ई.पू. तक)", 79, 400, 143),
        L("(100000 ई.पू. से", 157, 388, 216), L("40000 ई.पू. तक)", 157, 400, 216),
        L("(40000 ई.पू. से", 236, 388, 291), L("10000 ई.पू. तक)", 234, 400, 293),
        L("•  भारत में सर्वप्रथम किस वर्ष से अनुसंधान प्रारम्भ हुआ", 72, 414, 306),
        L("– 1863 ई० से", 236, 429, 306, bold=True),
    ]
    page = PageLines(page=6, width=612, height=792, blocks=[Block(lines, (72, 324, 306, 443))])
    paras = build_paragraphs([page], remove_running=False)
    assert [(p.type, p.text) for p in paras] == [
        ("table", " | प्रागैतिहासिक काल | \n"
                  "निम्नपुरापाषाण युग | मध्यपुरापाषाण युग | उच्चपुरापाषाण युग\n"
                  "(2500000 ई.पू. से 100000 ई.पू. तक) | (100000 ई.पू. से 40000 ई.पू. तक) | (40000 ई.पू. से 10000 ई.पू. तक)"),
        ("list_item", "• भारत में सर्वप्रथम किस वर्ष से अनुसंधान प्रारम्भ हुआ – 1863 ई० से"),
    ]


def test_question_answer_lines_are_never_a_grid() -> None:
    lines = [
        L("• दधेरी एक परवर्ती हड़प्पीय पुरास्थल है", 328, 642, 459), L("– पंजाब का", 491, 642, 542, bold=True),
        L("• हड़प्पा सभ्यता का सबसे बड़ा पुरास्थल है", 328, 658, 469), L("– राखीगढ़ी", 448, 658, 544, bold=True),
    ]
    page = PageLines(page=1, width=612, height=792, blocks=[Block(lines, (328, 642, 544, 670))])
    assert [p.type for p in build_paragraphs([page], remove_running=False)] == ["list_item", "list_item"]
