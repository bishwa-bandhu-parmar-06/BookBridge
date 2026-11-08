"""HTML (Jinja2) → PDF with WeasyPrint, using the bundled Noto fonts.

WeasyPrint shapes text with HarfBuzz via Pango, so Devanagari conjuncts and matras
render correctly (ReportLab does not). WeasyPrint is imported lazily: if its system
libraries (Pango) are missing, only the PDF endpoints fail, with a clear error.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from app import errors
from app.services import annotations

log = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = APP_DIR / "templates"
FONTS_DIR = APP_DIR / "fonts"

FONT_FILES: list[tuple[str, str, int, str]] = [
    ("Noto Sans", "NotoSans-Regular.ttf", 400, "normal"),
    ("Noto Sans", "NotoSans-Bold.ttf", 700, "normal"),
    ("Noto Sans", "NotoSans-Italic.ttf", 400, "italic"),
    ("Noto Sans Devanagari", "NotoSansDevanagari-Regular.ttf", 400, "normal"),
    ("Noto Sans Devanagari", "NotoSansDevanagari-Bold.ttf", 700, "normal"),
    ("Noto Sans Mono", "NotoSansMono-Regular.ttf", 400, "normal"),
    ("Noto Sans Math", "NotoSansMath-Regular.ttf", 400, "normal"),
]

LABELS = {
    "en": {"contents": "Contents", "translated": "Translated with BookBridge", "from": {"hi": "Hindi", "en": "English"}},
    "hi": {"contents": "विषय सूची", "translated": "BookBridge द्वारा अनूदित", "from": {"hi": "हिंदी", "en": "अंग्रेज़ी"}},
}


def _css_string(value: str) -> Markup:
    """Escape a value for use inside a double-quoted CSS string within <style>."""
    v = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("<", "\\3c ")
    return Markup(v)


_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["css_string"] = _css_string


def font_stack(lang: str) -> Markup:
    # Put the target script's font first so whole words shape in one font;
    # the other covers mixed-language text (e.g. English terms in brackets).
    # Markup: this goes into <style> and must not be HTML-escaped.
    if lang == "hi":
        return Markup('"Noto Sans Devanagari", "Noto Sans", "Noto Sans Math", sans-serif')
    return Markup('"Noto Sans", "Noto Sans Devanagari", "Noto Sans Math", sans-serif')


def _fonts() -> list[dict[str, Any]]:
    return [
        {"family": fam, "url": (FONTS_DIR / file).as_uri(), "weight": w, "style": st}
        for fam, file, w, st in FONT_FILES
        if (FONTS_DIR / file).is_file()
    ]


# --------------------------------------------------------------------------------------------
# Building the view model
# --------------------------------------------------------------------------------------------


@dataclass
class ImageRef:
    page: int
    file: str
    width_pt: float


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s, flags=re.UNICODE).strip().lower()


_ANSWER_SEP_RE = re.compile(r"\s[–—]\s*|\s-(?:\s+|(?=\S))")


def answer_spans(text: str) -> tuple[int, int, int] | None:
    """(question_end, answer_start, answer_end) offsets for "question – answer", else None."""
    matches = list(_ANSWER_SEP_RE.finditer(text))
    if not matches:
        return None
    m = matches[-1]
    q_end = len(text[: m.start()].rstrip())
    a_start = m.end() + (len(text[m.end():]) - len(text[m.end():].lstrip()))
    a_end = len(text.rstrip())
    if q_end == 0 or a_end <= a_start or a_end - a_start > 160:
        return None
    return q_end, a_start, a_end


def split_answer(text: str) -> tuple[str, str | None]:
    """Split "question – answer" at the last spaced dash, so the answer can be printed in bold."""
    spans = answer_spans(text)
    if spans is None:
        return text, None
    q_end, a_start, a_end = spans
    return text[:q_end], text[a_start:a_end]


def _repeats_title(chapter: dict[str, Any], p: dict[str, Any]) -> bool:
    title_norm = _norm(chapter.get("title", ""))
    tr_title_norm = _norm(chapter.get("translated_title") or "")
    o, t = _norm(p["original"]), _norm(p.get("translated") or "")
    # The contents page and the chapter page may spell the title differently (सिंधु / सिन्धु),
    # so compare the translations too.
    return bool(o and o in title_norm) or bool(t and tr_title_norm and (t in tr_title_norm or tr_title_norm in t))


def split_leading_titles(chapter: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Clean the headings a chapter starts with, so each title is printed once.

    Books open a chapter with e.g. part title "प्राचीन इतिहास" + chapter banner "प्रागैतिहासिक काल".
    The chapter banner repeats our chapter title → dropped. A big heading before it is a part
    title → returned separately and printed once above the chapter title. Returns
    (part_titles, remaining paragraphs).
    """
    paras = list(chapter.get("paragraphs") or [])
    lead_end = 0
    while lead_end < len(paras) and paras[lead_end]["type"] == "heading" and not paras[lead_end].get("group"):
        lead_end += 1
    lead, rest = paras[:lead_end], paras[lead_end:]
    title_at = next((i for i, p in enumerate(lead) if _repeats_title(chapter, p)), None)

    parts: list[str] = []
    kept: list[dict[str, Any]] = []
    for i, p in enumerate(lead):
        if _repeats_title(chapter, p):
            continue
        if title_at is not None and i < title_at and (p.get("level") or 3) <= 1:
            parts.append(p.get("translated") or p["original"])
        else:
            kept.append(p)
    return parts, kept + rest


