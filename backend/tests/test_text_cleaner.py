from app.services.text_cleaner import (
    Block,
    Line,
    PageLines,
    build_paragraphs,
    is_formula,
    is_list_item,
    is_page_number,
    join_lines,
    normalize_text,
    remove_headers_footers,
)


# --- normalisation -------------------------------------------------------------------------

def test_nfc_and_spaces() -> None:
    assert normalize_text("  a  b­ c ") == "a b c"
    assert normalize_text("ﬁnd") == "find"


def test_i_matra_reordered() -> None:
    # extracted in visual order: ि before the consonant
    assert normalize_text("िक") == "कि"
    assert normalize_text("स्िथति") == "स्थिति"  # ि wrongly placed after the halant
    assert normalize_text("िस्थति") == "स्थिति"  # conjunct moved as a whole
    # already-correct text is unchanged
    for word in ["किताब", "स्थिति", "विद्यार्थी", "शिक्षा"]:
        assert normalize_text(word) == word


def test_danda() -> None:
    assert normalize_text("यह पुस्तक है |") == "यह पुस्तक है।"
    assert normalize_text("a | b") == "a | b"


# --- line joining / lists / page numbers ---------------------------------------------------

def test_hyphenation_fixed_for_english() -> None:
    assert join_lines("This is infor-", "mation for you") == "This is information for you"
    assert join_lines("well-", "Known") == "well- Known"
    assert join_lines("पाठ", "दो") == "पाठ दो"


def test_list_items() -> None:
    for t in ["• point", "1. First", "(a) option", "a) option", "(iv) roman", "१. पहला", "(क) विकल्प", "- dash item"]:
        assert is_list_item(t), t
    assert not is_list_item("1.5 kg of sugar")
    assert not is_list_item("Plants make food")


def test_page_numbers() -> None:
    for t in ["12", "- 12 -", "Page 7", "xii", "१२", "पृष्ठ 5"]:
        assert is_page_number(t), t
    assert not is_page_number("Chapter 12")


# --- formulas ------------------------------------------------------------------------------

def test_formulas_detected() -> None:
    for t in ["F = ma", "E = mc²", "2H₂ + O₂ → 2H₂O", "x² + 2x + 1 = 0", "H2SO4", "3.14159", "v = u + at",
              "sin θ = 0.5", "CaCO3 → CaO + CO2", "1,250", "a² + b²"]:
        assert is_formula(t), t


def test_text_is_not_formula() -> None:
    for t in ["Speed = Distance / Time", "बल = द्रव्यमान × त्वरण", "Newton's second law is F = ma for constant mass.",
              "Photosynthesis", "प्रकाश संश्लेषण", "NCERT", "Chapter 1"]:
        assert not is_formula(t), t


# --- headers / footers --------------------------------------------------------------------

def _page(n: int, lines: list[tuple[str, float, float]]) -> PageLines:
    """lines: (text, y0, size)"""
    blocks = [Block(lines=[Line(t, s, False, (50, y, 500, y + s))], bbox=(50, y, 500, y + s)) for t, y, s in lines]
    return PageLines(page=n, width=595, height=842, blocks=blocks)


def test_running_header_and_page_numbers_removed() -> None:
    pages = [
        _page(i, [("Science — Class IX", 20, 9), (f"Body text on page {i}.", 300, 11), (str(i), 815, 9)])
        for i in range(1, 7)
    ]
    cleaned = remove_headers_footers(pages)
    texts = [ln.text for p in cleaned for b in p.blocks for ln in b.lines]
    assert all("Science" not in t for t in texts)
    assert all(not t.isdigit() for t in texts)
    assert len(texts) == 6


def test_alternating_headers_removed_but_sparse_heading_kept() -> None:
    pages = []
    for i in range(1, 41):
        top = "Motion" if i % 2 else "Science"
        lines = [(top, 20, 9), (f"Body {i} text.", 300, 11)]
        if i in (5, 20, 38):
            lines.append(("Exercises", 30, 14))  # top zone, but far apart
        pages.append(_page(i, lines))
    texts = [ln.text for p in remove_headers_footers(pages) for b in p.blocks for ln in b.lines]
    assert "Motion" not in texts and "Science" not in texts
    assert texts.count("Exercises") == 3


# --- full paragraph building ---------------------------------------------------------------

