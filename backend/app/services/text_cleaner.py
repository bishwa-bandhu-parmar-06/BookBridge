"""Turn raw PDF lines into clean, typed paragraphs.

Input is a list of `PageLines` (built by pdf_reader from PyMuPDF's get_text("dict")).
Steps:
  1. Unicode normalisation (NFC, matra-order fixes, danda fixes, ligatures)
  2. Remove running headers/footers and page numbers
  3. Rebuild paragraphs from lines inside each block (with English de-hyphenation)
  4. Merge paragraphs that continue across a page break
  5. Classify: heading | paragraph | list_item | formula | table_text
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Literal

from app.services.layout import PageLayout, TableGrid, center_in

ParagraphType = Literal["heading", "paragraph", "list_item", "formula", "table_text", "table"]

# --------------------------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------------------------


@dataclass
class Line:
    text: str
    size: float
    bold: bool
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass
class Block:
    lines: list[Line]
    bbox: tuple[float, float, float, float]


@dataclass
class PageLines:
    page: int  # 1-based
    width: float
    height: float
    blocks: list[Block] = field(default_factory=list)
    #: shaded bands, boxes and ruled tables from the page's drawings (None if not analysed)
    layout: PageLayout | None = None


@dataclass
class Paragraph:
    id: str
    page: int
    type: ParagraphType
    text: str
    size: float
    bold: bool = False
    level: int | None = None  # heading level 1–3
    #: paragraphs inside the same framed box (a note or a diagram) share a group id
    group: str | None = None


# --------------------------------------------------------------------------------------------
# 1. Unicode normalisation
# --------------------------------------------------------------------------------------------

_CONS = r"[क-हक़-य़ॸ-ॿ]"
# "ि" (U+093F) must follow a consonant. PDFs store it in visual order (before the consonant),
# so extraction often yields "िक" instead of "कि". Fix only when ि is NOT preceded by a
# consonant/nukta, so correct text is never changed. Handles conjuncts: "िस्थ" -> "स्थि".
_I_MATRA_RE = re.compile(
    rf"(?<![क-हक़-य़ॸ-ॿ़])ि((?:{_CONS}़?्)*{_CONS}़?)"
)
_DANDA_RE = re.compile(r"(?<=[ऀ-ॿ])\s*\|\|(?=\s|$)")
_SINGLE_DANDA_RE = re.compile(r"(?<=[ऀ-ॿ])\s*\|(?=\s|$)")
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
_SPACES_RE = re.compile(r"[ \t  -   　]+")
_DROP_RE = re.compile(r"[­​﻿\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]")


def normalize_text(s: str) -> str:
    for k, v in _LIGATURES.items():
        s = s.replace(k, v)
    s = _DROP_RE.sub("", s)
    s = unicodedata.normalize("NFC", s)
    s = _I_MATRA_RE.sub(lambda m: m.group(1) + "ि", s)
    s = _DANDA_RE.sub("॥", s)
    s = _SINGLE_DANDA_RE.sub("।", s)
    s = _SPACES_RE.sub(" ", s)
    return s.strip()


# --------------------------------------------------------------------------------------------
# 2. Headers / footers / page numbers
# --------------------------------------------------------------------------------------------

HEADER_ZONE = 0.10  # top 10% of the page
FOOTER_ZONE = 0.12  # bottom 12% (footers sit higher on some pages, e.g. above a closing rule)

_PAGE_NUM_RE = re.compile(
    r"^\s*(?:page|pg\.?|p\.|पृष्ठ|पृ\.?)?\s*[-–—(\[`'‘’\"]?\s*(?:[0-9०-९]{1,4}|[ivxlcdm]{1,7})\s*[-–—)\]`'‘’\"]?\s*$",
    re.IGNORECASE,
)
_DIGITS_RE = re.compile(r"[0-9०-९]+")


def is_page_number(text: str) -> bool:
    return bool(_PAGE_NUM_RE.match(text))


def _repeat_key(text: str) -> str:
    t = _DIGITS_RE.sub("#", text.lower())
    t = re.sub(r"\b[ivxlcdm]{1,7}\b", "#", t)
    return re.sub(r"\s+", " ", t).strip()


def _zone(line: Line, page: PageLines) -> str | None:
    if line.bbox[3] <= page.height * HEADER_ZONE:
        return "top"
    if line.bbox[1] >= page.height * (1 - FOOTER_ZONE):
        return "bottom"
    return None


def remove_headers_footers(pages: list[PageLines]) -> list[PageLines]:
    """Drop page numbers and lines repeated in the header/footer zone across pages.

    A repeated line is removed when it occurs on >= 3 pages AND on at least 40% of the
    pages between its first and last occurrence. This catches running headers that
    alternate on odd/even pages or only cover one chapter, while keeping section headings
    like "Exercises" that happen to sit near the top of a few far-apart pages.
    """
    occurrences: dict[tuple[str, str], set[int]] = defaultdict(set)
    for p in pages:
        for b in p.blocks:
            for ln in b.lines:
                z = _zone(ln, p)
                if z and len(ln.text) <= 150:
                    occurrences[(z, _repeat_key(ln.text))].add(p.page)

    repeated: set[tuple[str, str]] = set()
    for key, pgs in occurrences.items():
        if len(pgs) >= 3:
            span = max(pgs) - min(pgs) + 1
            if len(pgs) / span >= 0.4:
                repeated.add(key)
    # Words of repeated footer lines ("समग्र इतिहास", "YCT"): a zone line made only of these words
    # plus a page number (e.g. "348 YCT") is a footer too.
    repeated_words = {w for _, key in repeated for w in _letters(key).split()}

    out: list[PageLines] = []
    for p in pages:
        new_blocks: list[Block] = []
        for b in p.blocks:
            kept: list[Line] = []
            for ln in b.lines:
                z = _zone(ln, p)
                if z and (is_page_number(ln.text) or (z, _repeat_key(ln.text)) in repeated):
                    continue
                words = _letters(_repeat_key(ln.text)).split()
                if z and words and all(w in repeated_words for w in words):
                    continue
                kept.append(ln)
            if kept:
                new_blocks.append(Block(lines=kept, bbox=b.bbox))
        out.append(PageLines(page=p.page, width=p.width, height=p.height, blocks=new_blocks, layout=p.layout))
    return out


def _letters(text: str) -> str:
    return re.sub(r"[^\w\u0900-\u097F]+|[#\d_]", " ", text).strip()


# --------------------------------------------------------------------------------------------
# 3. Paragraph rebuilding
# --------------------------------------------------------------------------------------------

_LIST_MARKER_RE = re.compile(
    r"^\s*(?:[•●○◦▪▫■□►▶✓✔\-–—*]\s+"
    r"|\(?(?:[0-9०-९]{1,3}|[a-zA-Z]|[ivxIVX]{1,5}|[क-ह])[.)]\s+"
    r"|\((?:[0-9०-९]{1,3}|[a-zA-Z]|[ivxIVX]{1,5}|[क-ह])\)\s*)"
)


def is_list_item(text: str) -> bool:
    return bool(_LIST_MARKER_RE.match(text))


def join_lines(prev: str, nxt: str) -> str:
    """Join two lines of the same paragraph, fixing English hyphenation."""
    if not prev:
        return nxt
    if not nxt:
        return prev
    # "infor-" + "mation" -> "information"  (only when the next line continues in lowercase)
    if re.search(r"[A-Za-z]-$", prev) and re.match(r"[a-z]", nxt):
        return prev[:-1] + nxt
    return prev + " " + nxt


def _sizes_differ(a: float, b: float) -> bool:
    return abs(a - b) > 0.15 * max(a, b)


@dataclass
class _Draft:
    page: int
    text: str
    size: float
    bold: bool
    block_idx: int
    lines: int = 1
    bold_chars: int = 0
    chars: int = 0
    first_bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    last_bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    has_answer: bool = False
    group: str | None = None  # framed box id
    band: bool = False  # sits on a shaded heading band
    is_table: bool = False


def _paragraphs_from_block(page: int, block_idx: int, block: Block, region=None) -> list[_Draft]:  # type: ignore[no-untyped-def]
    """`region(line)` (optional) identifies the box/band a line sits in; a paragraph never
    spans two regions."""
    drafts: list[_Draft] = []
    cur: _Draft | None = None
    prev_line: Line | None = None
    for ln in block.lines:
        text = normalize_text(ln.text)
        if not text:
            continue
        start_new = (
            cur is None
            or (region is not None and prev_line is not None and region(ln) != region(prev_line))
            or _sizes_differ(cur.size, ln.size)
            or is_list_item(text)
            or (prev_line is not None and cur.bold != ln.bold and cur.lines == 1 and len(cur.text) < 100)
        )
        if start_new:
            cur = _Draft(page=page, text=text, size=ln.size, bold=ln.bold, block_idx=block_idx, first_bbox=ln.bbox)
            drafts.append(cur)
        else:
            assert cur is not None
            cur.text = join_lines(cur.text, text)
            cur.lines += 1
        assert cur is not None
        cur.chars += len(text)
        cur.last_bbox = ln.bbox
        if ln.bold:
            cur.bold_chars += len(text)
        prev_line = ln
    for d in drafts:
        d.bold = d.chars > 0 and d.bold_chars / d.chars > 0.6
    return drafts


# Question-bank layout: "• question" followed by "– answer" (usually bold). Some books
# use a plain hyphen for the answer ("-वाराणसी में").
_ANSWER_RE = re.compile(r"^[–—]\s*\S")
_HYPHEN_ANSWER_RE = re.compile(r"^-\s*\S")
_DASH_INSIDE_RE = re.compile(r"\S\s*[–—]\s*\S")


def is_answer_line(text: str) -> bool:
    return bool(_ANSWER_RE.match(text))


def _merge_answers(drafts: list[_Draft], body: float) -> list[_Draft]:
    """Join answers (and wrapped question/answer lines) to their question, so each
    Q&A pair is translated and reviewed as one item."""
    out: list[_Draft] = []
    for d in drafts:
        prev = out[-1] if out else None
        if prev is not None and (prev.group != d.group or prev.is_table or d.is_table or prev.band != d.band):
            prev = None  # never merge across a box, band or table boundary
        if prev is not None and _continues_heading(prev, d, body):
            prev.text = f"{prev.text} {d.text}"
            prev.last_bbox = d.last_bbox
            prev.lines += d.lines
            prev.chars += d.chars
            continue
        if prev is not None and prev.size < body * 1.12 and _joins_previous(prev, d):
            prev.text = f"{prev.text} {d.text}"
            prev.has_answer = prev.has_answer or is_answer_line(d.text) or bool(_HYPHEN_ANSWER_RE.match(d.text))                 or bool(_DASH_INSIDE_RE.search(d.text))
            prev.last_bbox = d.last_bbox
            prev.lines += d.lines
            prev.chars += d.chars
            continue
        if d.text.startswith("•") and _DASH_INSIDE_RE.search(d.text):
            d.has_answer = True  # "• question – answer" printed on one line
        out.append(d)
    return out


def _directly_below(prev: _Draft, d: _Draft) -> bool:
    py0, py1 = prev.last_bbox[1], prev.last_bbox[3]
    return -1 <= d.first_bbox[1] - py1 <= max(py1 - py0, 1.0) * 0.8


def _continues_heading(prev: _Draft, d: _Draft, body: float) -> bool:
    """A heading that wraps onto a second line ("रौलेट एक्ट और जलियाँवाला" / "बाग हत्याकांड")."""
    heading_like = prev.bold and d.bold and (prev.size >= body * 1.12 or prev.lines == 1)
    return (
        heading_like
        and not prev.has_answer
        and abs(prev.size - d.size) <= 0.3
        and prev.size >= body * 0.95
        and len(prev.text) + len(d.text) <= 120
        and not prev.text.startswith("•")
        and not is_list_item(d.text)
        and not is_answer_line(d.text)
        and not _TERMINAL_RE.search(prev.text)
        and _directly_below(prev, d)
        and abs((prev.first_bbox[0] + prev.first_bbox[2]) / 2 - (d.first_bbox[0] + d.first_bbox[2]) / 2) < 60
    )


def _joins_previous(prev: _Draft, d: _Draft) -> bool:
    if is_answer_line(d.text):
        return True
    is_question = prev.text.startswith("•") or prev.has_answer
    if not is_question or len(d.text) > 200 or abs(prev.size - d.size) > 0.6:
        return False
    if _HYPHEN_ANSWER_RE.match(d.text):  # "-answer" / "- answer" (checked before the bullet rule)
        return d.bold and not prev.has_answer
    if is_list_item(d.text):
        return False
    px1 = prev.last_bbox[2]
    x0, x1 = d.first_bbox[0], d.first_bbox[2]
    directly_below = _directly_below(prev, d)
    same_column = x0 >= prev.first_bbox[0] - 2 and x1 <= max(prev.first_bbox[2], px1) + 4
    if not (directly_below and same_column):
        return False
    if prev.has_answer:
        # Wrapped answers are right-aligned under the answer line; a centred diagram or table
        # title directly below an answer is not.
        return d.bold and abs(x1 - px1) <= 6
    return True  # wrapped question line (possibly ending with "– answer")


_TERMINAL_RE = re.compile(r"[.?!।॥:;\"'”’)\]]\s*$")


def _continues(prev: _Draft, nxt: _Draft) -> bool:
    """Does `nxt` (first paragraph of a page) continue `prev` (last paragraph of the previous page)?"""
    if nxt.page != prev.page + 1 or _sizes_differ(prev.size, nxt.size) or prev.bold or nxt.bold:
        return False
    if prev.is_table or nxt.is_table or prev.group or nxt.group or prev.band or nxt.band:
        return False
    if _TERMINAL_RE.search(prev.text) or is_list_item(nxt.text):
        return False
    first = nxt.text[0]
    if first.islower():
        return True
    # Hindi has no case: continue if the previous text ended mid-word/sentence in Devanagari.
    return bool(re.search(r"[ऀ-ॿ,]$", prev.text)) and bool(re.match(r"[ऀ-ॿ]", first))


# --------------------------------------------------------------------------------------------
# 5. Classification
# --------------------------------------------------------------------------------------------

_MATH_CHARS = set("=+−-×÷*/^√∑∫∏π∞≈≠≤≥<>±∆Δ∂→←⇌⇒↔⟶°%²³¹⁰⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉")
_RELATIONS = set("=≈≠≤≥<>→⇌⇒↔⟶")
_NUMERIC_RE = re.compile(r"[0-9०-९\s.,:;+\-−×÷*/=()\[\]%^<>≤≥±√π°'\"²³¹⁰⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]+")
_WORD_RE = re.compile(r"[A-Za-z]{3,}|[ऀ-ॿ]{3,}")
_MATH_FUNCS = {"sin", "cos", "tan", "cot", "sec", "cosec", "csc", "log", "exp", "lim", "max", "min", "mod", "det"}

_SUB = "₀₁₂₃₄₅₆₇₈₉"
_SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻"
_CHEM_TERM = rf"[0-9]*(?:[A-Z][a-z]?[0-9{_SUB}]*|\((?:[A-Z][a-z]?[0-9{_SUB}]*)+\)[0-9{_SUB}]*)+(?:[{_SUP}]+|\^?[0-9]*[+\-])?(?:\s*\((?:s|l|g|aq)\))?"
_CHEM_RE = re.compile(rf"{_CHEM_TERM}(?:\s*(?:\+|→|⟶|⇌|=|->|<->)\s*{_CHEM_TERM})*")


def is_formula(text: str) -> bool:
    """Formulas, equations, chemical formulas and pure numbers. These are never translated."""
    t = text.strip()
    if not t or len(t) > 250:
        return False
    if re.search(r"[0-9०-९]", t) and _NUMERIC_RE.fullmatch(t):
        return True
    if _CHEM_RE.fullmatch(t) and (re.search(rf"[0-9{_SUB}]", t) or re.search(r"\+|→|⟶|⇌|->", t)):
        return True
    words = [w for w in _WORD_RE.findall(t) if w.lower() not in _MATH_FUNCS]
    has_relation = any(c in _RELATIONS for c in t)
    math_count = sum(1 for c in t if c in _MATH_CHARS)
    if has_relation and len(words) <= 1:
        return True
    if not words and math_count >= 1 and re.search(r"[A-Za-z0-9]", t):
        return True
    return False


def _table_blocks(page: PageLines) -> set[int]:
    """Blocks whose lines sit in rows shared with >= 2 other blocks (i.e. table cells)."""
    rows: dict[int, set[int]] = defaultdict(set)
    line_rows: list[tuple[int, int]] = []
    for bi, b in enumerate(page.blocks):
        for ln in b.lines:
            key = round(((ln.bbox[1] + ln.bbox[3]) / 2) / 3)
            rows[key].add(bi)
            line_rows.append((bi, key))
    in_row = Counter()
    total = Counter()
    for bi, key in line_rows:
        total[bi] += 1
        if len(rows[key]) >= 3 or len(rows.get(key - 1, set()) | rows[key] | rows.get(key + 1, set())) >= 3:
            in_row[bi] += 1
    return {bi for bi in total if in_row[bi] / total[bi] >= 0.6}


def compute_body_size(pages: list[PageLines]) -> float:
    counts: Counter[float] = Counter()
    for p in pages:
        for b in p.blocks:
            for ln in b.lines:
                counts[round(ln.size * 2) / 2] += len(ln.text)
    return counts.most_common(1)[0][0] if counts else 10.0


def _is_heading(d: _Draft, body: float) -> bool:
    words = len(d.text.split())
    if d.size >= body * 1.12 and len(d.text) <= 200 and words <= 25:
        return True
    if d.bold and words <= 12 and len(d.text) <= 100 and not re.search(r"[.।]$", d.text):
        return True
    return False


# --------------------------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------------------------


def _table_rows(lines: list[Line], grid: TableGrid) -> list[list[str]]:
    """Rebuild table rows from text lines: columns from the grid, rows by aligned baselines.
    A line that only continues cells of the row above (a wrapped cell) is appended to it."""
    cols = grid.col_x
    ncol = len(cols) - 1

    def col_of(ln: Line) -> int:
        cx = (ln.bbox[0] + ln.bbox[2]) / 2
        return max(0, min(ncol - 1, bisect.bisect(cols, cx) - 1))

    clusters: list[tuple[float, float, dict[int, list[Line]]]] = []  # (cy, height, col -> lines)
    for ln in sorted(lines, key=lambda x: ((x.bbox[1] + x.bbox[3]) / 2, x.bbox[0])):
        cy = (ln.bbox[1] + ln.bbox[3]) / 2
        if clusters and abs(cy - clusters[-1][0]) <= 4:
            clusters[-1][2].setdefault(col_of(ln), []).append(ln)
        else:
            clusters.append((cy, ln.bbox[3] - ln.bbox[1], {col_of(ln): [ln]}))

    rows: list[list[str]] = []
    prev_cols: set[int] = set()
    prev_y = None
    for cy, h, cells in clusters:
        texts = {c: normalize_text(" ".join(x.text for x in sorted(v, key=lambda x: x.bbox[0]))) for c, v in cells.items()}
        crossed_rule = prev_y is not None and any(prev_y < ry < cy for ry in grid.row_y)
        wrapped = (
            rows and not crossed_rule and len(texts) < ncol and set(texts) <= prev_cols
            and prev_y is not None and cy - prev_y <= max(h, 8) * 1.6
        )
        if wrapped:
            for c, t in texts.items():
                rows[-1][c] = f"{rows[-1][c]} {t}".strip()
        else:
            row = [""] * ncol
            for c, t in texts.items():
                row[c] = t
            rows.append(row)
            prev_cols = set(texts)
        prev_y = cy
    return [r for r in rows if any(c.strip() for c in r)]


_NOT_GRID_START = ("•", "–", "—", "-", "❑", "❖")


def columnar_grid(block: Block) -> TableGrid | None:
    """A block whose short lines sit side by side in aligned columns (e.g. a branching chart:
    "निम्नपुरापाषाण युग | मध्यपुरापाषाण युग | उच्चपुरापाषाण युग" with dates under each).
    Returns a grid to rebuild it as a table, or None for ordinary text.

    Question–answer lines ("• question" + "– answer" on one baseline) are never grids.
    """
    lines = [ln for ln in block.lines if ln.text.strip()]
    if len(lines) < 4 or any(ln.text.lstrip().startswith(_NOT_GRID_START) for ln in lines):
        return None
    if any(len(ln.text) > 80 for ln in lines):
        return None
    rows: list[list[Line]] = []
    for ln in sorted(lines, key=lambda x: ((x.bbox[1] + x.bbox[3]) / 2, x.bbox[0])):
        cy = (ln.bbox[1] + ln.bbox[3]) / 2
        if rows and abs(cy - (rows[-1][0].bbox[1] + rows[-1][0].bbox[3]) / 2) <= 3:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    multi = [sorted(r, key=lambda x: x.bbox[0]) for r in rows if len(r) >= 2]
    if len(multi) < 2:
        return None
    ncol = len(multi[0])
    if not 2 <= ncol <= 6 or any(len(r) != ncol for r in multi):
        return None
    centers = [sum((r[i].bbox[0] + r[i].bbox[2]) / 2 for r in multi) / len(multi) for i in range(ncol)]
    for r in multi:
        for i, ln in enumerate(r):
            if abs((ln.bbox[0] + ln.bbox[2]) / 2 - centers[i]) > 25:
                return None  # not aligned in columns
        if any(r[i + 1].bbox[0] - r[i].bbox[2] < 6 for i in range(ncol - 1)):
            return None  # words of one sentence, not separate columns
    x0 = min(ln.bbox[0] for ln in lines) - 1
    x1 = max(ln.bbox[2] for ln in lines) + 1
    bounds = [(centers[i] + centers[i + 1]) / 2 for i in range(ncol - 1)]
    y0 = min(ln.bbox[1] for ln in lines)
    y1 = max(ln.bbox[3] for ln in lines)
    return TableGrid(bbox=(x0, y0, x1, y1), col_x=[x0, *bounds, x1], row_y=[])


def _split_at_points(block: Block) -> list[Block]:
    """Split a block's lines (in their stored order) before each bullet / numbered point."""
    segs: list[list[Line]] = []
    for ln in block.lines:
        if not segs or is_list_item(normalize_text(ln.text)):
            segs.append([ln])
        else:
            segs[-1].append(ln)
    return [Block(lines=ls, bbox=block.bbox) for ls in segs]


