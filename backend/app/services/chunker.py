"""Group consecutive paragraphs into translation batches of about N characters.

A paragraph is never split. A paragraph longer than the limit becomes its own batch.
Order and ids are preserved exactly.
"""

from __future__ import annotations

from typing import Sequence, TypeVar

from app.services.translator.base import TranslationItem

T = TypeVar("T", bound=TranslationItem)


def chunk_paragraphs(items: Sequence[T], max_chars: int = 2000, max_items: int = 40) -> list[list[T]]:
    batches: list[list[T]] = []
    current: list[T] = []
    size = 0
    for it in items:
        n = len(it.text)
        if current and (size + n > max_chars or len(current) >= max_items):
            batches.append(current)
            current, size = [], 0
        current.append(it)
        size += n
    if current:
        batches.append(current)
    return batches