def test_build_paragraphs_types_and_merge() -> None:
    body = 11.0
    p1 = PageLines(page=1, width=595, height=842, blocks=[
        Block([Line("Chapter 1", 20, True, (50, 100, 300, 120))], (50, 100, 300, 120)),
        Block([Line("v = u + at", body, False, (200, 130, 300, 141))], (200, 130, 300, 141)),
        Block([Line("• Speed is scalar", body, False, (50, 150, 300, 161))], (50, 150, 300, 161)),
        Block([
            Line("Motion is a change in the position of an object with", body, False, (50, 200, 500, 211)),
            Line("time. Every object around us is either at rest or in", body, False, (50, 213, 500, 224)),
            Line("motion and we describe it using distance and displace-", body, False, (50, 226, 500, 237)),
            Line("ment over a period of", body, False, (50, 239, 500, 250)),
        ], (50, 200, 500, 250)),
    ])
    p2 = PageLines(page=2, width=595, height=842, blocks=[
        Block([Line("time which we measure in seconds.", body, False, (50, 100, 500, 111))], (50, 100, 500, 111)),
    ])
    paras = build_paragraphs([p1, p2], remove_running=False)
    types = [(p.type, p.text[:20]) for p in paras]
    assert paras[0].type == "heading" and paras[0].level == 1
    assert paras[1].type == "formula"
    assert paras[2].type == "list_item"
    assert paras[3].type == "paragraph"
    assert "displacement over a period of time which we measure" in paras[3].text  # hyphen + page-break merge
    assert len(paras) == 4, types
    assert len({p.id for p in paras}) == len(paras)


# --- question-bank layout ------------------------------------------------------------------------

def _blk(text: str, x0: float, y0: float, x1: float, bold: bool = False, size: float = 11) -> Block:
    return Block([Line(text, size, bold, (x0, y0, x1, y0 + 11))], (x0, y0, x1, y0 + 11))


def test_question_and_answer_are_merged() -> None:
    page = PageLines(page=1, width=595, height=842, blocks=[
        _blk("• जिस काल का कोई लिखित साक्ष्य नहीं प्राप्त होता है, उसे कहते हैं", 70, 100, 300),
        _blk("– प्रागैतिहासिक काल", 200, 113, 300, bold=True),
        _blk("• पुरापाषाण युग से प्राप्त उपकरण किस प्रकार के थे", 70, 140, 300),
        _blk("– क्रोड उपकरण हस्तकुठार विदारणी", 150, 153, 300, bold=True),
        _blk("(क्लीवर) खंडक गड़ासा", 220, 166, 300, bold=True),          # wrapped answer, right-aligned
        _blk("मानव विकास का क्रम", 140, 200, 230, bold=True),             # centred section heading
        _blk("• रामापिथेकस", 100, 225, 200),
    ])
    texts = [(p.type, p.text) for p in build_paragraphs([page], remove_running=False)]
    assert texts == [
        ("list_item", "• जिस काल का कोई लिखित साक्ष्य नहीं प्राप्त होता है, उसे कहते हैं – प्रागैतिहासिक काल"),
        ("list_item", "• पुरापाषाण युग से प्राप्त उपकरण किस प्रकार के थे – क्रोड उपकरण हस्तकुठार विदारणी (क्लीवर) खंडक गड़ासा"),
        ("heading", "मानव विकास का क्रम"),
        ("list_item", "• रामापिथेकस"),
    ]


def test_hyphen_answers_and_wrapped_headings() -> None:
    page = PageLines(page=1, width=595, height=842, blocks=[
        _blk("रौलेट एक्ट और जलियाँवाला", 120, 80, 260, bold=True, size=13),
        _blk("बाग हत्याकांड", 150, 95, 230, bold=True, size=13),
        _blk("• रौलेट एक्ट को किस वर्ष पारित किया गया था", 70, 120, 300),
        _blk("- वर्ष 1919 में", 220, 133, 300, bold=True),
        _blk("• खेड़ा सत्याग्रह का नेतृत्व किसने किया था", 70, 160, 300),
        _blk("-महात्मा गाँधी ने", 200, 173, 300, bold=True),
        _blk("- a normal dash list item", 70, 220, 300),
    ])
    texts = [(p.type, p.text) for p in build_paragraphs([page], remove_running=False)]
    assert texts == [
        ("heading", "रौलेट एक्ट और जलियाँवाला बाग हत्याकांड"),
        ("list_item", "• रौलेट एक्ट को किस वर्ष पारित किया गया था - वर्ष 1919 में"),
        ("list_item", "• खेड़ा सत्याग्रह का नेतृत्व किसने किया था -महात्मा गाँधी ने"),
        ("list_item", "- a normal dash list item"),
    ]


def test_centred_title_below_answer_is_not_merged() -> None:
    page = PageLines(page=1, width=595, height=842, blocks=[
        _blk("• प्रागैतिहासिक काल को कितने भागों में बाँटा गया है – तीन", 72, 301, 306),
        _blk("प्रागैतिहासिक काल", 151, 314, 225, bold=True),  # directly below, but centred
        _blk("• रौलेट एक्ट लाने का क्या प्रयोजन था", 72, 498, 218),
        _blk("-राष्ट्रीय एवं क्रांतिकारी गतिविधियों पर", 159, 514, 310, bold=True),
        _blk("रोक लगाना", 259, 527, 306, bold=True),
    ])
    texts = [p.text for p in build_paragraphs([page], remove_running=False)]
    assert texts == [
        "• प्रागैतिहासिक काल को कितने भागों में बाँटा गया है – तीन",
        "प्रागैतिहासिक काल",
        "• रौलेट एक्ट लाने का क्या प्रयोजन था -राष्ट्रीय एवं क्रांतिकारी गतिविधियों पर रोक लगाना",
    ]
