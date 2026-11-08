"""PDF validation, text extraction, language / legacy-font checks, images and chapter splitting."""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pymupdf as fitz  # PyMuPDF

from app import errors
from app.services.language import (
    Lang,
    LegacyTextStats,
    detect_language,
    is_legacy_font_name,
    legacy_text_stats,
    normalise_font_name,
    private_use_ratio,
)
from app.services.layout import analyze_page
from app.services.ocr import scanned_pages
from app.services.legacy_font_converter import LegacyFontConverter, get_converter
from app.services.text_cleaner import Block, Line, PageLines, Paragraph, build_paragraphs

log = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"

# A line counts as bold if most of its characters are in a bold span.
_BOLD_FLAG = 1 << 4

# Share of characters in legacy fonts above which we reject the book.
LEGACY_CHAR_SHARE = 0.20
PUA_MAX_RATIO = 0.05


# --------------------------------------------------------------------------------------------
# Byte-level validation & opening
# --------------------------------------------------------------------------------------------


def check_pdf_bytes(data: bytes, max_bytes: int, max_mb: int) -> None:
    if len(data) > max_bytes:
        raise errors.too_large(max_mb)
    # The PDF spec allows a little junk before the header; real files have it at offset 0.
    if PDF_MAGIC not in data[:1024]:
        raise errors.not_pdf()


def open_pdf(data: bytes) -> fitz.Document:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:  # noqa: BLE001 - any parse failure is a corrupt file for the user
        raise errors.corrupt_pdf() from None
    # PDFs with only an owner password (print/copy restrictions) open fine and have
    # needs_pass == False; only reject PDFs that need a password to be read at all.
    if doc.needs_pass:
        doc.close()
        raise errors.encrypted_pdf()
    if doc.page_count == 0:
        doc.close()
        raise errors.empty_pdf()
    return doc


# --------------------------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------------------------


@dataclass
class ExtractedBook:
    page_count: int
    pages: list[PageLines]
    font_chars: Counter[str] = field(default_factory=Counter)  # normalised font name -> chars
    font_display: dict[str, str] = field(default_factory=dict)  # normalised -> display name
    total_chars: int = 0

    def sample_text(self, limit: int = 300_000) -> str:
        parts: list[str] = []
        n = 0
        for p in self.pages:
            for b in p.blocks:
                for ln in b.lines:
                    parts.append(ln.text)
                    n += len(ln.text)
                    if n >= limit:
                        return "\n".join(parts)
        return "\n".join(parts)


_DINGBAT_FONTS = ("wingdings", "webdings", "zapfdingbats", "dingbats")


def _symbol_text(font: str, text: str) -> str:
    """Bullets from Symbol/Wingdings fonts become "• " so lines are recognised as list items."""
    f = font.lower()
    if any(d in f for d in _DINGBAT_FONTS):
        return "• " if text.strip() else text
    if "symbol" in f and text.strip() in ("•", "·", ""):
        return "• "
    return text


INVISIBLE_SHARE = 0.8


def is_invisible_text_layer(page: fitz.Page) -> bool:
    """True when (nearly) all text on the page is invisible (PDF text render mode 3)."""
    if not page.get_images():
        return False  # hidden OCR layers always sit on top of a scanned image
    try:
        trace = page.get_texttrace()
    except Exception:  # noqa: BLE001
        return False
    total = invisible = 0
    for span in trace:
        n = len(span.get("chars", ()))
        total += n
        if span.get("type") == 3 or span.get("opacity", 1) == 0:
            invisible += n
    return total > 0 and invisible / total >= INVISIBLE_SHARE


