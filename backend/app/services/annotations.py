"""Student annotations on translated text: highlights (character ranges), a note, and a star.

Stored per chapter in state["chapters"][i]["annotations"] = {paragraph_id: {...}}.
Highlights are ranges in the paragraph's *translated* text, saved with a fingerprint of that
text: if the translation is later edited or re-translated, its highlights are hidden instead
of landing on the wrong words (notes and stars are kept).
"""

from __future__ import annotations

import hashlib
from typing import Any

COLORS = ("yellow", "green", "pink", "blue")


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def display_text(p: dict[str, Any]) -> str:
    """The text a student reads and highlights: the translation (or the original if missing)."""
    return p.get("translated") or p["original"]


def clean_highlights(highlights: list[dict[str, Any]], length: int) -> list[dict[str, Any]]:
    out = []
    for h in highlights:
        start, end = max(0, int(h["start"])), min(length, int(h["end"]))
        if end > start and h.get("color") in COLORS:
            out.append({"start": start, "end": end, "color": h["color"]})
    out.sort(key=lambda h: (h["start"], h["end"]))
    return out


def live(chapter: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Annotations to show: highlights dropped where the text changed since they were made."""
    paras = {p["id"]: p for p in chapter.get("paragraphs", [])}
    out: dict[str, dict[str, Any]] = {}
    for pid, a in (chapter.get("annotations") or {}).items():
        p = paras.get(pid)
        if p is None:
            continue
        fresh = a.get("text_hash") == text_hash(display_text(p))
        item = {
            "highlights": a.get("highlights", []) if fresh else [],
            "note": a.get("note", ""),
            "star": bool(a.get("star")),
        }
        if item["highlights"] or item["note"] or item["star"]:
            out[pid] = item
    return out


def segments(text: str, highlights: list[dict[str, Any]], start: int = 0, end: int | None = None) -> list[tuple[str, str | None]]:
    """Split text[start:end] into (piece, colour-or-None) runs. Later highlights win on overlap."""
    end = len(text) if end is None else end
    if start >= end:
        return []
    colors: list[str | None] = [None] * (end - start)
    for h in highlights:
        for i in range(max(h["start"], start), min(h["end"], end)):
            colors[i - start] = h["color"]
    out: list[tuple[str, str | None]] = []
    run_start = start
    for i in range(start + 1, end + 1):
        if i == end or colors[i - start] != colors[run_start - start]:
            out.append((text[run_start:i], colors[run_start - start]))
            run_start = i
    return out
