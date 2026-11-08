"""Translation orchestration: retry/backoff/fallback around a Translator, and the background job
that translates a chapter (or selected paragraphs) batch by batch.

Logging records ids, counts and sizes only — never book text.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from app.errors import AppError
from app.services import ocr
from app.services.chunker import chunk_paragraphs
from app.services.glossary import merge_model_terms, relevant_terms
from app.services.jobs import Job, JobRegistry
from app.services.session_store import SessionStore
from app.services.translator.base import (
    BatchContext,
    BatchResult,
    InvalidResponseError,
    Lang,
    RateLimitError,
    TranslatedParagraph,
    TranslationItem,
    Translator,
    TranslatorConfigError,
    TranslatorError,
)

log = logging.getLogger(__name__)

#: pseudo paragraph id used to translate the chapter title together with the first batch
TITLE_ID = "__chapter_title__"

StatusFn = Callable[[str], None]
SleepFn = Callable[[float], None]


# --------------------------------------------------------------------------------------------
# Retry policy
# --------------------------------------------------------------------------------------------


@dataclass
class RetryPolicy:
    max_attempts: int = 3  # for invalid responses / transient errors
    base_delay: float = 1.0  # 1s, 2s, 4s …
    max_rate_limit_retries: int = 8
    rate_limit_base_delay: float = 5.0
    max_delay: float = 60.0


@dataclass
class RetryOutcome:
    #: one entry per input item, None where that paragraph could not be translated
    translations: list[str | None]
    terms: dict[str, str]
    used_fallback: bool = False

    @property
    def failed_ids_count(self) -> int:
        return sum(1 for t in self.translations if t is None)


def _call_with_retries(
    translator: Translator,
    items: list[TranslationItem],
    source: Lang,
    target: Lang,
    glossary: dict[str, str],
    context: BatchContext,
    policy: RetryPolicy,
    sleep: SleepFn,
    on_status: StatusFn,
) -> BatchResult:
    attempts = 0
    rate_limited = 0
    while True:
        try:
            result = translator.translate_batch(items, source, target, glossary, context)
            # Defence in depth: providers are expected to validate, but never trust alignment blindly.
            if [t.id for t in result.translations] != [i.id for i in items] or any(
                not t.text.strip() for t in result.translations
            ):
                raise InvalidResponseError("translator returned misaligned or empty translations")
            return result
        except RateLimitError as e:
            rate_limited += 1
            if rate_limited > policy.max_rate_limit_retries:
                raise
            delay = e.retry_after or policy.rate_limit_base_delay * 2 ** (rate_limited - 1)
            delay = min(delay, policy.max_delay)
            on_status("The AI service is busy right now. Switching models and trying again…")
            log.info("rate limited, retry %d in %.0fs", rate_limited, delay)
            sleep(delay)
        except (InvalidResponseError, TranslatorError) as e:
            attempts += 1
            log.info("batch attempt %d/%d failed: %s", attempts, policy.max_attempts, e)
            if attempts >= policy.max_attempts:
                raise
            sleep(min(policy.base_delay * 2 ** (attempts - 1), policy.max_delay))


def translate_with_retry(
    translator: Translator,
    items: list[TranslationItem],
    source: Lang,
    target: Lang,
    glossary: dict[str, str],
    context: BatchContext,
    policy: RetryPolicy | None = None,
    sleep: SleepFn | None = None,
    on_status: StatusFn = lambda _m: None,
) -> RetryOutcome:
    """Translate a batch; if it keeps failing, split it in half and translate each half
    (recursively). Splitting costs far fewer requests than going paragraph by paragraph,
    which matters on rate-limited free tiers.

    Rate-limit exhaustion and configuration errors propagate (they would fail every
    paragraph too). A paragraph that still fails alone is returned as None.
    """
    policy = policy or RetryPolicy()
    sleep = sleep or time.sleep
    try:
        r = _call_with_retries(translator, items, source, target, glossary, context, policy, sleep, on_status)
        return RetryOutcome([t.text for t in r.translations], r.terms)
    except RateLimitError:
        raise
    except (InvalidResponseError, TranslatorError):
        if len(items) == 1:
            log.warning("paragraph %s failed after retries", items[0].id)
            return RetryOutcome([None], {}, used_fallback=True)

    on_status("Retrying in smaller parts…")
    mid = len(items) // 2
    left = translate_with_retry(translator, items[:mid], source, target, glossary, context, policy, sleep, on_status)
    right = translate_with_retry(translator, items[mid:], source, target, glossary, context, policy, sleep, on_status)
    return RetryOutcome(left.translations + right.translations, {**left.terms, **right.terms}, used_fallback=True)


# --------------------------------------------------------------------------------------------
# Chapter paragraphs
# --------------------------------------------------------------------------------------------


def build_chapter_paragraphs(extracted: dict[str, Any], start_page: int, end_page: int) -> list[dict[str, Any]]:
    """Paragraph records for a chapter, from the whole-book extraction."""
    out: list[dict[str, Any]] = []
    for p in extracted["paragraphs"]:
        if start_page <= p["page"] <= end_page:
            is_formula = p["type"] == "formula"
            out.append(
                {
                    "id": p["id"],
                    "page": p["page"],
                    "type": p["type"],
                    "level": p.get("level"),
                    "group": p.get("group"),
                    "original": p["text"],
                    "translated": p["text"] if is_formula else None,  # formulas pass through unchanged
                    "flagged": False,
                    "edited": False,
                    "error": False,
                }
            )
    return out


def find_chapter(state: dict[str, Any], chapter_id: str) -> dict[str, Any]:
    from app import errors

    for ch in state["chapters"]:
        if ch["id"] == chapter_id:
            return ch
    raise errors.chapter_not_found()


# --------------------------------------------------------------------------------------------
# Background job
# --------------------------------------------------------------------------------------------


def _previous_context(paras: list[dict[str, Any]], before_index: int, n: int = 2) -> list[str]:
    """The n paragraphs before a batch: their translation if already done, else the original
    (batches run in parallel, so the previous batch may still be in progress)."""
    prev: list[str] = []
    for p in reversed(paras[:before_index]):
        if p["type"] != "formula":
            prev.append(p.get("translated") or p["original"])
            if len(prev) == n:
                break
    return list(reversed(prev))


def run_translation_job(
    job: Job,
    *,
    store: SessionStore,
    registry: JobRegistry,
    translator: Translator,
    paragraph_ids: list[str] | None,
    note: str | None = None,
    batch_chars: int = 2000,
    policy: RetryPolicy | None = None,
    sleep: SleepFn | None = None,
    concurrency: int = 1,
) -> None:
    """Translate the chapter's untranslated paragraphs (kind=translate) or the given
    paragraph_ids (kind=retranslate), `concurrency` batches at a time. Runs in a worker
    thread via BackgroundTasks; each finished batch is saved immediately, so a failed or
    interrupted job keeps its progress."""
    sid, cid = job.session_id, job.chapter_id
    on_status: StatusFn = lambda m: registry.update(job.id, notice=m)  # noqa: E731
    registry.update(job.id, status="running", message="Starting…", notice=None, progress=0)
    started = time.time()
    try:
        if job.kind == "translate":
            _read_scanned_pages(job, store, registry, translator)
        state = store.load_state(sid)
        ch = find_chapter(state, cid)
        source: Lang = state["source_lang"]
        target: Lang = state["target_lang"]
        paras: list[dict[str, Any]] = ch["paragraphs"]
        index = {p["id"]: i for i, p in enumerate(paras)}

        if paragraph_ids is None:
            targets = [p for p in paras if p["type"] != "formula" and not p.get("translated")]
        else:
            wanted = set(paragraph_ids)
            targets = [p for p in paras if p["id"] in wanted]
        items = [TranslationItem(p["id"], p["original"], p["type"]) for p in targets]
        if paragraph_ids is None and not ch.get("translated_title"):
            # The chapter title is translated with the first batch (used in PDF headings / contents).
            items.insert(0, TranslationItem(TITLE_ID, ch["title"], "heading"))
        batches = chunk_paragraphs(items, max_chars=batch_chars)
        log.info("job %s start kind=%s paragraphs=%d batches=%d", job.id, job.kind, len(items), len(batches))
        registry.update(job.id, message=f"0 of {len(batches)} parts translated")

        failed = 0
        done = 0
        base_progress = job.progress  # > 0 when scanned pages were read first
        lock = threading.Lock()
        abort = threading.Event()
        state0 = store.load_state(sid)
        ch0 = find_chapter(state0, cid)

        def work(batch: list[TranslationItem]) -> None:
            nonlocal failed, done
            if abort.is_set():
                return
            st_now = store.load_state(sid)
            context = BatchContext(
                book_title=st_now.get("book_title", ""),
                chapter_title=ch0["title"],
                previous_translations=_previous_context(ch0["paragraphs"], index.get(batch[0].id, 0)),
                note=note,
            )
            glossary = relevant_terms(st_now["glossary"], [it.text for it in batch])
            try:
                outcome = translate_with_retry(
                    translator, batch, source, target, glossary, context, policy, sleep, on_status
                )
            except Exception:
                abort.set()  # rate limits exhausted / config error: stop starting new batches
                raise
            with store.edit_state(sid) as st:
                ch_st = find_chapter(st, cid)
                pmap = {p["id"]: p for p in ch_st["paragraphs"]}
                n_failed = 0
                for it, text in zip(batch, outcome.translations):
                    if it.id == TITLE_ID:
                        if text:
                            ch_st["translated_title"] = text
                        continue
                    p = pmap[it.id]
                    if text is None:
                        n_failed += 1
                        p["flagged"] = True
                        p["error"] = not p.get("translated")
                    else:
                        p.update(translated=text, flagged=False, edited=False, error=False)
                merge_model_terms(st["glossary"], outcome.terms)
            with lock:
                failed += n_failed
                done += 1
                registry.update(
                    job.id,
                    progress=base_progress + int(done * (100 - base_progress) / len(batches)),
                    message=f"{done} of {len(batches)} parts translated",
                    notice=None,
                )
            log.info("job %s batch done %d/%d chars=%d failed=%d", job.id, done, len(batches),
                     sum(len(i.text) for i in batch), n_failed)

        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = [pool.submit(work, b) for b in batches]
            first_error: BaseException | None = None
            for f in futures:
                try:
                    f.result()
                except BaseException as e:  # noqa: BLE001 - re-raised below after all workers stop
                    first_error = first_error or e
        if first_error is not None:
            raise first_error

        with store.edit_state(sid) as st:
            find_chapter(st, cid)["status"] = "review"
        msg = "Done" if not failed else f"Done, but {failed} paragraph(s) could not be translated. They are flagged."
        registry.update(job.id, status="done", progress=100, message=msg, notice=None)
        log.info("job %s done in %.1fs failed=%d", job.id, time.time() - started, failed)

    except AppError as e:  # session expired / deleted mid-job, or scanned pages not read
        log.info("job %s stopped: %s", job.id, e.code)
        if e.code == "ocr_failed":
            _mark_failed(store, sid, cid, job.kind)  # "Continue translation" retries the missing pages
        registry.update(job.id, status="failed", message="Stopped", error=e.message, error_hi=e.message_hi)
    except Exception as e:  # noqa: BLE001
        if isinstance(e, TranslatorConfigError):
            err, err_hi = "The translation service is not set up correctly on the server.", "सर्वर पर अनुवाद सेवा सही से सेट नहीं है।"
            log.error("job %s config error: %s", job.id, e)
        elif isinstance(e, RateLimitError):
            err, err_hi = "The translation service is too busy right now. Please try again in a few minutes.", "अनुवाद सेवा अभी बहुत व्यस्त है। कृपया कुछ मिनट बाद फिर कोशिश करें।"
            log.warning("job %s gave up after rate limits", job.id)
        else:
            err, err_hi = "Translation failed. Please try again.", "अनुवाद विफल रहा। कृपया फिर से कोशिश करें।"
            log.exception("job %s failed: %s", job.id, type(e).__name__)
        _mark_failed(store, sid, cid, job.kind)
        registry.update(job.id, status="failed", message="Failed", error=err, error_hi=err_hi)


FRONT_MATTER_TITLE = "Front matter"


def prepare_for_translation(store: SessionStore, session_id: str, chapter_id: str) -> None:
    """Under the state lock: check the chapter can be translated, build its paragraphs from the
    book extraction if needed, and mark it as translating."""
    from app import errors

    with store.edit_state(session_id) as st:
        ch = find_chapter(st, chapter_id)
        if ch["status"] not in ("pending", "failed"):
            raise errors.chapter_wrong_status("translate", ch["status"])
        if not ch["paragraphs"]:
            extracted = store.load_extracted(session_id)
            # Chapters with unread scanned pages are built after OCR, inside the job.
            if not ocr.pending_pages(extracted, ch["start_page"], ch["end_page"]):
                ch["paragraphs"] = build_chapter_paragraphs(extracted, ch["start_page"], ch["end_page"])
        ch["status"] = "translating"


def _read_scanned_pages(job: Job, store: SessionStore, registry: JobRegistry, translator: Translator) -> None:
    """OCR the chapter's unread scanned pages, then build its paragraphs (translate jobs only)."""
    sid, cid = job.session_id, job.chapter_id
    ch = find_chapter(store.load_state(sid), cid)
    if ch["paragraphs"]:
        return
    pages = ocr.pending_pages(store.load_extracted(sid), ch["start_page"], ch["end_page"])
    if pages:
        registry.update(job.id, message=f"Reading scanned page 1 of {len(pages)}…")
        ocr.read_pages(
            store, sid, pages, translator,
            on_progress=lambda done, total: registry.update(
                job.id, message=f"Read {done} of {total} scanned pages", notice=None,
                progress=int(done * 30 / total),  # reading = the first 30% of the bar
            ),
            on_busy=lambda: registry.update(job.id, notice="The AI service is busy right now. Trying again…"),
        )
    with store.edit_state(sid) as st:
        c = find_chapter(st, cid)
        if not c["paragraphs"]:
            c["paragraphs"] = build_chapter_paragraphs(store.load_extracted(sid), c["start_page"], c["end_page"])
        if pages and _AUTO_TITLE_RE.match(c["title"]):
            title = title_from_headings(c["paragraphs"])
            if title:
                c["title"] = title  # translated with the first batch, like any chapter title


