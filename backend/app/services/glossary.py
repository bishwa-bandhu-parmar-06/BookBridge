"""Per-session term glossary, stored in state["glossary"].

Shape: {source_term: {"target": str, "origin": "model" | "user"}}
- Terms suggested by the model are added only if the term is not already present,
  so the first translation of a term stays consistent across the book.
- User edits always win and are never overwritten by the model.
"""

from __future__ import annotations

from typing import Any, Literal

Glossary = dict[str, dict[str, str]]
Origin = Literal["model", "user"]

MAX_TERMS = 2000
MAX_TERMS_PER_PROMPT = 80


def merge_model_terms(glossary: Glossary, terms: dict[str, str]) -> int:
    """Add model-suggested terms. Returns how many were added."""
    existing_lower = {k.lower() for k in glossary}
    added = 0
    for src, tgt in terms.items():
        src, tgt = src.strip(), tgt.strip()
        if not src or not tgt or src.lower() in existing_lower or len(glossary) >= MAX_TERMS:
            continue
        glossary[src] = {"target": tgt, "origin": "model"}
        existing_lower.add(src.lower())
        added += 1
    return added


def replace_with_user_terms(glossary: Glossary, terms: list[tuple[str, str]]) -> Glossary:
    """Full replacement from the user's edited list.

    Entries identical to an existing model entry keep origin "model"; anything new or changed
    becomes "user". Terms left out are deleted.
    """
    out: Glossary = {}
    for src, tgt in terms:
        src, tgt = src.strip(), tgt.strip()
        if not src or not tgt:
            continue
        old = glossary.get(src)
        origin = old["origin"] if old and old["target"] == tgt else "user"
        out[src] = {"target": tgt, "origin": origin}
    return out


def relevant_terms(glossary: Glossary, texts: list[str], limit: int = MAX_TERMS_PER_PROMPT) -> dict[str, str]:
    """Only the glossary terms that occur in `texts` (user terms first), to keep prompts small."""
    haystack = "\n".join(texts).lower()
    hits = [(k, v) for k, v in glossary.items() if k.lower() in haystack]
    hits.sort(key=lambda kv: (kv[1]["origin"] != "user", -len(kv[0])))
    return {k: v["target"] for k, v in hits[:limit]}


def as_list(glossary: Glossary) -> list[dict[str, Any]]:
    return [{"source": k, "target": v["target"], "origin": v["origin"]} for k, v in sorted(glossary.items(), key=lambda kv: kv[0].lower())]