def _page_lines(page: fitz.Page, page_no: int, font_chars: Counter[str], font_display: dict[str, str]) -> PageLines:
    flags = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP
    data = page.get_text("dict", flags=flags)
    rect = page.rect
    pl = PageLines(page=page_no, width=rect.width, height=rect.height, layout=analyze_page(page))
    if is_invisible_text_layer(page):
        # A scanner's hidden OCR layer ("searchable PDF"): often garbled, especially for Hindi.
        # Ignore it; the page is read again with our OCR.
        return pl
    for blk in data.get("blocks", []):
        if blk.get("type", 0) != 0:
            continue
        lines: list[Line] = []
        for ln in blk.get("lines", []):
            dx, dy = ln.get("dir", (1.0, 0.0))
            if abs(dy) > 0.1 or dx < 0:  # rotated / vertical text: watermarks, margin notes
                continue
            text_parts: list[str] = []
            size_weight = 0.0
            bold_chars = 0
            chars = 0
            # Consecutive spans in the same legacy font family are converted together,
            # so a syllable split across bold/regular spans still converts correctly.
            run: list[str] = []
            run_conv: LegacyFontConverter | None = None

            def flush_run() -> None:
                nonlocal run, run_conv
                if run and run_conv is not None:
                    text_parts.append(run_conv.convert("".join(run)))
                run, run_conv = [], None

            for sp in ln.get("spans", []):
                t = sp.get("text", "")
                if not t:
                    continue
                n = len(t.strip())
                chars += n
                size_weight += sp.get("size", 0.0) * n
                font = sp.get("font", "")
                if sp.get("flags", 0) & _BOLD_FLAG or "bold" in font.lower():
                    bold_chars += n
                if n:
                    key = normalise_font_name(font)
                    font_chars[key] += n
                    font_display.setdefault(key, font)
                conv = get_converter(font)
                if conv is not None:
                    if run_conv is not None and run_conv is not conv:
                        flush_run()
                    run.append(t)
                    run_conv = conv
                    continue
                flush_run()
                text_parts.append(_symbol_text(font, t))
            flush_run()
            text = "".join(text_parts).strip()
            if not text or chars == 0:
                continue
            lines.append(
                Line(
                    text=text,
                    size=size_weight / chars,
                    bold=bold_chars / chars > 0.6,
                    bbox=tuple(ln["bbox"]),  # type: ignore[arg-type]
                )
            )
        if lines:
            pl.blocks.append(Block(lines=lines, bbox=tuple(blk["bbox"])))  # type: ignore[arg-type]
    return pl


def extract_book(doc: fitz.Document) -> ExtractedBook:
    book = ExtractedBook(page_count=doc.page_count, pages=[])
    for i, page in enumerate(doc):
        book.pages.append(_page_lines(page, i + 1, book.font_chars, book.font_display))
    book.total_chars = sum(book.font_chars.values())
    return book


# --------------------------------------------------------------------------------------------
# Analysis (scanned / legacy / language)
# --------------------------------------------------------------------------------------------


@dataclass
class FontUsage:
    name: str
    chars: int
    legacy: bool
    #: legacy font whose text is converted to Unicode automatically
    converted: bool = False


@dataclass
class PdfAnalysis:
    page_count: int
    detected_lang: Lang
    devanagari_ratio: float
    avg_chars_per_page: float
    fonts: list[FontUsage]
    legacy_fonts: list[str]  # legacy fonts that could NOT be converted
    legacy_text: LegacyTextStats
    converted_fonts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: pages that are images of text and will be read with OCR
    scan_pages: list[int] = field(default_factory=list)
    #: False when there was too little text to tell the language (a scanned book)
    language_known: bool = True


def chars_per_page(book: ExtractedBook) -> dict[int, int]:
    return {p.page: sum(len(ln.text.strip()) for b in p.blocks for ln in b.lines) for p in book.pages}


def analyze_book(book: ExtractedBook, min_chars_per_page: int, scan_pages: list[int] | None = None) -> PdfAnalysis:
    """Run all content checks. Raises AppError for unsupported books. `scan_pages` (pages that
    will be read with OCR) lets an image-only / mostly-scanned book through."""
    scan_pages = scan_pages or []
    """Run all content checks. Raises AppError for unsupported books."""
    avg = book.total_chars / max(book.page_count, 1)

    fonts = []
    for k, c in book.font_chars.most_common():
        name = book.font_display[k]
        converted = get_converter(name) is not None
        fonts.append(FontUsage(name=name, chars=c, legacy=is_legacy_font_name(k) or converted, converted=converted))
    legacy_fonts = [f.name for f in fonts if f.legacy and not f.converted]
    converted_fonts = [f.name for f in fonts if f.converted]
    legacy_chars = sum(f.chars for f in fonts if f.legacy and not f.converted)

    sample = book.sample_text()  # already converted to Unicode where a converter exists
    guess = detect_language(sample)
    lt = legacy_text_stats(sample)

    if avg < min_chars_per_page and not scan_pages:
        raise errors.scanned_pdf()

    if private_use_ratio(sample) > PUA_MAX_RATIO:
        raise errors.unreadable_encoding()

    warnings: list[str] = []
    legacy_share = legacy_chars / max(book.total_chars, 1)
    if legacy_share > LEGACY_CHAR_SHARE and guess.lang != "hi":
        raise errors.legacy_font(legacy_fonts)
    if guess.lang != "hi" and lt.is_legacy:
        raise errors.legacy_font(legacy_fonts)
    if legacy_fonts:
        warnings.append(
            f"Some text uses legacy Hindi fonts ({', '.join(legacy_fonts[:3])}); that part may not extract correctly."
        )
    if converted_fonts:
        families = sorted({_family(f) for f in converted_fonts})
        warnings.append(
            f"This book uses an old non-Unicode Hindi font ({', '.join(families)}). Its text was converted "
            "to Unicode automatically; rare letters may need a manual fix in the review."
        )

    language_known = guess.lang is not None
    if not language_known and not scan_pages:
        raise errors.unsupported_language()
    if scan_pages:
        warnings.append(
            f"{len(scan_pages)} scanned page(s) will be read with AI (OCR) when you translate them. "
            "This takes a little longer, and the reading may have small mistakes — check them in the review."
        )

    return PdfAnalysis(
        page_count=book.page_count,
        detected_lang=guess.lang or "hi",
        scan_pages=scan_pages,
        language_known=language_known,
        devanagari_ratio=guess.devanagari_ratio,
        avg_chars_per_page=avg,
        fonts=fonts,
        legacy_fonts=legacy_fonts,
        legacy_text=lt,
        converted_fonts=converted_fonts,
        warnings=warnings,
    )


