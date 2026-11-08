"""Google Gemini translator (google-genai SDK). Key and model come from env only."""

from __future__ import annotations

import logging
import re
import time

from app.services.translator import prompts
from app.services.translator.base import (
    BatchContext,
    BatchResult,
    InvalidResponseError,
    Lang,
    RateLimitError,
    TranslationItem,
    Translator,
    TranslatorConfigError,
    TranslatorError,
    parse_batch_response,
    parse_ocr_response,
)

log = logging.getLogger(__name__)


_LEVELS = ["MINIMAL", "LOW", "MEDIUM", "HIGH"]

# HTTP codes meaning "the service is overloaded / temporarily failing": try another model,
# then back off like a rate limit.
_BUSY_CODES = {500, 502, 503, 504}
BUSY_COOLDOWN_SECONDS = 300.0
# Reading a whole scanned page takes longer than translating a batch.
OCR_TIMEOUT_MS = 70_000


class GeminiTranslator(Translator):
    """Gemini via google-genai. `models` is the preferred model first, then fallbacks that are
    tried when it is overloaded (503) or rate-limited (429)."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        fallback_models: list[str] | None = None,
        timeout_seconds: float = 25.0,
        temperature: float = 0.2,
        thinking_level: str = "minimal",
    ) -> None:
        if not api_key:
            raise TranslatorConfigError("GEMINI_API_KEY is not set")
        if not model:
            raise TranslatorConfigError("GEMINI_MODEL is not set")
        from google import genai
        from google.genai import types

        self._types = types
        self.models = list(dict.fromkeys([model, *(m for m in (fallback_models or []) if m)]))
        self.model = model
        self.temperature = temperature
        self._busy_until: dict[str, float] = {}
        # Thinking level per model; stepped up if a model rejects it (e.g. MINIMAL unsupported).
        level = (thinking_level or "default").strip().upper()
        self._thinking_ladder: list[str] = _LEVELS[_LEVELS.index(level):] if level in _LEVELS else []
        self._thinking: dict[str, str | None] = {}
        self._gone: dict[str, str] = {}  # model -> Google's "not found" message
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )

    def _generate(self, model: str, system: str, contents, schema: dict, timeout_ms: int | None = None):  # type: ignore[no-untyped-def]
        """One request; if the model rejects our thinking level, retry with the next level up
        (then the model's default) and remember what works for that model."""
        from google.genai import errors as genai_errors

        types = self._types
        ladder: list[str | None] = [self._thinking[model]] if model in self._thinking else [*self._thinking_ladder, None]
        last: Exception | None = None
        for level in ladder:
            cfg = types.GenerateContentConfig(
                system_instruction=system,
                temperature=self.temperature,
                response_mime_type="application/json",
                response_json_schema=schema,
                thinking_config=types.ThinkingConfig(thinking_level=level) if level else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                http_options=types.HttpOptions(timeout=timeout_ms) if timeout_ms else None,
            )
            try:
                resp = self.client.models.generate_content(model=model, contents=contents, config=cfg)
                self._thinking[model] = level
                return resp
            except genai_errors.APIError as e:
                if e.code == 400 and "thinking" in str(getattr(e, "message", "")).lower():
                    last = e
                    continue
                raise
        assert last is not None
        raise last

    def _candidates(self) -> list[str]:
        now = time.monotonic()
        live = [m for m in self.models if m not in self._gone]
        ready = [m for m in live if self._busy_until.get(m, 0) <= now]
        return ready or live  # if every model is cooling down, try them anyway

    def translate_batch(
        self,
        paragraphs: list[TranslationItem],
        source_lang: Lang,
        target_lang: Lang,
        glossary: dict[str, str],
        context: BatchContext,
    ) -> BatchResult:
        contents = prompts.user_prompt(paragraphs, glossary, context)
        system = prompts.system_prompt(source_lang, target_lang)
        return parse_batch_response(self._run(system, contents, prompts.RESPONSE_SCHEMA), paragraphs)

    def ocr_image(self, image: bytes, mime: str = "image/jpeg") -> list[dict]:
        """Read a scanned page image: the text in its original language, with structure."""
        types = self._types
        contents = [types.Part.from_bytes(data=image, mime_type=mime), prompts.OCR_USER]
        text = self._run(prompts.OCR_SYSTEM, contents, prompts.OCR_SCHEMA, timeout_ms=OCR_TIMEOUT_MS)
        return parse_ocr_response(text)

    def _run(self, system: str, contents, schema: dict, timeout_ms: int | None = None) -> str:  # type: ignore[no-untyped-def]
        """One JSON request with model fallback / busy handling; returns the response text."""
        from google.genai import errors as genai_errors

        rate_limited: list[float | None] = []
        busy = False
        candidates = self._candidates()
        if not candidates:
            raise TranslatorConfigError("No usable Gemini model: " + "; ".join(self._gone.values()))
        for model in candidates:
            try:
                resp = self._generate(model, system, contents, schema, timeout_ms)
            except genai_errors.APIError as e:
                msg = str(getattr(e, "message", "") or "")[:300]
                if e.code in (401, 403):
                    raise TranslatorConfigError(f"Gemini rejected the API key (HTTP {e.code}): {msg}") from None
                if e.code == 404:
                    self._gone[model] = f"{model}: {msg or 'not found'}"
                    log.warning("gemini model unavailable: %s", model)
                    continue
                if e.code == 429:
                    log.info("gemini quota hit on %s: %s", model, _quota_info(e))
                    rate_limited.append(_retry_after(e))
                    self._busy_until[model] = time.monotonic() + (_retry_after(e) or BUSY_COOLDOWN_SECONDS)
                    log.info("gemini model rate-limited: %s", model)
                    continue
                if e.code in _BUSY_CODES:
                    busy = True
                    self._busy_until[model] = time.monotonic() + BUSY_COOLDOWN_SECONDS
                    log.info("gemini model busy (HTTP %s): %s", e.code, model)
                    continue
                raise TranslatorError(f"Gemini error HTTP {e.code}: {msg}") from None
            except Exception as e:  # network errors, timeouts: treat the model as busy, try the next
                busy = True
                self._busy_until[model] = time.monotonic() + BUSY_COOLDOWN_SECONDS
                log.info("gemini model timed out / unreachable (%s): %s", type(e).__name__, model)
                continue

            self._busy_until.pop(model, None)
            if model != self.model:
                log.info("gemini fallback model used: %s", model)
            text = getattr(resp, "text", None)
            if not text:
                reason = ""
                try:
                    reason = str(resp.candidates[0].finish_reason)  # type: ignore[index]
                except Exception:  # noqa: BLE001
                    pass
                raise InvalidResponseError(f"empty response from Gemini {reason}".strip())
            return text

        if busy or rate_limited:
            waits = [w for w in rate_limited if w]
            raise RateLimitError(
                "Gemini is busy" if busy else "Gemini rate limit",
                retry_after=min(waits) if waits and not busy else None,
            )
        raise TranslatorConfigError("No usable Gemini model: " + "; ".join(self._gone.values()))


def _quota_info(e: Exception) -> str:
    """Which quota was exceeded, e.g. "GenerateRequestsPerMinutePerProjectPerModel-FreeTier limit=10"."""
    details = str(getattr(e, "details", "") or "")
    ids = re.findall(r"quotaId['\"]?\s*:\s*['\"]([^'\"]+)", details)
    vals = re.findall(r"quotaValue['\"]?\s*:\s*['\"]?(\d+)", details)
    return ", ".join(f"{q} limit={v}" for q, v in zip(ids, vals)) or "unknown quota"


def _retry_after(e: Exception) -> float | None:
    """Gemini puts e.g. "retryDelay": "21s" in the error details."""
    m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(getattr(e, "details", "") or e))
    return float(m.group(1)) if m else None