_AUTO_TITLE_RE = re.compile(r"^Pages \d+–\d+$")


def title_from_headings(paras: list[dict[str, Any]]) -> str | None:
    """A chapter title from its opening headings: "part title + chapter title" → the chapter
    title, otherwise the first heading. Used for scanned pages that had no contents page."""
    heads = [p for p in paras[:6] if p["type"] == "heading"]
    if not heads:
        return None
    if len(heads) >= 2 and (heads[0].get("level") or 3) == 1 and (heads[1].get("level") or 3) <= 2:
        return heads[1]["original"][:150]
    return heads[0]["original"][:150]


def next_chapter_to_translate(state: dict[str, Any], after_chapter_id: str | None) -> str | None:
    """The next not-yet-translated chapter after `after_chapter_id` (then from the start),
    skipping the front matter. Failed chapters are left for the student to retry."""
    chapters = state["chapters"]
    ids = [c["id"] for c in chapters]
    start = ids.index(after_chapter_id) + 1 if after_chapter_id in ids else 0
    for ch in chapters[start:] + chapters[:start]:
        if ch["status"] == "pending" and ch["title"] != FRONT_MATTER_TITLE and ch["id"] != after_chapter_id:
            return ch["id"]
    return None


def start_next_auto_job(
    store: SessionStore, registry: JobRegistry, session_id: str, after_chapter_id: str | None
) -> Job | None:
    """If auto-translate is on, register and prepare the next chapter's job (or return None)."""
    try:
        state = store.load_state(session_id)
    except AppError:
        return None
    if not state.get("auto_translate"):
        return None
    nxt = next_chapter_to_translate(state, after_chapter_id)
    if nxt is None:
        return None
    try:
        job = registry.start(session_id, nxt, "translate")
    except AppError:  # another job is already running for this session
        return None
    try:
        prepare_for_translation(store, session_id, nxt)
    except Exception as e:  # noqa: BLE001
        registry.update(job.id, status="failed", message="Not started", error=getattr(e, "message", "Not started"))
        return None
    log.info("auto-translate: next chapter sid=%s cid=%s job=%s", session_id, nxt, job.id)
    return job