def _family(font: str) -> str:
    name = font.split("+", 1)[-1].split(",")[0]
    return re.sub(r"(Roman|Bold|Italic)$", "", name).rstrip("-")


@dataclass
class LoadedPdf:
    doc: fitz.Document
    book: ExtractedBook
    analysis: PdfAnalysis
    paragraphs: list[Paragraph]


def load_pdf(
    data: bytes, *, max_bytes: int, max_mb: int, max_pages: int, min_chars_per_page: int, ocr: bool = False
) -> LoadedPdf:
    """Validate bytes, open, check page limit, extract, analyse and clean. Caller closes `doc`."""
    check_pdf_bytes(data, max_bytes, max_mb)
    doc = open_pdf(data)
    try:
        if doc.page_count > max_pages:
            raise errors.too_many_pages(doc.page_count, max_pages)
        book = extract_book(doc)
        scans = scanned_pages(doc, chars_per_page(book)) if ocr else []
        analysis = analyze_book(book, min_chars_per_page, scans)
        paragraphs = build_paragraphs(book.pages)
    except Exception:
        doc.close()
        raise
    log.info(
        "pdf loaded: pages=%d lang=%s deva=%.2f paragraphs=%d",
        analysis.page_count, analysis.detected_lang, analysis.devanagari_ratio, len(paragraphs),
    )
    return LoadedPdf(doc=doc, book=book, analysis=analysis, paragraphs=paragraphs)


# --------------------------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------------------------


@dataclass
class ImageInfo:
    page: int
    file: str  # file name inside the images directory
    width_px: int
    height_px: int
    width_pt: float  # displayed size on the original page
    height_pt: float


MIN_IMAGE_PX = 50
MAX_PAGES_PER_IMAGE = 3  # images repeated on more pages are logos/backgrounds


def extract_images(doc: fitz.Document, out_dir: Path, skip_pages: list[int] | None = None) -> list[ImageInfo]:
    """Figures on text pages. Pages in `skip_pages` (scans read with OCR) are skipped: their
    images are the page itself (sometimes in strips), not figures."""
    skip = set(skip_pages or [])
    out_dir.mkdir(parents=True, exist_ok=True)
    xref_pages: Counter[int] = Counter()
    for page in doc:
        for xref in {img[0] for img in page.get_images(full=True)}:
            xref_pages[xref] += 1

    result: list[ImageInfo] = []
    for i, page in enumerate(doc):
        page_no = i + 1
        if page_no in skip:
            continue
        page_area = page.rect.width * page.rect.height
        text_boxes = [fitz.Rect(b[:4]) for b in page.get_text("blocks") if b[4].strip()]
        seen: set[int] = set()
        for img in page.get_images(full=True):
            xref, smask = img[0], img[1]
            if xref in seen or xref_pages[xref] > MAX_PAGES_PER_IMAGE:
                continue
            seen.add(xref)
            rects = page.get_image_rects(xref)
            if not rects:
                continue
            r = max(rects, key=lambda rr: rr.width * rr.height)
            if r.width * r.height < 0.01 * page_area:
                continue
            if r.width * r.height > 0.6 * page_area:
                continue  # a full-page scan / background, not a figure
            # Text printed on top of an image means it is a decorative background (e.g. a banner
            # behind a chapter title), not a figure.
            if any(r.contains(fitz.Point((t.x0 + t.x1) / 2, (t.y0 + t.y1) / 2)) for t in text_boxes):
                continue
            try:
                pix = fitz.Pixmap(doc, xref)
                if smask:
                    pix = fitz.Pixmap(pix, fitz.Pixmap(doc, smask))
                if pix.width < MIN_IMAGE_PX or pix.height < MIN_IMAGE_PX:
                    continue
                if pix.colorspace and pix.colorspace.n not in (1, 3):  # CMYK etc. -> RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                name = f"p{page_no:04d}_x{xref}.png"
                pix.save(str(out_dir / name))
                result.append(ImageInfo(page_no, name, pix.width, pix.height, r.width, r.height))
            except Exception as exc:  # noqa: BLE001 - a bad image must not break the upload
                log.warning("image extraction failed page=%d xref=%d: %s", page_no, xref, exc)
    return result


