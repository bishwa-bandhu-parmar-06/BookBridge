from app.services.chunker import chunk_paragraphs
from app.services.translator.base import TranslationItem


def _items(lengths: list[int]) -> list[TranslationItem]:
    return [TranslationItem(id=f"p{i}", text="x" * n) for i, n in enumerate(lengths)]


def test_never_splits_and_preserves_ids_and_order() -> None:
    items = _items([500, 700, 900, 300, 1500, 100, 2600, 50, 50])
    batches = chunk_paragraphs(items, max_chars=2000)
    flat = [it for b in batches for it in b]
    assert [it.id for it in flat] == [it.id for it in items]
    assert all(a is b for a, b in zip(flat, items)), "paragraph objects are passed through untouched"


def test_respects_limit_except_single_long_paragraph() -> None:
    items = _items([500, 700, 900, 300, 1500, 100, 2600, 50, 50])
    batches = chunk_paragraphs(items, max_chars=2000)
    for b in batches:
        total = sum(len(it.text) for it in b)
        assert total <= 2000 or len(b) == 1
    assert [len(b) for b in batches] == [2, 2, 2, 1, 2]
    assert any(len(b) == 1 and len(b[0].text) == 2600 for b in batches)


def test_empty_and_max_items() -> None:
    assert chunk_paragraphs([], 2000) == []
    batches = chunk_paragraphs(_items([1] * 100), max_chars=2000, max_items=40)
    assert [len(b) for b in batches] == [40, 40, 20]
