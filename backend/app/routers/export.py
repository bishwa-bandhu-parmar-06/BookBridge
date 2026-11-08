"""PDF downloads and previews: a single chapter (review or approved) and the combined book
(approved chapters only).

Preview = the same PDF, generated once and shown as page images, so it works in every
browser (phones cannot display a PDF inside a web page).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pymupdf as fitz
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response

from app import errors
from app.deps import get_store
from app.schemas import ErrorResponse, PreviewInfo
from app.services import pdf_writer
from app.services.session_store import SessionStore
from app.services.translation import find_chapter

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions/{session_id}", tags=["export"])

_PDF = {"content": {"application/pdf": {}}, "description": "PDF file"}
_PNG = {"content": {"image/png": {}}, "description": "Page image"}
_ERRS = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}
_NO_CACHE = {"Cache-Control": "no-store"}
# Student options for the PDF: text size and whether to print highlights / notes / stars.
_FONT = Query(1.0, ge=0.8, le=1.6, description="text size, 1.0 = normal")
_ANN = Query(True, description="include the student's highlights, notes and stars")


def _file_stem(title: str) -> str:
    stem = re.sub(r"[^\wऀ-ॿ]+", "_", title, flags=re.UNICODE).strip("_")
    return stem[:60] or "book"


def _outputs(store: SessionStore, session_id: str) -> Path:
    out = store.existing_dir(session_id) / "outputs"
    out.mkdir(exist_ok=True)
    return out


def _build_chapter_pdf(
    store: SessionStore, session_id: str, chapter_id: str, font_scale: float = 1.0, annotate: bool = True
) -> tuple[Path, str]:
    state = store.load_state(session_id)
    ch = find_chapter(state, chapter_id)
    if ch["status"] not in ("review", "approved"):
        raise errors.chapter_wrong_status("download", ch["status"])
    images = pdf_writer.load_images(store.load_extracted(session_id))
    html = pdf_writer.render_chapter_html(state, ch, images, font_scale=font_scale, annotate=annotate)
    pdf = pdf_writer.html_to_pdf(html, store.existing_dir(session_id))
    path = _outputs(store, session_id) / f"chapter_{ch['id']}.pdf"
    path.write_bytes(pdf)
    log.info("chapter pdf sid=%s cid=%s bytes=%d", session_id, ch["id"], len(pdf))
    return path, f"{_file_stem(state.get('book_title', 'book'))}_ch{ch['id']}_{state['target_lang']}.pdf"


def _build_book_pdf(
    store: SessionStore, session_id: str, font_scale: float = 1.0, annotate: bool = True
) -> tuple[Path, str]:
    state = store.load_state(session_id)
    approved = [ch for ch in state["chapters"] if ch["status"] == "approved"]
    if not approved:
        raise errors.no_approved_chapters()
    images = pdf_writer.load_images(store.load_extracted(session_id))
    html = pdf_writer.render_book_html(state, approved, images, font_scale=font_scale, annotate=annotate)
    pdf = pdf_writer.html_to_pdf(html, store.existing_dir(session_id))
    path = _outputs(store, session_id) / "book.pdf"
    path.write_bytes(pdf)
    log.info("book pdf sid=%s chapters=%d bytes=%d", session_id, len(approved), len(pdf))
    return path, f"{_file_stem(state.get('book_title', 'book'))}_{state['target_lang']}.pdf"


def _preview_info(path: Path) -> PreviewInfo:
    with fitz.open(path) as doc:
        r = doc[0].rect if doc.page_count else fitz.Rect(0, 0, 595, 842)
        return PreviewInfo(pages=doc.page_count, width_pt=r.width, height_pt=r.height, version=int(path.stat().st_mtime))


def _page_png(path: Path, page: int, width: int) -> Response:
    if not path.is_file():
        raise errors.preview_not_ready()
    with fitz.open(path) as doc:
        if not 1 <= page <= doc.page_count:
            raise errors.preview_not_ready()
        pg = doc[page - 1]
        zoom = width / pg.rect.width
        png = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")
    return Response(content=png, media_type="image/png", headers=_NO_CACHE)


# --- original pages --------------------------------------------------------------------------


@router.get("/pages/{page}.jpg", response_class=Response,
            responses={200: {"content": {"image/jpeg": {}}, "description": "Original page image"}, **_ERRS})
def original_page(
    session_id: str,
    page: int,
    width: int = Query(1000, ge=300, le=1800),
    store: SessionStore = Depends(get_store),
) -> Response:
    """A page of the uploaded book as an image, to compare a scanned page with what OCR read."""
    path = store.existing_dir(session_id) / "original.pdf"
    with fitz.open(path) as doc:
        if not 1 <= page <= doc.page_count:
            raise errors.page_not_found()
        pg = doc[page - 1]
        zoom = width / pg.rect.width
        jpg = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("jpeg", jpg_quality=80)
    # The original never changes during a session; private so shared caches never keep it.
    return Response(content=jpg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# --- chapter -----------------------------------------------------------------------------------


@router.get("/chapters/{chapter_id}/pdf", response_class=FileResponse, responses={200: _PDF, **_ERRS})
def chapter_pdf(
    session_id: str,
    chapter_id: str,
    font_scale: float = _FONT,
    annotations: bool = _ANN,
    store: SessionStore = Depends(get_store),
) -> FileResponse:
    path, name = _build_chapter_pdf(store, session_id, chapter_id, font_scale, annotations)
    return FileResponse(path, media_type="application/pdf", filename=name)


@router.get("/chapters/{chapter_id}/preview", response_model=PreviewInfo, responses=_ERRS)
def chapter_preview(
    session_id: str,
    chapter_id: str,
    font_scale: float = _FONT,
    annotations: bool = _ANN,
    store: SessionStore = Depends(get_store),
) -> Any:
    """Build the chapter PDF with the latest translations; returns its page count."""
    path, _ = _build_chapter_pdf(store, session_id, chapter_id, font_scale, annotations)
    return _preview_info(path)


@router.get("/chapters/{chapter_id}/preview/{page}.png", response_class=Response, responses={200: _PNG, **_ERRS})
def chapter_preview_page(
    session_id: str,
    chapter_id: str,
    page: int,
    width: int = Query(900, ge=300, le=1800),
    store: SessionStore = Depends(get_store),
) -> Response:
    state = store.load_state(session_id)
    ch = find_chapter(state, chapter_id)
    return _page_png(_outputs(store, session_id) / f"chapter_{ch['id']}.pdf", page, width)


# --- whole book --------------------------------------------------------------------------------


@router.get("/book.pdf", response_class=FileResponse, responses={200: _PDF, **_ERRS})
def book_pdf(
    session_id: str,
    font_scale: float = _FONT,
    annotations: bool = _ANN,
    store: SessionStore = Depends(get_store),
) -> FileResponse:
    path, name = _build_book_pdf(store, session_id, font_scale, annotations)
    return FileResponse(path, media_type="application/pdf", filename=name)


@router.get("/book/preview", response_model=PreviewInfo, responses=_ERRS)
def book_preview(
    session_id: str,
    font_scale: float = _FONT,
    annotations: bool = _ANN,
    store: SessionStore = Depends(get_store),
) -> Any:
    path, _ = _build_book_pdf(store, session_id, font_scale, annotations)
    return _preview_info(path)


@router.get("/book/preview/{page}.png", response_class=Response, responses={200: _PNG, **_ERRS})
def book_preview_page(
    session_id: str,
    page: int,
    width: int = Query(900, ge=300, le=1800),
    store: SessionStore = Depends(get_store),
) -> Response:
    return _page_png(_outputs(store, session_id) / "book.pdf", page, width)