# --------------------------------------------------------------------------------------------
# Chapter splitting
# --------------------------------------------------------------------------------------------

ChapterMethod = Literal["toc", "contents", "headings", "fixed"]


@dataclass
class ChapterInfo:
    id: str
    title: str
    start_page: int  # 1-based, inclusive
    end_page: int  # 1-based, inclusive
    method: ChapterMethod


_EN_NUM_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    "sixteen|seventeen|eighteen|nineteen|twenty"
)
_HI_NUM_WORDS = "एक|दो|तीन|चार|पाँच|पांच|छह|छः|सात|आठ|नौ|दस"
_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

EN_CHAPTER_RE = re.compile(
    rf"^\s*(chapter|unit|lesson)\s*[-–—:.]?\s*(\d{{1,3}}|[ivxlc]{{1,7}}|{_EN_NUM_WORDS})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
HI_CHAPTER_RE = re.compile(
    rf"^\s*(अध्याय|पाठ|इकाई)\s*[-–—:.]?\s*([0-9०-९]{{1,3}}|{_HI_NUM_WORDS})(?=$|[\s:.\-–—।)])"
)
_ANY_CHAPTER_RE = re.compile(
    rf"(?:chapter|unit|lesson|अध्याय|पाठ|इकाई)\s*[-–—:.]?\s*(?:\d{{1,3}}|[0-9०-९]{{1,3}}|[ivxlc]{{1,7}}\b)",
    re.IGNORECASE,
)


def match_chapter_heading(text: str) -> tuple[str, str] | None:
    """Return (kind, number) if `text` starts like a chapter heading, else None."""
    t = text.strip()
    m = EN_CHAPTER_RE.match(t) or HI_CHAPTER_RE.match(t)
    if not m:
        return None
    kind = m.group(1).lower()
    number = m.group(2).lower().translate(_DEVA_DIGITS)
    return kind, number


def _chapters_from_toc(doc: fitz.Document) -> list[tuple[str, int]]:
    toc = doc.get_toc(simple=True)
    if not toc:
        return []
    for level in (1, 2):
        entries = [(t.strip(), p) for lvl, t, p in toc if lvl == level and 1 <= p <= doc.page_count]
        if len(entries) >= 2:
            entries.sort(key=lambda e: e[1])
            dedup: list[tuple[str, int]] = []
            for title, page in entries:
                if dedup and dedup[-1][1] == page:
                    continue
                dedup.append((title or f"Page {page}", page))
            if len(dedup) >= 2:
                return dedup
    return []


def _chapters_from_headings(paragraphs: list[Paragraph]) -> list[tuple[str, int]]:
    by_page: dict[int, list[Paragraph]] = {}
    for p in paragraphs:
        by_page.setdefault(p.page, []).append(p)

    found: dict[tuple[str, str], tuple[str, int]] = {}
    for page_no in sorted(by_page):
        paras = by_page[page_no]
        page_text = " ".join(p.text for p in paras)
        if len(_ANY_CHAPTER_RE.findall(page_text)) >= 3:
            continue  # a contents page listing many chapters
        for idx, p in enumerate(paras[:6]):
            if len(p.text) > 120 or p.type in ("paragraph", "list_item") and len(p.text) > 60:
                continue
            m = match_chapter_heading(p.text)
            if not m:
                continue
            title = p.text.strip()
            # "Chapter 1" alone: take the following short line as the actual title.
            if len(title) <= 15 and idx + 1 < len(paras) and len(paras[idx + 1].text) <= 100:
                title = f"{title}: {paras[idx + 1].text.strip()}"
            # A repeated number keeps the later page (earlier one is usually front matter).
            found[m] = (title[:150], page_no)
            break
    entries = sorted(found.values(), key=lambda e: e[1])
    return entries if len(entries) >= 2 else []


# "प्रागैतिहासिक काल ........ 5-10"  /  "Motion .......... 12"
_CONTENTS_ENTRY_RE = re.compile(
    r"(?:^|(?<=\s))(?:[•●▪◦❖\-–]\s*)?(?P<title>[^•…]{2,160}?)\s*[.…·_]{5,}\s*"
    r"(?P<start>[0-9०-९]{1,4})(?:\s*[-–]\s*(?P<end>[0-9०-९]{1,4}))?(?=\s|$)"
)
_PAGE_NUM_ONLY_RE = re.compile(r"^\s*[-–(]?\s*([0-9०-९]{1,4})\s*[-–)]?\s*$")


def printed_page_offset(pages: list[PageLines]) -> int | None:
    """PDF page number minus printed page number, read from page numbers in headers/footers.

    Returns None when the book has no consistent printed page numbers.
    """
    votes: Counter[int] = Counter()
    for p in pages:
        for b in p.blocks:
            for ln in b.lines:
                in_zone = ln.bbox[3] <= p.height * 0.1 or ln.bbox[1] >= p.height * 0.88
                m = _PAGE_NUM_ONLY_RE.match(ln.text) if in_zone else None
                if m:
                    votes[p.page - int(m.group(1).translate(_DEVA_DIGITS))] += 1
    if not votes:
        return None
    offset, n = votes.most_common(1)[0]
    return offset if n >= max(3, len(pages) * 0.2) else None


def _chapters_from_contents(paragraphs: list[Paragraph], pages: list[PageLines], page_count: int) -> list[tuple[str, int]]:
    """Chapters from a printed contents page (dotted leaders + page numbers)."""
    limit = max(20, int(page_count * 0.1))
    raw: list[tuple[str, int]] = []
    for p in paragraphs:
        if p.page > limit:
            break
        for m in _CONTENTS_ENTRY_RE.finditer(p.text):
            title = m.group("title").strip(" -–:•")
            if len(title) >= 2:
                raw.append((title, int(m.group("start").translate(_DEVA_DIGITS))))
    if len(raw) < 3:
        return []
    offset = printed_page_offset(pages)
    if offset is None:
        offset = 0
    entries: list[tuple[str, int]] = []
    for title, printed in raw:
        pdf_page = printed + offset
        if not 1 <= pdf_page <= page_count:
            continue
        if entries and pdf_page <= entries[-1][1]:
            if pdf_page == entries[-1][1]:
                continue  # two entries starting on the same page: keep the first
            return []  # not increasing: probably not a contents page
        entries.append((title[:150], pdf_page))
    return entries if len(entries) >= 3 else []


def _to_chapters(entries: list[tuple[str, int]], page_count: int, method: ChapterMethod) -> list[ChapterInfo]:
    chapters: list[ChapterInfo] = []
    if entries[0][1] > 1:
        entries = [("Front matter", 1), *entries]
    for i, (title, start) in enumerate(entries):
        end = entries[i + 1][1] - 1 if i + 1 < len(entries) else page_count
        chapters.append(ChapterInfo(str(i + 1), title, start, max(start, end), method))
    return chapters


def fixed_chapters(page_count: int, pages_per_chunk: int) -> list[ChapterInfo]:
    chapters: list[ChapterInfo] = []
    for i, start in enumerate(range(1, page_count + 1, pages_per_chunk)):
        end = min(start + pages_per_chunk - 1, page_count)
        chapters.append(ChapterInfo(str(i + 1), f"Pages {start}–{end}", start, end, "fixed"))
    return chapters


def detect_chapters(
    doc: fitz.Document,
    paragraphs: list[Paragraph],
    pages_per_chunk: int,
    pages: list[PageLines] | None = None,
) -> list[ChapterInfo]:
    """PDF outline → printed contents page → chapter headings → fixed page ranges."""
    entries = _chapters_from_toc(doc)
    if entries:
        return _to_chapters(entries, doc.page_count, "toc")
    if pages is not None:
        entries = _chapters_from_contents(paragraphs, pages, doc.page_count)
        if entries:
            return _to_chapters(entries, doc.page_count, "contents")
    entries = _chapters_from_headings(paragraphs)
    if entries:
        return _to_chapters(entries, doc.page_count, "headings")
    return fixed_chapters(doc.page_count, pages_per_chunk)
