"""Session endpoints: upload, summary, change direction, delete."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool

from app import errors
from app.config import Settings, get_settings
from app.deps import get_store
from app.schemas import (
    ChapterSummary,
    CreateSessionResponse,
    DeleteSessionResponse,
    ErrorResponse,
    SessionSummary,
    UpdateSessionRequest,
)
from app.errors import AppError
from app.services import ocr, pdf_reader
from app.services.language import detect_language
from app.services.translator import get_translator
from app.services.translator.base import Translator, TranslatorConfigError
from app.services.language import Lang, other_lang
from app.services.jobs import JobRegistry, get_jobs
from app.services.session_store import SessionStore, utcnow
from app.services.translation import load_reconciled_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["sessions"])

_CHUNK = 1024 * 1024
_NOT_FOUND = {404: {"model": ErrorResponse}}


def boundaries_editable(state: dict[str, Any]) -> bool:
    return all(c["status"] == "pending" for c in state["chapters"])


def to_summary(state: dict[str, Any]) -> SessionSummary:
    expires = datetime.fromisoformat(state["expires_at"])
    return SessionSummary(
        session_id=state["session_id"],
        book_title=state["book_title"],
        source_lang=state["source_lang"],
        target_lang=state["target_lang"],
        detected_lang=state["detected_lang"],
        page_count=state["page_count"],
        chapter_detection=state["chapter_detection"],
        chapters=[
            ChapterSummary(**{k: c[k] for k in ("id", "title", "start_page", "end_page", "status")}, translated_title=c.get("translated_title"))
            for c in state["chapters"]
        ],
        warnings=state["warnings"],
        created_at=state["created_at"],
        expires_at=expires,
        seconds_remaining=max(0, int((expires - utcnow()).total_seconds())),
        boundaries_editable=boundaries_editable(state),
        auto_translate=bool(state.get("auto_translate", False)),
    )


def _ocr_translator(settings: Settings) -> Translator | None:
    """The translator, if it can read scanned pages (OCR); None otherwise."""
    try:
        t = get_translator(settings)
    except TranslatorConfigError:
        return None
    return t if t.can_ocr else None


def _detect_language_by_ocr(
    doc, pages: list[int], translator: Translator | None, requested: str, warnings: list[str],  # type: ignore[no-untyped-def]
) -> tuple[Lang, dict[int, list[dict]]]:
    if requested in ("hi", "en"):
        return requested, {}  # the student told us; no need to spend a request
    if translator is None or not pages:
        return "hi", {}
    page_no = pages[0]
    try:
        blocks = ocr.ocr_one(translator, ocr.render_page(doc, page_no))
    except Exception as e:  # noqa: BLE001 - busy service: fall back to Hindi, student can change it
        log.warning("language OCR failed: %s", type(e).__name__)
        warnings.append("Could not read the first page to detect the language; assumed Hindi. Change it above if needed.")
        return "hi", {}
    guess = detect_language(" ".join(b["text"] for b in blocks))
    return (guess.lang or "hi"), {page_no: blocks}


def _book_title(meta_title: str | None, filename: str | None) -> str:
    title = (meta_title or "").strip()
    if not title and filename:
        title = Path(filename).stem
    title = re.sub(r"[\x00-\x1f]", "", title)[:200]
    return title or "Book"


def _combine_upload(blobs: list[bytes], settings: Settings) -> bytes:
    """One PDF as is; photos (JPG/PNG/WebP) become a PDF with a page per photo."""
    if len(blobs) == 1 and pdf_reader.PDF_MAGIC in blobs[0][:1024]:
        return blobs[0]
    if any(pdf_reader.PDF_MAGIC in b[:1024] for b in blobs):
        raise errors.unsupported_file()  # mixing a PDF with other files
    if not all(ocr.image_type(b) for b in blobs):
        raise errors.not_pdf() if len(blobs) == 1 else errors.unsupported_file()
    if len(blobs) > settings.max_pages:
        raise errors.too_many_pages(len(blobs), settings.max_pages)
    return ocr.images_to_pdf(blobs)


def _process_upload(
    data: bytes,
    filename: str | None,
    requested: Literal["auto", "hi", "en"],
    settings: Settings,
    store: SessionStore,
) -> dict:
    translator = _ocr_translator(settings)
    try:
        loaded = pdf_reader.load_pdf(
            data,
            max_bytes=settings.max_upload_bytes,
            max_mb=settings.max_upload_mb,
            max_pages=settings.max_pages,
            min_chars_per_page=settings.min_chars_per_page,
            ocr=translator is not None,
        )
    except AppError as e:
        if e.code == "scanned_pdf" and translator is None:
            raise errors.ocr_unavailable() from None
        raise
    session_id, sdir = store.create()
    try:
        doc = loaded.doc
        analysis = loaded.analysis
        warnings = list(analysis.warnings)
        ocr_pages = analysis.scan_pages
        first_ocr: dict[int, list[dict]] = {}
        detected: Lang = analysis.detected_lang
        if not analysis.language_known:
            # Too little text to tell the language: read the first scanned page now.
            detected, first_ocr = _detect_language_by_ocr(doc, ocr_pages, translator, requested, warnings)
        source: Lang = detected if requested == "auto" else requested
        if source != detected and analysis.language_known:
            warnings.append(f"You chose {source} as the source language, but the book looks like {detected}.")

        chapters = pdf_reader.detect_chapters(doc, loaded.paragraphs, settings.default_pages_per_chunk, loaded.book.pages)
        images = pdf_reader.extract_images(doc, sdir / "images", skip_pages=ocr_pages)
        title = _book_title(doc.metadata.get("title") if doc.metadata else None, filename)

        (sdir / "original.pdf").write_bytes(data)
        paragraphs = [asdict(p) for p in loaded.paragraphs if p.page not in first_ocr]
        for page_no, blocks in first_ocr.items():
            paragraphs += ocr.blocks_to_paragraphs(page_no, blocks)
        paragraphs.sort(key=lambda p: (p["page"], p["id"]))
        store.write_json_atomic(
            sdir / "extracted.json",
            {
                "paragraphs": paragraphs,
                "images": [asdict(i) for i in images],
                "ocr_pages": ocr_pages,  # scanned pages, read with OCR when their chapter is translated
                "ocr_done": sorted(first_ocr),
            },
        )
        now = datetime.now(timezone.utc)
        state = {
            "session_id": session_id,
            "book_title": title,
            "source_lang": source,
            "target_lang": other_lang(source),
            "detected_lang": detected,
            "page_count": doc.page_count,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=settings.session_ttl_minutes)).isoformat(),
            "chapter_detection": chapters[0].method,
            "chapters": [
                {
                    "id": c.id,
                    "title": c.title,
                    "start_page": c.start_page,
                    "end_page": c.end_page,
                    "status": "pending",
                    "paragraphs": [],
                }
                for c in chapters
            ],
            "glossary": {},
            "warnings": warnings,
            "scanned_pages": len(ocr_pages),
            "scan_page_list": ocr_pages,
        }
        store.save_state(session_id, state)
        log.info("session created sid=%s pages=%d chapters=%d", session_id, doc.page_count, len(chapters))
        return state
    except Exception:
        shutil.rmtree(sdir, ignore_errors=True)
        raise
    finally:
        loaded.doc.close()


@router.post(
    "",
    response_model=CreateSessionResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}},
)
async def create_session(
    file: list[UploadFile] = File(..., description="one PDF, or one or more photos of pages"),
    source_lang: Literal["auto", "hi", "en"] = Form("auto"),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
) -> CreateSessionResponse:
    blobs: list[bytes] = []
    total = 0
    for f in file:
        data = bytearray()
        while chunk := await f.read(_CHUNK):
            data += chunk
            total += len(chunk)
            if total > settings.max_upload_bytes:
                raise errors.too_large(settings.max_upload_mb)
        blobs.append(bytes(data))
    pdf_bytes = await run_in_threadpool(_combine_upload, blobs, settings)
    name = file[0].filename if file else None
    state = await run_in_threadpool(_process_upload, pdf_bytes, name, source_lang, settings, store)
    return to_summary(state)


@router.get("/{session_id}", response_model=SessionSummary, responses=_NOT_FOUND)
def get_session(
    session_id: str, store: SessionStore = Depends(get_store), jobs: JobRegistry = Depends(get_jobs)
) -> SessionSummary:
    return to_summary(load_reconciled_state(store, jobs, session_id))


@router.patch(
    "/{session_id}",
    response_model=SessionSummary,
    responses={**_NOT_FOUND, 409: {"model": ErrorResponse}},
)
def update_session(
    session_id: str, body: UpdateSessionRequest, store: SessionStore = Depends(get_store)
) -> SessionSummary:
    """Change the translation direction. Allowed only before any translation has started."""
    with store.edit_state(session_id) as state:
        if not boundaries_editable(state):
            raise errors.translation_started()
        state["source_lang"] = body.source_lang
        state["target_lang"] = other_lang(body.source_lang)
        state["glossary"] = {}
    return to_summary(state)


@router.delete("/{session_id}", response_model=DeleteSessionResponse, responses=_NOT_FOUND)
def delete_session(
    session_id: str, store: SessionStore = Depends(get_store), jobs: JobRegistry = Depends(get_jobs)
) -> DeleteSessionResponse:
    """"Finish & delete my files": remove everything for this session immediately.

    A running job notices on its next batch that the session is gone and stops."""
    jobs.forget_session(session_id)
    if not store.delete(session_id):
        raise errors.session_not_found()
    return DeleteSessionResponse(deleted=True)