def _join_open_brackets(rows: list[list[str]]) -> list[list[str]]:
    """Rows whose cells all open a bracket that the next row closes are one row:
    "(2500000 ई.पू. से" + "100000 ई.पू. तक)" → "(2500000 ई.पू. से 100000 ई.पू. तक)"."""
    out: list[list[str]] = []
    for r in rows:
        prev = out[-1] if out else None
        filled = [c for c in prev if c] if prev else []
        if prev and filled and all(c.count("(") > c.count(")") for c in filled):
            out[-1] = [f"{a} {b}".strip() for a, b in zip(prev, r)]
        else:
            out.append(list(r))
    return out


def table_to_text(rows: list[list[str]]) -> str:
    """Tables travel through translation as rows of "cell | cell" lines."""
    return "\n".join(" | ".join(c.replace("|", "/") for c in row) for row in rows)


_BULLET_ONLY = {"•", "❖", "❑", "■", "●", "▪", "◦", "➢", "►"}


def attach_bullets(p: PageLines) -> PageLines:
    """PDFs sometimes place a bullet glyph as its own line just left of the text it belongs to
    (even in another text block). Join it to that text so the item starts a new point."""
    lines = [(bi, li, ln) for bi, b in enumerate(p.blocks) for li, ln in enumerate(b.lines)]
    bullets = [(bi, li, ln) for bi, li, ln in lines if ln.text.strip() in _BULLET_ONLY]
    if not bullets:
        return p
    drop: set[tuple[int, int]] = set()
    prefix: dict[tuple[int, int], str] = {}
    for bi, li, bl in bullets:
        cy = (bl.bbox[1] + bl.bbox[3]) / 2
        best = None
        for bj, lj, ln in lines:
            if (bj, lj) == (bi, li) or ln.text.strip() in _BULLET_ONLY or (bj, lj) in prefix:
                continue
            ly = (ln.bbox[1] + ln.bbox[3]) / 2
            gap = ln.bbox[0] - bl.bbox[2]
            if abs(ly - cy) <= 5 and -2 <= gap <= 35 and (best is None or gap < best[0]):
                best = (gap, bj, lj)
        if best is not None:
            prefix[(best[1], best[2])] = "• "
            drop.add((bi, li))
    blocks: list[Block] = []
    for bi, b in enumerate(p.blocks):
        new_lines = []
        for li, ln in enumerate(b.lines):
            if (bi, li) in drop:
                continue
            if (bi, li) in prefix:
                bx = ln.bbox
                ln = Line(text=prefix[(bi, li)] + ln.text.lstrip("•❖❑ ").strip(), size=ln.size, bold=ln.bold,
                          bbox=(bx[0] - 12, bx[1], bx[2], bx[3]))
            new_lines.append(ln)
        if new_lines:
            blocks.append(Block(lines=new_lines, bbox=b.bbox))
    return PageLines(page=p.page, width=p.width, height=p.height, blocks=blocks, layout=p.layout)


