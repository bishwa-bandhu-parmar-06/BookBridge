"""Retry / backoff / per-paragraph fallback, using scripted mock translators."""

from __future__ import annotations

import pytest

from app.services.translation import RetryPolicy, translate_with_retry
from app.services.translator.base import (
    BatchContext,
    BatchResult,
    InvalidResponseError,
    RateLimitError,
    TranslatedParagraph,
    TranslationItem,
    Translator,
    TranslatorConfigError,
)

ITEMS = [TranslationItem(f"p{i}", f"text {i}") for i in range(3)]


class Scripted(Translator):
    """Fails according to `script` (a list of exceptions or None=success) for batch calls;
    single-paragraph calls fail for ids in `bad_ids`."""

    def __init__(self, script: list[Exception | None], bad_ids: set[str] = frozenset(), terms=None) -> None:  # type: ignore[assignment,no-untyped-def]
        self.script = list(script)
        self.bad_ids = bad_ids
        self.calls: list[list[str]] = []
        self.terms = terms or {}

    def translate_batch(self, paragraphs, source_lang, target_lang, glossary, context):  # type: ignore[no-untyped-def]
        self.calls.append([p.id for p in paragraphs])
        if len(paragraphs) > 1 or not self.bad_ids:
            if self.script:
                step = self.script.pop(0)
                if step is not None:
                    raise step
        if len(paragraphs) == 1 and paragraphs[0].id in self.bad_ids:
            raise InvalidResponseError("bad")
        return BatchResult([TranslatedParagraph(p.id, "T:" + p.text) for p in paragraphs], dict(self.terms))


class Misaligned(Translator):
    def translate_batch(self, paragraphs, *a):  # type: ignore[no-untyped-def]
        return BatchResult([TranslatedParagraph("zzz", "x") for _ in paragraphs])


def run(tr: Translator, items=ITEMS, policy=None):  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    statuses: list[str] = []
    out = translate_with_retry(tr, items, "en", "hi", {}, BatchContext(), policy or RetryPolicy(),
                               sleep=sleeps.append, on_status=statuses.append)
    return out, sleeps, statuses


def test_success_first_try() -> None:
    out, sleeps, _ = run(Scripted([None], terms={"a": "b"}))
    assert out.translations == ["T:text 0", "T:text 1", "T:text 2"]
    assert out.terms == {"a": "b"} and sleeps == []


def test_retries_with_exponential_backoff_then_succeeds() -> None:
    tr = Scripted([InvalidResponseError("x"), InvalidResponseError("y"), None])
    out, sleeps, _ = run(tr)
    assert out.translations[0] == "T:text 0" and not out.used_fallback
    assert sleeps == [1.0, 2.0]
    assert len(tr.calls) == 3


class PoisonId(Translator):
    """Fails any batch that contains the poisoned paragraph id."""

    def __init__(self, bad: str) -> None:
        self.bad = bad
        self.calls: list[list[str]] = []

    def translate_batch(self, paragraphs, *a):  # type: ignore[no-untyped-def]
        ids = [p.id for p in paragraphs]
        self.calls.append(ids)
        if self.bad in ids:
            raise InvalidResponseError("bad")
        return BatchResult([TranslatedParagraph(p.id, "T:" + p.text) for p in paragraphs])


def test_failed_batch_is_split_in_half_until_the_bad_paragraph_is_isolated() -> None:
    items = [TranslationItem(f"p{i}", f"text {i}") for i in range(16)]
    tr = PoisonId("p5")
    sleeps: list[float] = []
    statuses: list[str] = []
    out = translate_with_retry(tr, items, "hi", "en", {}, BatchContext(), RetryPolicy(), sleep=sleeps.append, on_status=statuses.append)
    assert out.used_fallback
    assert out.translations == [None if i == 5 else f"T:text {i}" for i in range(16)]
    # 16 -> 8 -> 4 -> 2 -> 1: far fewer requests than retrying all 16 paragraphs one by one
    assert len(tr.calls) < 30
    assert sum(1 for c in tr.calls if len(c) == 1) <= 2 * 3
    assert any("smaller parts" in s for s in statuses)


def test_misaligned_response_is_treated_as_invalid() -> None:
    out, _, _ = run(Misaligned())
    assert out.translations == [None, None, None]


def test_rate_limit_uses_retry_after_and_reports_busy() -> None:
    tr = Scripted([RateLimitError(retry_after=7), RateLimitError(), None])
    out, sleeps, statuses = run(tr)
    assert out.translations[2] == "T:text 2"
    assert sleeps == [7, 10.0]  # retry_after, then base 5 * 2
    assert sum("busy" in s for s in statuses) == 2


def test_rate_limit_exhaustion_propagates() -> None:
    tr = Scripted([RateLimitError()] * 10)
    with pytest.raises(RateLimitError):
        run(tr, policy=RetryPolicy(max_rate_limit_retries=3))


def test_config_error_is_not_retried() -> None:
    tr = Scripted([TranslatorConfigError("no key")])
    with pytest.raises(TranslatorConfigError):
        run(tr)
    assert len(tr.calls) == 1
