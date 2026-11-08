import json

import pytest

from app.config import Settings
from app.services.translator import get_translator
from app.services.translator.base import (
    BatchContext,
    InvalidResponseError,
    TranslationItem,
    TranslatorConfigError,
    parse_batch_response,
)
from app.services.translator.mock import MockTranslator
from app.services.translator.prompts import system_prompt, user_prompt

ITEMS = [TranslationItem("p1", "Photosynthesis"), TranslationItem("p2", "Plants make food.")]


def _resp(entries, terms=None) -> str:  # type: ignore[no-untyped-def]
    return json.dumps({"translations": entries, "terms": terms or []}, ensure_ascii=False)


def test_parse_valid_with_terms() -> None:
    raw = _resp(
        [{"id": "p1", "text": "प्रकाश संश्लेषण"}, {"id": "p2", "text": "पौधे भोजन बनाते हैं।"}],
        [{"source": "Photosynthesis", "target": "प्रकाश संश्लेषण"}],
    )
    r = parse_batch_response(raw, ITEMS)
    assert [t.id for t in r.translations] == ["p1", "p2"]
    assert r.terms == {"Photosynthesis": "प्रकाश संश्लेषण"}


def test_parse_reorders_by_request_and_accepts_fences_and_bare_list() -> None:
    raw = "```json\n" + json.dumps([{"id": "p2", "text": "b"}, {"id": "p1", "text": "a"}]) + "\n```"
    r = parse_batch_response(raw, ITEMS)
    assert [(t.id, t.text) for t in r.translations] == [("p1", "a"), ("p2", "b")]


@pytest.mark.parametrize("raw", [
    "not json",
    json.dumps({"foo": 1}),
    _resp([{"id": "p1", "text": "a"}]),                                        # wrong count
    _resp([{"id": "p1", "text": "a"}, {"id": "p9", "text": "b"}]),             # wrong id
    _resp([{"id": "p1", "text": "a"}, {"id": "p1", "text": "b"}]),             # duplicate id
    _resp([{"id": "p1", "text": "a"}, {"id": "p2", "text": "   "}]),           # empty
    _resp([{"id": "p1", "text": "a"}, {"id": "p2"}]),                          # missing text
])
def test_parse_rejects_bad_responses(raw: str) -> None:
    with pytest.raises(InvalidResponseError):
        parse_batch_response(raw, ITEMS)


def test_prompts_contain_rules_glossary_and_context() -> None:
    sp = system_prompt("en", "hi")
    assert "from English to Hindi" in sp and "NCERT" in sp and "Return ONLY valid JSON" in sp
    assert "NCERT" not in system_prompt("hi", "en")
    up = user_prompt(ITEMS, {"Photosynthesis": "प्रकाश संश्लेषण"},
                     BatchContext(chapter_title="Nutrition", previous_translations=["पिछला"], note="use simpler words"))
    assert "Nutrition" in up and "प्रकाश संश्लेषण" in up and "पिछला" in up and "use simpler words" in up
    assert '"id": "p1"' in up


def test_mock_translator() -> None:
    r = MockTranslator().translate_batch(ITEMS, "hi", "en", {}, BatchContext())
    assert [t.text for t in r.translations] == ["[EN] Photosynthesis", "[EN] Plants make food."]


def test_factory() -> None:
    assert get_translator(Settings(translator="mock", _env_file=None)).name == "mock"  # type: ignore[call-arg]
    with pytest.raises(TranslatorConfigError):
        get_translator(Settings(translator="gemini", gemini_api_key="", gemini_model="x", _env_file=None))  # type: ignore[call-arg]
    with pytest.raises(TranslatorConfigError):
        get_translator(Settings(translator="gemini", gemini_api_key="k", gemini_model="", _env_file=None))  # type: ignore[call-arg]
