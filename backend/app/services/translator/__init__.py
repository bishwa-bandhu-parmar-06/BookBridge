"""Translator factory. To add a provider (IndicTrans2, Bhashini…), add a module in this folder
and a branch here — nothing outside this folder needs to change."""

from __future__ import annotations

from app.config import Settings
from app.services.translator.base import Translator, TranslatorConfigError


def get_translator(settings: Settings) -> Translator:
    name = settings.translator
    if name == "mock":
        from app.services.translator.mock import MockTranslator

        return MockTranslator(delay_seconds=settings.mock_delay_seconds)
    if name == "gemini":
        from app.services.translator.gemini import GeminiTranslator

        return GeminiTranslator(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            fallback_models=[m.strip() for m in settings.gemini_fallback_models.split(",") if m.strip()],
            thinking_level=settings.gemini_thinking_level,
            timeout_seconds=settings.gemini_timeout_seconds,
        )
    raise TranslatorConfigError(f"Unknown TRANSLATOR '{name}'")