def _page_drafts(p: PageLines, body: float) -> list[_Draft]:
    """Drafts for one page: tables rebuilt from their grid, every other block as paragraphs;
    each draft tagged with its framed box (group) and shaded band."""
    p = attach_bullets(p)
    layout = p.layout
    tables = layout.tables if layout else []
    table_lines: dict[int, list[Line]] = {}
    table_first_block: dict[int, int] = {}
    blocks: list[Block | None] = []
    for bi, b in enumerate(p.blocks):
        keep: list[Line] = []
        for ln in b.lines:
            ti = next((k for k, t in enumerate(tables) if center_in(t.bbox, ln.bbox, 2.0)), None)
            if ti is None:
                keep.append(ln)
            else:
                table_lines.setdefault(ti, []).append(ln)
                table_first_block.setdefault(ti, bi)
        blocks.append(Block(lines=keep, bbox=b.bbox) if keep else None)

    def region(ln: Line) -> tuple[int | None, bool]:
        if not layout:
            return (None, False)
        box = next((k for k, bx in enumerate(layout.boxes) if center_in(bx, ln.bbox, 2.0)), None)
        return (box, any(center_in(bd, ln.bbox, 2.0) for bd in layout.bands))

    out: list[_Draft] = []
    for bi, b in enumerate(blocks):
        for ti, first in table_first_block.items():
            if first == bi:
                rows = _table_rows(table_lines[ti], tables[ti])
                if rows:
                    t = tables[ti]
                    out.append(_Draft(
                        page=p.page, text=table_to_text(rows), size=body, bold=False, block_idx=bi,
                        first_bbox=t.bbox, last_bbox=t.bbox, is_table=True,
                    ))
        if b is not None:
            # A PDF block can hold a side-by-side chart *and* the questions after it, so look
            # for column grids in the pieces between bullet points.
            for seg in _split_at_points(b):
                grid = columnar_grid(seg)
                rows = _join_open_brackets(_table_rows(seg.lines, grid)) if grid else []
                if grid and len(rows) >= 2:
                    out.append(_Draft(
                        page=p.page, text=table_to_text(rows), size=body, bold=False, block_idx=bi,
                        first_bbox=grid.bbox, last_bbox=grid.bbox, is_table=True,
                    ))
                else:
                    out.extend(_paragraphs_from_block(p.page, bi, seg, region))

    if layout:
        for d in out:
            if d.is_table:
                continue
            box = next((k for k, bx in enumerate(layout.boxes) if center_in(bx, d.first_bbox, 2.0)), None)
            d.group = f"b{p.page}_{box}" if box is not None else None
            d.band = any(center_in(bd, d.first_bbox, 2.0) for bd in layout.bands)
    return out


