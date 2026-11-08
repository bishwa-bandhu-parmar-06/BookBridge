"""GeminiTranslator without network: the SDK call is replaced by a fake."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from app.services.translator.base import (
    BatchContext,
    InvalidResponseError,
    RateLimitError,
    TranslationItem,
    TranslatorConfigError,
    TranslatorError,
)
from app.services.translator.gemini import GeminiTranslator

ITEMS = [TranslationItem("p1", "Force"), TranslationItem("p2", "Mass")]


def _translator(behaviour) -> tuple[GeminiTranslator, list]:  # type: ignore[no-untyped-def]
    t = GeminiTranslator(api_key="fake-key", model="test-model")
    calls: list = []

    def generate_content(**kw):  # type: ignore[no-untyped-def]
        calls.append(kw)
        return behaviour()

    t.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))  # type: ignore[assignment]
    return t, calls


def test_success_and_request_shape() -> None:
    body = {"translations": [{"id": "p1", "text": "बल"}, {"id": "p2", "text": "द्रव्यमान"}],
            "terms": [{"source": "Force", "target": "बल"}]}
    t, calls = _translator(lambda: SimpleNamespace(text=json.dumps(body, ensure_ascii=False)))
    r = t.translate_batch(ITEMS, "en", "hi", {"Force": "बल"}, BatchContext(chapter_title="Force"))
    assert [x.text for x in r.translations] == ["बल", "द्रव्यमान"] and r.terms == {"Force": "बल"}
    kw = calls[0]
    assert kw["model"] == "test-model"
    assert kw["config"].response_mime_type == "application/json"
    assert "from English to Hindi" in kw["config"].system_instruction
    assert '"p1"' in kw["contents"]


def _raise(code: int, details: dict | None = None):  # type: ignore[no-untyped-def]
    def f():  # type: ignore[no-untyped-def]
        raise genai_errors.ClientError(code, details or {"error": {"code": code, "message": "x", "status": "X"}})
    return f


def test_429_maps_to_rate_limit_with_retry_after() -> None:
    details = {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED",
                         "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "21s"}]}}
    t, _ = _translator(_raise(429, details))
    with pytest.raises(RateLimitError) as ei:
        t.translate_batch(ITEMS, "en", "hi", {}, BatchContext())
    assert ei.value.retry_after == 21


@pytest.mark.parametrize("code, exc", [(401, TranslatorConfigError), (403, TranslatorConfigError),
                                       (404, TranslatorConfigError), (400, TranslatorError),
                                       (503, RateLimitError), (500, RateLimitError)])
def test_other_errors(code: int, exc: type) -> None:
    t, _ = _translator(_raise(code))
    with pytest.raises(exc):
        t.translate_batch(ITEMS, "en", "hi", {}, BatchContext())


def test_empty_or_bad_json_is_invalid() -> None:
    for text in [None, "", "{not json"]:
        t, _ = _translator(lambda text=text: SimpleNamespace(text=text, candidates=[]))
        with pytest.raises(InvalidResponseError):
            t.translate_batch(ITEMS, "en", "hi", {}, BatchContext())


def test_requires_key_and_model() -> None:
    with pytest.raises(TranslatorConfigError):
        GeminiTranslator(api_key="", model="m")
    with pytest.raises(TranslatorConfigError):
        GeminiTranslator(api_key="k", model="")


OK_BODY = json.dumps({"translations": [{"id": "p1", "text": "a"}, {"id": "p2", "text": "b"}], "terms": []})


def _multi(behaviours: dict) -> tuple[GeminiTranslator, list]:  # type: ignore[type-arg]
    """behaviours: model -> callable raising or returning a response."""
    t = GeminiTranslator(api_key="fake-key", model="main", fallback_models=["fb1", "fb2"])
    calls: list = []

    def generate_content(**kw):  # type: ignore[no-untyped-def]
        calls.append(kw["model"])
        return behaviours[kw["model"]]()

    t.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))  # type: ignore[assignment]
    return t, calls


def _ok():  # type: ignore[no-untyped-def]
    return SimpleNamespace(text=OK_BODY)


def test_busy_model_falls_back_and_cools_down() -> None:
    t, calls = _multi({"main": _raise(503), "fb1": _ok, "fb2": _ok})
    r = t.translate_batch(ITEMS, "hi", "en", {}, BatchContext())
    assert [x.text for x in r.translations] == ["a", "b"]
    assert calls == ["main", "fb1"]
    t.translate_batch(ITEMS, "hi", "en", {}, BatchContext())
    assert calls == ["main", "fb1", "fb1"], "busy main model is skipped during its cooldown"


def test_gone_model_is_dropped_and_rate_limit_moves_on() -> None:
    t, calls = _multi({"main": _raise(404), "fb1": _raise(429), "fb2": _ok})
    t.translate_batch(ITEMS, "hi", "en", {}, BatchContext())
    assert calls == ["main", "fb1", "fb2"]
    assert "main" in t._gone


def test_all_busy_raises_rate_limit_for_backoff() -> None:
    t, _ = _multi({"main": _raise(503), "fb1": _raise(503), "fb2": _raise(429)})
    with pytest.raises(RateLimitError):
        t.translate_batch(ITEMS, "hi", "en", {}, BatchContext())


def test_all_models_gone_is_config_error() -> None:
    t, _ = _multi({"main": _raise(404), "fb1": _raise(404), "fb2": _raise(404)})
    with pytest.raises(TranslatorConfigError):
        t.translate_batch(ITEMS, "hi", "en", {}, BatchContext())


def test_timeout_falls_back_to_next_model() -> None:
    def hang():  # type: ignore[no-untyped-def]
        raise TimeoutError("read timed out")

    t, calls = _multi({"main": hang, "fb1": _ok, "fb2": _ok})
    t.translate_batch(ITEMS, "hi", "en", {}, BatchContext())
    assert calls == ["main", "fb1"]


def test_thinking_level_steps_up_when_model_rejects_it() -> None:
    t = GeminiTranslator(api_key="fake-key", model="m", thinking_level="minimal")
    seen: list = []

    def generate_content(**kw):  # type: ignore[no-untyped-def]
        tc = kw["config"].thinking_config
        level = tc.thinking_level if tc else None
        seen.append(str(level))
        if level is not None and "MINIMAL" in str(level):
            raise genai_errors.ClientError(400, {"error": {"code": 400, "message": "Thinking level MINIMAL is not supported for this model.", "status": "INVALID_ARGUMENT"}})
        return SimpleNamespace(text=OK_BODY)

    t.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))  # type: ignore[assignment]
    t.translate_batch(ITEMS, "hi", "en", {}, BatchContext())
    t.translate_batch(ITEMS, "hi", "en", {}, BatchContext())
    assert len(seen) == 3 and "MINIMAL" in seen[0] and "LOW" in seen[1] and "LOW" in seen[2], seen
