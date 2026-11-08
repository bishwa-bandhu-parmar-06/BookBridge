"""Prompt text for LLM translators. Edit wording here, not in the provider code."""

from __future__ import annotations

import json

from app.services.translator.base import LANG_NAMES, BatchContext, Lang, TranslationItem

SYSTEM_PROMPT = """\
You translate school and college textbook content from {source} to {target} for students.

Rules:
- Preserve every concept, fact, number, unit, example, and instruction. Do not summarize, skip, simplify, or add anything.
- Keep the academic register used in {target}-medium textbooks in India.{hindi_rule}
- For important technical terms, add the original term in brackets the first time it appears in each chapter, \
e.g. "Photosynthesis (प्रकाश संश्लेषण)" or "प्रकाश संश्लेषण (Photosynthesis)".
- Follow the provided glossary strictly for consistency.
- Keep formulas, numbers, symbols, variable names, and chemical formulas unchanged.
- Translate each item separately. Never merge, split, reorder, or drop items. Keep each item's "id" exactly.
- Headings stay short headings; list items keep their numbering or bullet marker.
- Items of type "table" are tables: one row per line, cells separated by " | ". Keep exactly the same number of lines and the same number of " | " separators in every line; translate each cell in place and leave empty cells empty.
- Many items are exam-style question–answer pairs: "• <question> – <answer>". Keep this exact shape: translate \
the question, then " – " (always this spaced dash, even if the source uses "-" or "–" without spaces), then the answer. Do not turn the answer into a full sentence.
- Write names of people, places, dynasties, texts, and events with the standard spellings used in Indian \
textbooks and competitive-exam books (e.g. Bhimbetka, Chandragupta Maurya, Harappa, Arthashastra, Mehrgarh).
- Keep dates and eras as written in the source style, e.g. "ई०पू०" → "BC", "ई०" → "AD"/"CE" consistently.
- The source text may come from an old printed book and contain small spelling mistakes; translate what the \
author clearly meant.
- Return ONLY valid JSON in the required format.

Required JSON format:
{{
  "translations": [{{"id": "<same id>", "text": "<translation>"}}, ...],
  "terms": [{{"source": "<{source} technical term>", "target": "<{target} term>"}}, ...]
}}
"translations" must contain exactly one entry per input item, in the same order.
"terms" lists the key technical terms used in these items (at most 15), for the book's glossary.
"""

_HINDI_RULE = (
    " For Hindi output, use the standard Hindi terminology used in Indian textbooks (NCERT style), "
    "not overly Sanskritized or casual words."
)


def system_prompt(source_lang: Lang, target_lang: Lang) -> str:
    return SYSTEM_PROMPT.format(
        source=LANG_NAMES[source_lang],
        target=LANG_NAMES[target_lang],
        hindi_rule=_HINDI_RULE if target_lang == "hi" else "",
    )


def user_prompt(items: list[TranslationItem], glossary: dict[str, str], context: BatchContext) -> str:
    parts: list[str] = []
    if context.book_title:
        parts.append(f"Book: {context.book_title}")
    if context.chapter_title:
        parts.append(f"Chapter: {context.chapter_title}")
    if glossary:
        parts.append("Glossary (use these translations exactly):\n" + json.dumps(glossary, ensure_ascii=False))
    if context.previous_translations:
        parts.append(
            "Previous paragraphs, for continuity only (do not translate or repeat them):\n"
            + "\n".join(context.previous_translations)
        )
    if context.note:
        parts.append(f"Extra instruction from the student for this re-translation: {context.note}")
    payload = [{"id": it.id, "type": it.type, "text": it.text} for it in items]
    parts.append("Items to translate:\n" + json.dumps(payload, ensure_ascii=False, indent=1))
    return "\n\n".join(parts)


# JSON schema handed to providers that support structured output.
RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"],
            },
        },
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"source": {"type": "string"}, "target": {"type": "string"}},
                "required": ["source", "target"],
            },
        },
    },
    "required": ["translations", "terms"],
}


# --- OCR: reading scanned pages -----------------------------------------------------------------

OCR_SYSTEM = """\
You are an OCR engine for scanned pages of Indian textbooks and competitive-exam books (Hindi or English).
Transcribe ALL the text on the page exactly as printed, in Unicode, in its ORIGINAL language.
Do NOT translate, summarize, explain, or correct anything.

Rules:
- Reading order: for two-column pages, the whole left column first, then the right column.
- Skip running headers, footers, page numbers, watermarks and purely decorative text.
- One block per heading, paragraph, point or table. Never merge separate points.
- Headings: type "heading" with level 1 (part/chapter title), 2 (section bar), or 3 (sub-heading).
- A bulleted question with its answer is ONE "list_item": "• <question> – <answer>".
- Numbered points are "list_item" starting with their number ("1. ...").
- Tables and side-by-side charts: type "table", one row per line, cells separated by " | ".
  A whole table (with its title row, if any) is ONE block: all its rows in one "text", separated by newlines.
- A box with a title and numbered points is NOT a table: a "heading" (level 3) followed by one "list_item" per point.
- Formulas and equations: type "formula", exactly as printed.
- Write Devanagari correctly (matras, conjuncts, nukta). Keep numbers, dates and names exactly.
Return ONLY JSON: {"blocks": [{"type": "...", "level": 1|2|3 (headings only), "text": "..."}]}
"""

OCR_USER = "Transcribe this page."

OCR_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["heading", "paragraph", "list_item", "table", "formula"]},
                    "level": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["type", "text"],
            },
        }
    },
    "required": ["blocks"],
}