def run_translation_chain(job: Job, **kwargs: Any) -> None:
    """Run a job; when a chapter translation finishes and auto-translate is on, continue with
    the next chapter in the same worker (still one job per session at a time)."""
    store: SessionStore = kwargs["store"]
    registry: JobRegistry = kwargs["registry"]
    current: Job | None = job
    while current is not None:
        run_translation_job(current, **kwargs)
        if current.kind != "translate" or current.status != "done":
            return
        kwargs = {**kwargs, "paragraph_ids": None, "note": None}
        current = start_next_auto_job(store, registry, current.session_id, current.chapter_id)


def _mark_failed(store: SessionStore, sid: str, cid: str, kind: str) -> None:
    try:
        with store.edit_state(sid) as st:
            ch = find_chapter(st, cid)
            # A failed re-translation keeps the earlier translations, so go back to review.
            ch["status"] = "review" if kind == "retranslate" else "failed"
    except Exception:  # noqa: BLE001 - session may be gone
        pass


__all__ = [
    "RetryPolicy",
    "RetryOutcome",
    "TranslatedParagraph",
    "build_chapter_paragraphs",
    "find_chapter",
    "run_translation_job",
    "translate_with_retry",
]


def load_reconciled_state(store: SessionStore, registry: JobRegistry, session_id: str) -> dict[str, Any]:
    """Load state; chapters stuck in 'translating' with no live job (e.g. after a server
    restart) are moved to 'failed' — or 'review' if every paragraph already has a translation."""
    state = store.load_state(session_id)
    if not any(ch["status"] == "translating" for ch in state["chapters"]):
        return state
    if registry.active_for_session(session_id) is not None:
        return state
    with store.edit_state(session_id) as st:
        if registry.active_for_session(session_id) is None:
            for ch in st["chapters"]:
                if ch["status"] == "translating":
                    done = ch["paragraphs"] and all(p.get("translated") for p in ch["paragraphs"])
                    ch["status"] = "review" if done else "failed"
                    log.info("reconciled stale chapter sid=%s cid=%s -> %s", session_id, ch["id"], ch["status"])
        state = st
    return state