def _drop_repeated_headings(paras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A heading identical to the heading right before it is printed only once."""
    out: list[dict[str, Any]] = []
    for p in paras:
        if (
            p["type"] == "heading" and out and out[-1]["type"] == "heading"
            and _norm(p.get("translated") or p["original"]) == _norm(out[-1].get("translated") or out[-1]["original"])
        ):
            continue
        out.append(p)
    return out


def build_blocks(
    chapter: dict[str, Any], images: list[ImageRef], max_width_pt: float = 480, annotate: bool = True
) -> list[dict[str, Any]]:
    """Paragraphs in order, each page's images placed after that page's paragraphs.

    Leading headings that repeat the chapter title are dropped (the chapter title is printed
    above); part titles are left to `chapter_view`.
    """
    _, paras = split_leading_titles(chapter)
    paras = _drop_repeated_headings(paras)
    notes = annotations.live(chapter) if annotate else {}

    by_page: dict[int, list[dict[str, Any]]] = {}
    for p in paras:
        by_page.setdefault(p["page"], []).append(p)
    imgs_by_page: dict[int, list[ImageRef]] = {}
    for im in images:
        if chapter["start_page"] <= im.page <= chapter["end_page"]:
            imgs_by_page.setdefault(im.page, []).append(im)

    blocks: list[dict[str, Any]] = []
    for page in range(chapter["start_page"], chapter["end_page"] + 1):
        for p in by_page.get(page, []):
            text = p.get("translated") or p["original"]
            spans = answer_spans(text) if p["type"] in ("list_item", "paragraph") else None
            ann = notes.get(p["id"], {})
            hl = ann.get("highlights", [])
            blocks.append(
                {
                    "kind": p["type"],
                    "text": text,
                    "question": text[: spans[0]] if spans else text,
                    "answer": text[spans[1]: spans[2]] if spans else None,
                    # highlighted runs: [(text, colour or None), ...]
                    "segs": annotations.segments(text, hl),
                    "q_segs": annotations.segments(text, hl, 0, spans[0]) if spans else None,
                    "a_segs": annotations.segments(text, hl, spans[1], spans[2]) if spans else None,
                    "note": ann.get("note", ""),
                    "star": bool(ann.get("star")),
                    "level": p.get("level"),
                    "group": p.get("group"),
                    "rows": table_view(parse_table(text)) if p["type"] == "table" else None,
                    "untranslated": not p.get("translated") and p["type"] != "formula",
                }
            )
        for im in imgs_by_page.get(page, []):
            blocks.append({"kind": "image", "src": f"images/{im.file}", "width_pt": round(min(im.width_pt, max_width_pt), 1)})
    return group_boxes(blocks)


def parse_table(text: str) -> list[list[str]]:
    """"cell | cell" lines back into rows; ragged rows are padded so the table stays rectangular."""
    rows = [[c.strip() for c in line.split("|")] for line in text.splitlines() if line.strip()]
    width = max((len(r) for r in rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]


def table_view(rows: list[list[str]]) -> list[dict[str, Any]]:
    """Rows for the template: a row with a single filled cell is a title spanning the table;
    the first other row is the column header."""
    out: list[dict[str, Any]] = []
    header_done = False
    width = len(rows[0]) if rows else 0
    for r in rows:
        filled = [c for c in r if c]
        if width > 1 and len(filled) == 1 and not header_done:
            out.append({"kind": "title", "cells": filled, "span": width})
        elif not header_done:
            out.append({"kind": "head", "cells": r})
            header_done = True
        else:
            out.append({"kind": "body", "cells": r})
    return out


def group_boxes(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consecutive blocks from the same framed box of the book become one "box" block."""
    out: list[dict[str, Any]] = []
    for b in blocks:
        g = b.get("group")
        if g and out and out[-1]["kind"] == "box" and out[-1]["group"] == g:
            out[-1]["blocks"].append(b)
        elif g:
            out.append({"kind": "box", "group": g, "blocks": [b]})
        else:
            out.append(b)
    return out


def chapter_view(chapter: dict[str, Any], images: list[ImageRef], annotate: bool = True) -> dict[str, Any]:
    parts, _ = split_leading_titles(chapter)
    return {
        "anchor": f"chapter-{chapter['id']}",
        "title": chapter.get("translated_title") or chapter["title"],
        "parts": parts,
        "blocks": build_blocks(chapter, images, annotate=annotate),
    }


FONT_SCALE_MIN, FONT_SCALE_MAX = 0.8, 1.6


def _common(state: dict[str, Any], document_title: str, font_scale: float = 1.0) -> dict[str, Any]:
    lang = state["target_lang"]
    scale = min(max(font_scale, FONT_SCALE_MIN), FONT_SCALE_MAX)
    return {
        "lang": lang,
        "book_title": state.get("book_title", ""),
        "document_title": document_title,
        "fonts": _fonts(),
        "font_stack": font_stack(lang),
        # every font size in the stylesheet goes through pt() so the student's size applies
        "pt": lambda size: Markup(f"{size * scale:.2f}pt"),
    }


def render_chapter_html(
    state: dict[str, Any], chapter: dict[str, Any], images: list[ImageRef],
    font_scale: float = 1.0, annotate: bool = True,
) -> str:
    view = chapter_view(chapter, images, annotate)
    return _env.get_template("chapter.html").render(**_common(state, view["title"], font_scale), chapter=view)


def render_book_html(
    state: dict[str, Any], chapters: list[dict[str, Any]], images: list[ImageRef],
    font_scale: float = 1.0, annotate: bool = True,
) -> str:
    lang = state["target_lang"]
    lab = LABELS[lang]
    labels = {
        "contents": lab["contents"],
        "translated": lab["translated"],
        "direction": f"{lab['from'][state['source_lang']]} → {lab['from'][lang]}",
    }
    views = [chapter_view(ch, images, annotate) for ch in chapters]
    return _env.get_template("book.html").render(
        **_common(state, state.get("book_title", ""), font_scale), chapters=views, labels=labels
    )


# --------------------------------------------------------------------------------------------
# HTML → PDF
# --------------------------------------------------------------------------------------------


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except Exception:  # OSError when Pango/GObject libraries are missing
        return False
    return True


def html_to_pdf(html: str, base_dir: Path) -> bytes:
    try:
        from weasyprint import HTML
        from weasyprint.text.fonts import FontConfiguration
    except Exception as e:  # noqa: BLE001
        log.error("WeasyPrint unavailable: %s", type(e).__name__)
        raise errors.pdf_unavailable() from None
    font_config = FontConfiguration()
    return HTML(string=html, base_url=str(base_dir)).write_pdf(font_config=font_config)  # type: ignore[no-any-return]


def load_images(extracted: dict[str, Any]) -> list[ImageRef]:
    return [ImageRef(page=i["page"], file=i["file"], width_pt=i["width_pt"]) for i in extracted.get("images", [])]
