"""Scanned books and photos: find pages that are images of text and read them with OCR.

* Photos (JPG/PNG/WebP) are turned into PDF pages, so everything else works the same.
* A page "needs OCR" when it has almost no text layer but a big image (a scan).
  Mixed books work too: only the scanned pages are read.
* OCR runs when a chapter is translated (not at upload), one AI request per page, a few pages
  at a time; results are cached in the session's extracted.json.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import pymupdf as fitz

from app import errors
from app.services.session_store import SessionStore
from app.services.text_cleaner import normalize_text
from app.services.translator.base import (
    InvalidResponseError,
    RateLimitError,
    Translator,
    TranslatorConfigError,
    TranslatorError,
)

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 30  # a page with less visible text than this may be a scan
MIN_INK = 0.0005  # ... if at least this share of it is ink (a title-only page is ~0.1%; blank is 0)
INK_DPI = 36  # tiny render, enough to tell ink from a blank page
OCR_IMAGE_WIDTH = 1600  # pixels sent to the OCR model
OCR_CONCURRENCY = 3

IMAGE_TYPES = {  # magic bytes → PyMuPDF file type
    b"\x89PNG": "png",
    b"\xff\xd8\xff": "jpeg",
}


def image_type(data: bytes) -> str | None:
    for magic, kind in IMAGE_TYPES.items():
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def images_to_pdf(images: list[bytes]) -> bytes:
    """Photos of pages → one PDF, a page per photo (sized to the photo)."""
    out = fitz.open()
    for data in images:
        kind = image_type(data)
        if kind is None:
            raise errors.unsupported_file()
        try:
            img = fitz.open(stream=data, filetype=kind)
            pdf = fitz.open("pdf", img.convert_to_pdf())
        except Exception:  # noqa: BLE001 - a broken photo
            raise errors.unsupported_file() from None
        out.insert_pdf(pdf)
    data = out.tobytes(garbage=3, deflate=True)
    out.close()
    return data


def ink_share(page: fitz.Page) -> float:
    """Share of the page that is printed on (dark pixels), from a tiny greyscale render."""
    pix = page.get_pixmap(dpi=INK_DPI, colorspace=fitz.csGRAY, alpha=False)
    samples = pix.samples
    if not samples:
        return 0.0
    dark = sum(1 for v in samples if v < 200)
    return dark / len(samples)


def scanned_pages(doc: fitz.Document, chars_per_page: dict[int, int]) -> list[int]:
    """1-based numbers of pages to read with OCR: almost no visible text, but ink on the page.

    This works however the page was made — one scanned image, image strips (tiled scans),
    or text converted to vector outlines — and skips blank pages.
    """
    pages: list[int] = []
    for i, page in enumerate(doc):
        n = i + 1
        if chars_per_page.get(n, 0) >= MIN_TEXT_CHARS:
            continue
        if ink_share(page) >= MIN_INK:
            pages.append(n)
    return pages


def render_page(doc: fitz.Document, page_no: int, width: int = OCR_IMAGE_WIDTH) -> bytes:
    page = doc[page_no - 1]
    zoom = width / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("jpeg", jpg_quality=85)


def _table_text(text: str) -> str:
    """Normalize a "cell | cell" table cell by cell (so a "|" after Hindi text stays a cell
    separator and is not turned into a danda)."""
    rows = []
    for line in text.splitlines():
        if line.strip():
            rows.append(" | ".join(normalize_text(c) for c in line.split("|")))
    return "\n".join(rows)


def _columns(text: str) -> int:
    first = next((line for line in text.splitlines() if line.strip()), "")
    return first.count("|") + 1


def _merge_split_tables(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The model sometimes returns each table row as its own block: join neighbouring table
    blocks that have the same number of columns back into one table."""
    out: list[dict[str, Any]] = []
    for b in blocks:
        prev = out[-1] if out else None
        if (prev is not None and b["type"] == "table" and prev["type"] == "table"
                and "|" in b["text"] and _columns(b["text"]) == _columns(prev["text"])):
            out[-1] = {**prev, "text": prev["text"].rstrip("\n") + "\n" + b["text"]}
        else:
            out.append(dict(b))
    return out


_NUMBERED_RE = re.compile(r"^\s*(?:[0-9०-९]{1,2}|[a-zA-Z]|[क-ह])\s*[.)]\s*\S")


