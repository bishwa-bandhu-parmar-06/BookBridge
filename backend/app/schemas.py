"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

LangCode = Literal["hi", "en"]
ChapterStatus = Literal["pending", "translating", "review", "approved", "failed"]
ChapterDetection = Literal["toc", "contents", "headings", "fixed", "manual"]


class ErrorResponse(BaseModel):
    error: str
    message: str
    message_hi: str = ""


class ChapterSummary(BaseModel):
    id: str
    title: str
    translated_title: str | None = None
    start_page: int
    end_page: int
    status: ChapterStatus = "pending"


class SessionSummary(BaseModel):
    session_id: str
    book_title: str
    source_lang: LangCode
    target_lang: LangCode
    detected_lang: LangCode
    page_count: int
    chapter_detection: ChapterDetection
    chapters: list[ChapterSummary]
    warnings: list[str]
    created_at: datetime
    expires_at: datetime
    seconds_remaining: int
    #: True until any chapter has started translating; boundaries/direction can change only then.
    boundaries_editable: bool
    #: keep translating the following chapters in the background
    auto_translate: bool = False


# POST /api/sessions returns the full summary.
CreateSessionResponse = SessionSummary


class AutoTranslateRequest(BaseModel):
    enabled: bool
    #: when turning on: start with the first untranslated chapter after this one
    after_chapter_id: str | None = None


class UpdateSessionRequest(BaseModel):
    """Change the translation direction (only before any translation has started)."""

    source_lang: LangCode


class ChapterBoundary(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)


class UpdateChaptersRequest(BaseModel):
    """The complete new chapter list, in reading order.

    Merging, splitting and moving boundaries are all expressed by sending the new list.
    Chapters may not overlap; pages left out of every chapter are simply not translated.
    """

    chapters: list[ChapterBoundary] = Field(min_length=1, max_length=500)


class DeleteSessionResponse(BaseModel):
    deleted: bool


# --- Milestone 3: chapters, jobs, glossary --------------------------------------------------

ParagraphType = Literal["heading", "paragraph", "list_item", "formula", "table_text", "table"]


class ParagraphOut(BaseModel):
    id: str
    page: int
    type: ParagraphType
    level: int | None = None
    #: paragraphs in the same framed box of the book share a group id
    group: str | None = None
    original: str
    translated: str | None
    flagged: bool
    edited: bool
    #: True when translation failed and there is no translation yet
    error: bool


class ChapterDetail(ChapterSummary):
    source_lang: LangCode
    target_lang: LangCode
    paragraphs: list[ParagraphOut]
    #: the running job for this session, if it is translating this chapter
    active_job_id: str | None = None
    #: the student's highlights / notes / stars, by paragraph id
    annotations: dict[str, "Annotation"] = Field(default_factory=dict)
    #: pages of this chapter that were read with OCR (scans / photos); their image can be viewed
    scanned_pages: list[int] = Field(default_factory=list)


class StartJobResponse(BaseModel):
    job_id: str


class JobResponse(BaseModel):
    job_id: str
    session_id: str
    chapter_id: str
    kind: Literal["translate", "retranslate"]
    status: Literal["queued", "running", "done", "failed"]
    progress: int
    message: str
    notice: str | None = None
    elapsed_seconds: int = 0
    error: str | None = None
    error_hi: str | None = None


class RetranslateRequest(BaseModel):
    paragraph_ids: list[str] = Field(min_length=1, max_length=2000)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None


class ParagraphPatch(BaseModel):
    """Manual edit of a translation and/or toggling the flag."""

    translated: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)] | None = None
    flagged: bool | None = None


class GlossaryEntry(BaseModel):
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    target: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    origin: Literal["model", "user"] = "user"


class GlossaryResponse(BaseModel):
    source_lang: LangCode
    target_lang: LangCode
    terms: list[GlossaryEntry]


class GlossaryUpdate(BaseModel):
    """The complete edited glossary. Omitted terms are removed."""

    terms: list[GlossaryEntry] = Field(max_length=2000)


class PublicConfig(BaseModel):
    max_upload_mb: int
    max_pages: int
    session_ttl_minutes: int


class PreviewInfo(BaseModel):
    """A generated PDF ready to preview page by page."""

    pages: int
    width_pt: float
    height_pt: float
    #: changes whenever the PDF is regenerated (use it to bust image caches)
    version: int


# --- Study tools: highlights, notes, stars -----------------------------------------------------

HighlightColor = Literal["yellow", "green", "pink", "blue"]


class Highlight(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    color: HighlightColor = "yellow"


class Annotation(BaseModel):
    """What a student added to one point. Highlights are ranges in the translated text."""

    highlights: list[Highlight] = Field(default_factory=list, max_length=200)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    star: bool = False
