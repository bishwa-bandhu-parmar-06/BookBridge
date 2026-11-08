"""Study tools: highlights, notes, stars, text size — in the API and in the PDF."""

from __future__ import annotations

from app.services import annotations
from app.services.pdf_writer import answer_spans, render_chapter_html
from tests.conftest import BODY, make_pdf


def test_segments_and_overlaps() -> None:
    text = "Who discovered Harappa – Daya Ram Sahni"
    hl = [{"start": 0, "end": 3, "color": "yellow"}, {"start": 25, "end": 39, "color": "green"}]
    assert annotations.segments(text, hl) == [
        ("Who", "yellow"), (" discovered Harappa – ", None), ("Daya Ram Sahni", "green"),
    ]
    # later highlight wins where they overlap; a sub-range is split correctly
    assert annotations.segments("abcdef", [{"start": 0, "end": 4, "color": "pink"}, {"start": 2, "end": 6, "color": "blue"}], 1, 5) == [
        ("b", "pink"), ("cde", "blue"),
    ]
    assert annotations.clean_highlights([{"start": -5, "end": 99, "color": "yellow"}, {"start": 3, "end": 3, "color": "pink"},
                                         {"start": 1, "end": 2, "color": "purple"}], 10) == [{"start": 0, "end": 10, "color": "yellow"}]


def test_answer_spans_offsets() -> None:
    text = "• Who discovered Harappa – Daya Ram Sahni"
    q_end, a_start, a_end = answer_spans(text)  # type: ignore[misc]
    assert text[:q_end] == "• Who discovered Harappa" and text[a_start:a_end] == "Daya Ram Sahni"


def _session(client):  # type: ignore[no-untyped-def]
    c, root = client
    sid = c.post("/api/sessions", files={"file": ("b.pdf", make_pdf([[("Chapter 1", 20), (BODY, 11)], [("Chapter 2", 20), (BODY, 11)]]))}).json()["session_id"]
    assert c.post(f"/api/sessions/{sid}/chapters/1/translate").status_code == 202
    paras = c.get(f"/api/sessions/{sid}/chapters/1").json()["paragraphs"]
    target = next(p for p in paras if p["type"] == "paragraph")
    return c, sid, target


def test_save_load_and_clear_annotation(client) -> None:  # type: ignore[no-untyped-def]
    c, sid, p = _session(client)
    url = f"/api/sessions/{sid}/chapters/1/annotations/{p['id']}"
    body = {"highlights": [{"start": 5, "end": 15, "color": "green"}, {"start": 0, "end": 9999, "color": "yellow"}],
            "note": "  Important for exam  ", "star": True}
    r = c.put(url, json=body)
    assert r.status_code == 200
    saved = r.json()
    assert saved["note"] == "Important for exam" and saved["star"] is True
    assert saved["highlights"][0] == {"start": 0, "end": len(p["translated"]), "color": "yellow"}  # clipped + sorted

    ann = c.get(f"/api/sessions/{sid}/chapters/1").json()["annotations"]
    assert ann[p["id"]]["star"] is True and len(ann[p["id"]]["highlights"]) == 2

    # editing the translation hides now-stale highlights but keeps the note and star
    c.patch(f"/api/sessions/{sid}/chapters/1/paragraphs/{p['id']}", json={"translated": "A different text"})
    ann = c.get(f"/api/sessions/{sid}/chapters/1").json()["annotations"][p["id"]]
    assert ann["highlights"] == [] and ann["note"] == "Important for exam" and ann["star"] is True

    # an empty annotation removes it
    assert c.put(url, json={"highlights": [], "note": "", "star": False}).status_code == 200
    assert p["id"] not in c.get(f"/api/sessions/{sid}/chapters/1").json()["annotations"]


def test_annotation_rules(client) -> None:  # type: ignore[no-untyped-def]
    c, sid, p = _session(client)
    assert c.put(f"/api/sessions/{sid}/chapters/2/annotations/x", json={"star": True}).json()["error"] == "chapter_wrong_status"
    assert c.put(f"/api/sessions/{sid}/chapters/1/annotations/nope", json={"star": True}).json()["error"] == "paragraph_not_found"
    assert c.put(f"/api/sessions/{sid}/chapters/1/annotations/{p['id']}", json={"highlights": [{"start": 0, "end": 2, "color": "red"}]}).status_code == 422


def _ch(**over):  # type: ignore[no-untyped-def]
    para = {"id": "q", "page": 1, "type": "list_item", "level": None, "group": None, "flagged": False, "edited": False,
            "error": False, "original": "x", "translated": "• Who discovered Harappa – Daya Ram Sahni"}
    ch = {"id": "1", "title": "Harappa", "translated_title": "Harappa", "start_page": 1, "end_page": 1,
          "status": "review", "paragraphs": [para],
          "annotations": {"q": {"highlights": [{"start": 6, "end": 16, "color": "pink"}], "note": "Remember this",
                                "star": True, "text_hash": annotations.text_hash(para["translated"])}}}
    ch.update(over)
    return ch


STATE = {"book_title": "Book", "source_lang": "hi", "target_lang": "en"}


def test_pdf_html_has_highlights_note_star_and_font_scale() -> None:
    html = render_chapter_html(STATE, _ch(), [], font_scale=1.4)
    assert '<mark class="hl-pink">discovered</mark>' in html
    assert '<span class="star">★ </span>' in html and "Remember this" in html
    assert "font-size: 15.40pt" in html  # 11pt body × 1.4
    plain = render_chapter_html(STATE, _ch(), [], annotate=False)
    assert "<mark" not in plain and "Remember this" not in plain and "font-size: 11.00pt" in plain


def test_pdf_endpoint_options(client) -> None:  # type: ignore[no-untyped-def]
    c, sid, p = _session(client)
    assert c.get(f"/api/sessions/{sid}/chapters/1/preview?font_scale=3").status_code == 422
    assert c.get(f"/api/sessions/{sid}/chapters/1/pdf?font_scale=0.5").status_code == 422
