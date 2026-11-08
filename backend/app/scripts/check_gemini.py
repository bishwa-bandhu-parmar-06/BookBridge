"""Check your Gemini setup before translating a book.

Usage (from backend/, with GEMINI_API_KEY in .env):
    python -m app.scripts.check_gemini --list     # list models your key can use for text generation
    python -m app.scripts.check_gemini            # translate two sample paragraphs with GEMINI_MODEL

Sends only the built-in sample sentences, never book content.
"""

from __future__ import annotations

import argparse
import sys
import time

from app.config import get_settings
from app.services.translator.base import (
    BatchContext,
    RateLimitError,
    TranslationItem,
    TranslatorConfigError,
    TranslatorError,
)

SAMPLES = [
    TranslationItem("s1", "Photosynthesis is the process by which green plants make their food using sunlight."),
    TranslationItem("s2", "The SI unit of force is the newton (N). F = ma"),
]
SAMPLES_HI = [
    TranslationItem("h1", "• भारत में किस भू-वैज्ञानिक एवं पुरातत्वविद ने प्रस्तर युगीन बस्तियों का अन्वेषण प्रारम्भ किया – राबर्ट ब्रूस फुट ने", "list_item"),
    TranslationItem("h2", "• प्रागैतिहासिक काल में मनुष्य अपना सांस्कृतिक जीवन कब से प्रारम्भ करता है – लगभग 30 लाख ई०पू०", "list_item"),
]


def list_models(api_key: str) -> int:
    from google import genai

    client = genai.Client(api_key=api_key)
    names = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions:
            names.append((m.name or "").removeprefix("models/"))
    if not names:
        print("No text-generation models found for this key.")
        return 1
    print("Models that support generateContent (set one as GEMINI_MODEL in backend/.env):")
    for n in sorted(names):
        print("  ", n)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check the Gemini API key and model.")
    ap.add_argument("--list", action="store_true", help="list available models instead of translating")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    s = get_settings()
    if not s.gemini_api_key:
        print("GEMINI_API_KEY is not set in backend/.env")
        return 2
    if args.list:
        return list_models(s.gemini_api_key)
    if not s.gemini_model:
        print("GEMINI_MODEL is not set in backend/.env. Run with --list to see available models.")
        return 2

    from app.services.translator.gemini import GeminiTranslator

    fallbacks = [m.strip() for m in s.gemini_fallback_models.split(",") if m.strip()]
    tr = GeminiTranslator(api_key=s.gemini_api_key, model=s.gemini_model, fallback_models=fallbacks)
    for src_lang, tgt_lang, samples in (("en", "hi", SAMPLES), ("hi", "en", SAMPLES_HI)):
        try:
            t0 = time.time()
            result = tr.translate_batch(samples, src_lang, tgt_lang, {}, BatchContext(chapter_title="Test"))
        except TranslatorConfigError as e:
            print(f"Configuration problem: {e}")
            return 1
        except RateLimitError:
            print("All configured models are busy or rate-limited right now. Try again in a few minutes,")
            print("or add more models to GEMINI_FALLBACK_MODELS (see --list).")
            return 1
        except TranslatorError as e:
            print(f"Request failed: {type(e).__name__}: {e}")
            return 1
        skipped = [m for m in tr.models if m in tr._busy_until or m in tr._gone]
        used = next((m for m in tr.models if m not in skipped), "?")
        print(f"OK {src_lang}→{tgt_lang}: model '{used}' answered in {time.time() - t0:.1f}s")
        for m in skipped:
            print(f"   (skipped '{m}': {tr._gone.get(m, 'busy or rate-limited right now')})")
        for src, out in zip(samples, result.translations):
            print(f"   {src_lang.upper()}: {src.text}\n   {tgt_lang.upper()}: {out.text}")
        if result.terms:
            print("   Glossary terms suggested:", result.terms)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