def _heading_level(size: float, frequent_sizes: list[int]) -> int:
    """1 + number of commonly used heading sizes bigger than this one (capped at 3). Sizes used
    only once or twice (a cover page's giant title) do not push real headings down."""
    bigger = sum(1 for f in frequent_sizes if f > round(size))
    return min(1 + bigger, 3)


def build_paragraphs(pages: list[PageLines], remove_running: bool = True) -> list[Paragraph]:
    if remove_running:
        pages = remove_headers_footers(pages)
    body = compute_body_size(pages)

    drafts: list[_Draft] = []
    table_flags: set[tuple[int, int]] = set()
    for p in pages:
        for bi in _table_blocks(p):
            table_flags.add((p.page, bi))
        page_drafts = _merge_answers(_page_drafts(p, body), body)
        # 4. merge across page break
        if drafts and page_drafts and _continues(drafts[-1], page_drafts[0]):
            drafts[-1].text = join_lines(drafts[-1].text, page_drafts[0].text)
            page_drafts = page_drafts[1:]
        drafts.extend(page_drafts)

    size_counts = Counter(round(d.size) for d in drafts if d.size >= body * 1.12 and not d.is_table)
    frequent_sizes = sorted((s for s, c in size_counts.items() if c >= 3), reverse=True)

    out: list[Paragraph] = []
    per_page: Counter[int] = Counter()
    for d in drafts:
        ptype: ParagraphType
        level: int | None = None
        text = d.text
        if d.is_table:
            ptype = "table"
        elif d.band and len(text) <= 160:
            ptype, level = "heading", 2
            text = re.sub(r"^[•❑]\s*", "", text)
        elif is_formula(text):
            ptype = "formula"
        elif (d.page, d.block_idx) in table_flags and len(text) < 200:
            ptype = "table_text"
        elif is_list_item(text):
            if d.bold and text.startswith("•") and not d.has_answer and len(text) <= 140:
                # "❑ Sub-heading" (a dingbat box + bold text) — not a question
                ptype, level = "heading", 3
                text = re.sub(r"^•\s*", "", text)
            else:
                ptype = "list_item"
        elif _is_heading(d, body):
            ptype = "heading"
            level = _heading_level(d.size, frequent_sizes) if d.size >= body * 1.12 else 3
        else:
            ptype = "paragraph"
        per_page[d.page] += 1
        out.append(
            Paragraph(
                id=f"p{d.page:04d}_{per_page[d.page]:03d}",
                page=d.page,
                type=ptype,
                text=text,
                size=d.size,
                bold=d.bold,
                level=level,
                group=d.group,
            )
        )
    return out
