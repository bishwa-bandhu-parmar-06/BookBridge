"""Chapter endpoints: boundaries, translation jobs, review, manual edits, approval."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends

from app import errors
from app.config import Settings, get_settings
from app.deps import get_store, get_translator_dep
from app.routers.sessions import boundaries_editable, to_summary
from app.schemas import (
    Annotation,
    AutoTranslateRequest,
    ChapterBoundary,
    ChapterDetail,
    ChapterSummary,
    ErrorResponse,
    ParagraphOut,
    ParagraphPatch,
    RetranslateRequest,
    SessionSummary,
    StartJobResponse,
    UpdateChaptersRequest,
)
from app.services import annotations
from app.services.jobs import JobRegistry, get_jobs
from app.services.session_store import SessionStore
from app.services.translation import (
    RetryPolicy,
    build_chapter_paragraphs,
    find_chapter,
    load_reconciled_state,
    next_chapter_to_translate,
    prepare_for_translation,
    run_translation_chain,
)
from app.services.translator.base import Translator

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["chapters"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse},
}


def _summary(ch: dict[str, Any]) -> ChapterSummary:
    return ChapterSummary(**{k: ch[k] for k in ("id", "title", "start_page", "end_page", "status")}, translated_title=ch.get("translated_title"))


# --------------------------------------------------------------------------------------------
# Boundaries
# --------------------------------------------------------------------------------------------


def validate_boundaries(chapters: list[ChapterBoundary], page_count: int) -> None:
    """Chapters must be in reading order, inside the book, and must not overlap."""
    prev_end = 0
    for i, c in enumerate(chapters, start=1):
        if c.start_page > c.end_page:
            raise errors.invalid_chapters(
                f"Chapter {i}: the start page ({c.start_page}) is after the end page ({c.end_page}).",
                f"अध्याय {i}: प्रारंभ पृष्ठ ({c.start_page}) अंतिम पृष्ठ ({c.end_page}) के बाद है।",
            )
        if c.end_page > page_count:
            raise errors.invalid_chapters(
                f"Chapter {i}: the book has only {page_count} pages.",
                f"अध्याय {i}: किताब में केवल {page_count} पृष्ठ हैं।",
            )
        if c.start_page <= prev_end:
            raise errors.invalid_chapters(
                f"Chapter {i} overlaps the previous chapter. Chapters must be in order and must not share pages.",
                f"अध्याय {i} पिछले अध्याय से टकरा रहा है। अध्याय क्रम में हों और उनके पृष्ठ अलग-अलग हों।",
            )
        prev_end = c.end_page


@router.put("/chapters", response_model=SessionSummary, responses=_ERRORS)
def update_chapters(
    session_id: str, body: UpdateChaptersRequest, store: SessionStore = Depends(get_store)
) -> SessionSummary:
    """Replace the chapter list (merge / split / move boundaries). Only before any translation."""
    with store.edit_state(session_id) as state:
        if not boundaries_editable(state):
            raise errors.translation_started()
        validate_boundaries(body.chapters, state["page_count"])
        state["chapters"] = [
            {
                "id": str(i),
                "title": c.title.strip(),
                "start_page": c.start_page,
                "end_page": c.end_page,
                "status": "pending",
                "paragraphs": [],
            }
            for i, c in enumerate(body.chapters, start=1)
        ]
        state["chapter_detection"] = "manual"
    return to_summary(state)


# --------------------------------------------------------------------------------------------
# Review data
# --------------------------------------------------------------------------------------------


@router.get("/chapters/{chapter_id}", response_model=ChapterDetail, responses=_ERRORS)
def get_chapter(
    session_id: str,
    chapter_id: str,
    store: SessionStore = Depends(get_store),
    jobs: JobRegistry = Depends(get_jobs),
) -> ChapterDetail:
    state = load_reconciled_state(store, jobs, session_id)
    ch = find_chapter(state, chapter_id)
    job = jobs.active_for_session(session_id)
    return ChapterDetail(
        **_summary(ch).model_dump(),
        source_lang=state["source_lang"],
        target_lang=state["target_lang"],
        paragraphs=[ParagraphOut(**p) for p in ch["paragraphs"]],
        active_job_id=job.id if job and job.chapter_id == chapter_id else None,
        annotations={pid: Annotation(**a) for pid, a in annotations.live(ch).items()},
        scanned_pages=[p for p in state.get("scan_page_list", []) if ch["start_page"] <= p <= ch["end_page"]],
    )


@router.put("/chapters/{chapter_id}/annotations/{paragraph_id}", response_model=Annotation, responses=_ERRORS)
def save_annotation(
    session_id: str,
    chapter_id: str,
    paragraph_id: str,
    body: Annotation,
    store: SessionStore = Depends(get_store),
) -> Annotation:
    """Save a student's highlights / note / star for one point (send the complete set; an
    empty annotation removes it)."""
    with store.edit_state(session_id) as st:
        ch = find_chapter(st, chapter_id)
        if ch["status"] not in ("review", "approved"):
            raise errors.chapter_wrong_status("annotate", ch["status"])
        p = next((x for x in ch["paragraphs"] if x["id"] == paragraph_id), None)
        if p is None:
            raise errors.paragraph_not_found()
        text = annotations.display_text(p)
        hl = annotations.clean_highlights([h.model_dump() for h in body.highlights], len(text))
        store_map = ch.setdefault("annotations", {})
        if not hl and not body.note and not body.star:
            store_map.pop(paragraph_id, None)
        else:
            store_map[paragraph_id] = {
                "highlights": hl, "note": body.note, "star": body.star, "text_hash": annotations.text_hash(text),
            }
        out = Annotation(highlights=hl, note=body.note, star=body.star)
    return out


# --------------------------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------------------------


def _schedule(
    background: BackgroundTasks,
    *,
    store: SessionStore,
    jobs: JobRegistry,
    translator: Translator,
    settings: Settings,
    session_id: str,
    chapter_id: str,
    kind: str,
    prepare: Any,
    paragraph_ids: list[str] | None = None,
    note: str | None = None,
) -> StartJobResponse:
    """Register the job (one per session), run `prepare(chapter)` under the state lock, schedule."""
    job = jobs.start(session_id, chapter_id, kind)  # type: ignore[arg-type]
    try:
        with store.edit_state(session_id) as st:
            ch = find_chapter(st, chapter_id)
            prepare(ch)
            ch["status"] = "translating"
    except Exception as e:
        jobs.update(job.id, status="failed", message="Not started", error=getattr(e, "message", "Not started"))
        raise
    background.add_task(
        run_translation_chain,
        job,
        store=store,
        registry=jobs,
        translator=translator,
        paragraph_ids=paragraph_ids,
        note=note,
        batch_chars=settings.translation_batch_chars,
        policy=RetryPolicy(max_attempts=settings.translation_max_attempts),
        concurrency=settings.translation_concurrency,
    )
    return StartJobResponse(job_id=job.id)


@router.post(
    "/chapters/{chapter_id}/translate",
    response_model=StartJobResponse,
    status_code=202,
    responses={**_ERRORS, 503: {"model": ErrorResponse}},
)
def translate_chapter(
    session_id: str,
    chapter_id: str,
    background: BackgroundTasks,
    store: SessionStore = Depends(get_store),
    jobs: JobRegistry = Depends(get_jobs),
    translator: Translator = Depends(get_translator_dep),
    settings: Settings = Depends(get_settings),
) -> StartJobResponse:
    """Translate a pending chapter, or resume a failed one (only untranslated paragraphs)."""
    state = load_reconciled_state(store, jobs, session_id)
    ch = find_chapter(state, chapter_id)
    if ch["status"] not in ("pending", "failed"):
        raise errors.chapter_wrong_status("translate", ch["status"])
    return _start_translation(background, store, jobs, translator, settings, session_id, chapter_id)


def _start_translation(
    background: BackgroundTasks,
    store: SessionStore,
    jobs: JobRegistry,
    translator: Translator,
    settings: Settings,
    session_id: str,
    chapter_id: str,
) -> StartJobResponse:
    job = jobs.start(session_id, chapter_id, "translate")
    try:
        prepare_for_translation(store, session_id, chapter_id)
    except Exception as e:
        jobs.update(job.id, status="failed", message="Not started", error=getattr(e, "message", "Not started"))
        raise
    background.add_task(
        run_translation_chain,
        job,
        store=store,
        registry=jobs,
        translator=translator,
        paragraph_ids=None,
        note=None,
        batch_chars=settings.translation_batch_chars,
        policy=RetryPolicy(max_attempts=settings.translation_max_attempts),
        concurrency=settings.translation_concurrency,
    )
    return StartJobResponse(job_id=job.id)


@router.post(
    "/auto-translate",
    response_model=SessionSummary,
    responses={**_ERRORS, 503: {"model": ErrorResponse}},
)
def set_auto_translate(
    session_id: str,
    body: AutoTranslateRequest,
    background: BackgroundTasks,
    store: SessionStore = Depends(get_store),
    jobs: JobRegistry = Depends(get_jobs),
    translator: Translator = Depends(get_translator_dep),
    settings: Settings = Depends(get_settings),
) -> SessionSummary:
    """Turn background translation of the following chapters on or off. Turning it on while
    nothing is translating starts the next untranslated chapter right away."""
    with store.edit_state(session_id) as st:
        st["auto_translate"] = body.enabled
    state = load_reconciled_state(store, jobs, session_id)
    if body.enabled and jobs.active_for_session(session_id) is None:
        nxt = next_chapter_to_translate(state, body.after_chapter_id)
        if nxt is not None:
            _start_translation(background, store, jobs, translator, settings, session_id, nxt)
            state = store.load_state(session_id)
    return to_summary(state)


@router.post(
    "/chapters/{chapter_id}/retranslate",
    response_model=StartJobResponse,
    status_code=202,
    responses={**_ERRORS, 503: {"model": ErrorResponse}},
)
def retranslate_paragraphs(
    session_id: str,
    chapter_id: str,
    body: RetranslateRequest,
    background: BackgroundTasks,
    store: SessionStore = Depends(get_store),
    jobs: JobRegistry = Depends(get_jobs),
    translator: Translator = Depends(get_translator_dep),
    settings: Settings = Depends(get_settings),
) -> StartJobResponse:
    """Re-translate only the given paragraphs (optionally with a note like "use simpler words")."""
    ids = list(dict.fromkeys(body.paragraph_ids))

    def prepare(c: dict[str, Any]) -> None:
        if c["status"] not in ("review", "approved"):
            raise errors.chapter_wrong_status("re-translate", c["status"])
        by_id = {p["id"]: p for p in c["paragraphs"]}
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            raise errors.invalid_paragraphs(f"Unknown paragraph id(s): {', '.join(unknown[:5])}")
        if any(by_id[i]["type"] == "formula" for i in ids):
            raise errors.invalid_paragraphs("Formulas are kept unchanged and cannot be re-translated.")

    load_reconciled_state(store, jobs, session_id)
    return _schedule(
        background, store=store, jobs=jobs, translator=translator, settings=settings,
        session_id=session_id, chapter_id=chapter_id, kind="retranslate", prepare=prepare,
        paragraph_ids=ids, note=body.note or None,
    )


# --------------------------------------------------------------------------------------------
# Edits & approval
# --------------------------------------------------------------------------------------------


@router.patch("/chapters/{chapter_id}/paragraphs/{paragraph_id}", response_model=ParagraphOut, responses=_ERRORS)
def edit_paragraph(
    session_id: str,
    chapter_id: str,
    paragraph_id: str,
    body: ParagraphPatch,
    store: SessionStore = Depends(get_store),
) -> ParagraphOut:
    """Manually correct a translation and/or set the paragraph's flag."""
    with store.edit_state(session_id) as st:
        ch = find_chapter(st, chapter_id)
        if ch["status"] not in ("review", "approved"):
            raise errors.chapter_wrong_status("edit", ch["status"])
        p = next((p for p in ch["paragraphs"] if p["id"] == paragraph_id), None)
        if p is None:
            raise errors.paragraph_not_found()
        if body.translated is not None:
            p.update(translated=body.translated, edited=True, error=False, flagged=False)
        if body.flagged is not None:
            p["flagged"] = body.flagged
        out = ParagraphOut(**p)
    return out


@router.post("/chapters/{chapter_id}/approve", response_model=ChapterSummary, responses=_ERRORS)
def approve_chapter(session_id: str, chapter_id: str, store: SessionStore = Depends(get_store)) -> ChapterSummary:
    with store.edit_state(session_id) as st:
        ch = find_chapter(st, chapter_id)
        if ch["status"] == "approved":
            return _summary(ch)
        if ch["status"] != "review":
            raise errors.chapter_wrong_status("approve", ch["status"])
        missing = sum(1 for p in ch["paragraphs"] if not p.get("translated"))
        if missing:
            raise errors.untranslated_paragraphs(missing)
        ch["status"] = "approved"
        out = _summary(ch)
    return out