def _titled_lists(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A "table" whose every row is "title | 1. … | 2. …" is really boxes with a title and
    numbered points (often side by side): turn each row into a sub-heading and its points."""
    out: list[dict[str, Any]] = []
    for b in blocks:
        rows = [[c.strip() for c in line.split("|")] for line in b["text"].splitlines() if line.strip()]
        if b["type"] == "table" and rows and all(
            len(r) >= 3 and all(_NUMBERED_RE.match(c) for c in r[1:]) for r in rows
        ):
            for r in rows:
                out.append({"type": "heading", "level": 3, "text": r[0]})
                out += [{"type": "list_item", "level": None, "text": c} for c in r[1:] if c]
        else:
            out.append(b)
    return out


def blocks_to_paragraphs(page_no: int, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OCR blocks → paragraph records in the same shape as text-layer extraction."""
    out = []
    for i, b in enumerate(_titled_lists(_merge_split_tables(blocks)), start=1):
        text = _table_text(b["text"]) if b["type"] == "table" else normalize_text(b["text"])
        if not text:
            continue
        out.append({
            "id": f"p{page_no:04d}_{i:03d}", "page": page_no, "type": b["type"], "text": text,
            "size": 12.0, "bold": b["type"] == "heading", "level": b.get("level"), "group": None,
        })
    return out


def pending_pages(extracted: dict[str, Any], start: int, end: int) -> list[int]:
    done = set(extracted.get("ocr_done", []))
    return [p for p in extracted.get("ocr_pages", []) if start <= p <= end and p not in done]


def ocr_one(translator: Translator, image: bytes, sleep: Callable[[float], None] = time.sleep,
            on_busy: Callable[[], None] = lambda: None) -> list[dict[str, Any]]:
    """OCR one page image, retrying on busy / rate-limited / bad answers."""
    attempts = 0
    busy_waits = 0
    while True:
        try:
            return translator.ocr_image(image)
        except RateLimitError as e:
            busy_waits += 1
            if busy_waits > 8:
                raise
            on_busy()
            sleep(min(e.retry_after or 5 * 2 ** (busy_waits - 1), 60))
        except (InvalidResponseError, TranslatorError):
            attempts += 1
            if attempts >= 3:
                raise
            sleep(2 ** attempts)


def read_pages(
    store: SessionStore,
    session_id: str,
    pages: list[int],
    translator: Translator,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
    on_busy: Callable[[], None] = lambda: None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """OCR the given pages and save their paragraphs into extracted.json (page by page)."""
    if not pages:
        return
    sdir: Path = store.existing_dir(session_id)
    with fitz.open(sdir / "original.pdf") as doc:  # PyMuPDF is not thread-safe: render first
        images = {p: render_page(doc, p) for p in pages}

    done = 0

    def work(page_no: int) -> None:
        nonlocal done
        blocks = ocr_one(translator, images[page_no], sleep, on_busy)
        paras = blocks_to_paragraphs(page_no, blocks)
        with store.lock(session_id):
            extracted = store.load_extracted(session_id)
            extracted["paragraphs"] = sorted(
                [p for p in extracted["paragraphs"] if p["page"] != page_no] + paras,
                key=lambda p: (p["page"], p["id"]),
            )
            extracted["ocr_done"] = sorted(set(extracted.get("ocr_done", [])) | {page_no})
            store.write_json_atomic(sdir / "extracted.json", extracted)
        done += 1
        on_progress(done, len(pages))
        log.info("ocr page sid=%s page=%d blocks=%d", session_id, page_no, len(paras))

    failed: list[int] = []
    config_error: Exception | None = None
    with ThreadPoolExecutor(max_workers=OCR_CONCURRENCY) as pool:
        futures = {pool.submit(work, p): p for p in pages}
        for f, page_no in futures.items():
            try:
                f.result()
            except TranslatorConfigError as e:  # bad key / no model: retrying will not help
                config_error = config_error or e
            except Exception as e:  # noqa: BLE001 - keep reading the other pages
                log.warning("ocr page sid=%s page=%d failed: %s", session_id, page_no, type(e).__name__)
                failed.append(page_no)
    if config_error is not None:
        raise config_error
    if failed:
        # Pages that were read are saved; running the chapter again retries only these.
        raise errors.ocr_failed(sorted(failed))
