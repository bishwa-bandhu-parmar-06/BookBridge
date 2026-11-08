"""MockTranslator: returns "[EN] " + text (or "[HI] "), so the whole flow works without an API key."""

from __future__ import annotations

import time

from app.services.translator.base import (
    BatchContext,
    BatchResult,
    Lang,
    TranslatedParagraph,
    TranslationItem,
    Translator,
)


class MockTranslator(Translator):
    name = "mock"

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self.delay_seconds = delay_seconds  # simulate latency so progress bars can be seen

    def translate_batch(
        self,
        paragraphs: list[TranslationItem],
        source_lang: Lang,
        target_lang: Lang,
        glossary: dict[str, str],
        context: BatchContext,
    ) -> BatchResult:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        prefix = f"[{target_lang.upper()}] "
        return BatchResult(translations=[TranslatedParagraph(p.id, prefix + p.text) for p in paragraphs])

    def ocr_image(self, image: bytes, mime: str = "image/jpeg") -> list[dict]:
        """Pretend to read a scanned page (for tests and offline demos)."""
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return [
            {"type": "heading", "level": 2, "text": "स्कैन किया गया पृष्ठ"},
            {"type": "list_item", "level": None, "text": "• हड़प्पा सभ्यता की खोज किस वर्ष की गई थी – वर्ष 1921 में"},
            {"type": "table", "level": None, "text": "विद्वान | तिथि\nजान मार्शल | 3250 ई०पू०"},
        ]
