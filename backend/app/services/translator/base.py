"""Provider-agnostic translator interface.

A provider (Gemini today; IndicTrans2 / Bhashini later) implements `Translator.translate_batch`.
Everything a provider needs — the paragraphs, languages, glossary and context — is passed in,
and everything it returns is validated here, so no code outside this folder changes when a
new provider is added.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Lang = Literal["hi", "en"]
LANG_NAMES: dict[str, str] = {"hi": "Hindi", "en": "English"}


@dataclass
class TranslationItem:
    id: str
    text: str
    type: str = "paragraph"  # heading | paragraph | list_item | table_text


@dataclass
class BatchContext:
    book_title: str = ""
    chapter_title: str = ""
    #: the last 2 translated paragraphs before this batch, for continuity
    previous_translations: list[str] = field(default_factory=list)
    #: optional user instruction for re-translation, e.g. "use simpler words"
    note: str | None = None


@dataclass
class TranslatedParagraph:
    id: str
    text: str


@dataclass
class BatchResult:
    """`translations` is in the same order, with the same ids, as the input batch."""

    translations: list[TranslatedParagraph]
    #: key technical terms used in this batch: source-language term -> target-language term
    terms: dict[str, str] = field(default_factory=dict)


# --- errors ---------------------------------------------------------------------------------


class TranslatorError(Exception):
    """A (possibly transient) failure talking to the provider."""


class RateLimitError(TranslatorError):
    """The provider said we are sending too many requests (HTTP 429)."""

    def __init__(self, message: str = "rate limited", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class InvalidResponseError(TranslatorError):
    """The provider answered, but not with the JSON we asked for."""


class TranslatorConfigError(Exception):
    """The translator is not configured (e.g. missing API key). Not retryable."""


# --- interface ------------------------------------------------------------------------------


class Translator(ABC):
    name: str = "base"

    @abstractmethod
    def translate_batch(
        self,
        paragraphs: list[TranslationItem],
        source_lang: Lang,
        target_lang: Lang,
        glossary: dict[str, str],
        context: BatchContext,
    ) -> BatchResult:
        """Translate `paragraphs`. Must raise RateLimitError / InvalidResponseError / TranslatorError on failure."""

    def ocr_image(self, image: bytes, mime: str = "image/jpeg") -> list[dict]:
        """Read a scanned page image (OCR). Returns blocks: {"type", "level", "text"}, in reading
        order and in the page's own language. Providers without OCR raise TranslatorConfigError."""
        raise TranslatorConfigError(f"{self.name} cannot read scanned pages")

    @property
    def can_ocr(self) -> bool:
        return type(self).ocr_image is not Translator.ocr_image


# --- response validation (shared by all JSON-speaking providers) ----------------------------

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_batch_response(raw: str, items: list[TranslationItem]) -> BatchResult:
    """Parse and strictly validate a provider's JSON answer.

    Expected: {"translations": [{"id": ..., "text": ...}, ...], "terms": [{"source": ..., "target": ...}]}
    (a bare list of translations is also accepted). Same count, same ids in the same order,
    no empty translations — otherwise InvalidResponseError.
    """
    try:
        data: Any = json.loads(_FENCE_RE.sub("", raw or ""))
    except json.JSONDecodeError as e:
        raise InvalidResponseError(f"response is not valid JSON ({e.msg})") from None

    if isinstance(data, list):
        data = {"translations": data}
    if not isinstance(data, dict) or not isinstance(data.get("translations"), list):
        raise InvalidResponseError("response has no 'translations' list")

    entries = data["translations"]
    if len(entries) != len(items):
        raise InvalidResponseError(f"expected {len(items)} translations, got {len(entries)}")

    by_id: dict[str, str] = {}
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not isinstance(e.get("text"), str):
            raise InvalidResponseError("each translation needs a string 'id' and 'text'")
        if e["id"] in by_id:
            raise InvalidResponseError(f"duplicate id {e['id']}")
        by_id[e["id"]] = e["text"].strip()

    expected = [it.id for it in items]
    if set(by_id) != set(expected):
        raise InvalidResponseError("translation ids do not match the request")
    empty = [i for i in expected if not by_id[i]]
    if empty:
        raise InvalidResponseError(f"{len(empty)} empty translation(s)")

    terms: dict[str, str] = {}
    raw_terms = data.get("terms") or []
    if isinstance(raw_terms, dict):
        raw_terms = [{"source": k, "target": v} for k, v in raw_terms.items()]
    if isinstance(raw_terms, list):
        for t in raw_terms:
            if isinstance(t, dict) and isinstance(t.get("source"), str) and isinstance(t.get("target"), str):
                s, g = t["source"].strip(), t["target"].strip()
                if s and g and len(s) <= 80 and len(g) <= 80:
                    terms[s] = g

    return BatchResult(translations=[TranslatedParagraph(i, by_id[i]) for i in expected], terms=terms)


OCR_TYPES = {"heading", "paragraph", "list_item", "table", "formula"}


def parse_ocr_response(raw: str) -> list[dict]:
    """Validate an OCR answer: {"blocks": [{"type", "level"?, "text"}]} → clean blocks."""
    try:
        data: Any = json.loads(_FENCE_RE.sub("", raw or ""))
    except json.JSONDecodeError as e:
        raise InvalidResponseError(f"OCR response is not valid JSON ({e.msg})") from None
    blocks = data.get("blocks") if isinstance(data, dict) else data
    if not isinstance(blocks, list):
        raise InvalidResponseError("OCR response has no 'blocks' list")
    out: list[dict] = []
    for b in blocks:
        if not isinstance(b, dict) or not isinstance(b.get("text"), str) or not b["text"].strip():
            continue
        typ = b.get("type") if b.get("type") in OCR_TYPES else "paragraph"
        level = b.get("level") if typ == "heading" and b.get("level") in (1, 2, 3) else (3 if typ == "heading" else None)
        out.append({"type": typ, "level": level, "text": b["text"].strip()})
    return out
