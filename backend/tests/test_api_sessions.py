"""Session summary, direction change, chapter boundary editing and delete."""

import json
import uuid

import pytest

from tests.conftest import BODY, make_pdf


@pytest.fixture
def session(client):  # type: ignore[no-untyped-def]
    c, root = client
    pdf = make_pdf([[(BODY, 11)]] * 12, toc=[[1, "Motion", 1], [1, "Force", 5], [1, "Work", 9]])
    r = c.post("/api/sessions", files={"file": ("book.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    return c, root, r.json()["session_id"]


def _start_translation(root, sid: str) -> None:  # type: ignore[no-untyped-def]
    p = root / sid / "state.json"
    st = json.loads(p.read_text(encoding="utf-8"))
    st["chapters"][0]["status"] = "translating"
    p.write_text(json.dumps(st), encoding="utf-8")


def test_get_summary(session) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = session
    body = c.get(f"/api/sessions/{sid}").json()
    assert body["page_count"] == 12
    assert [(ch["title"], ch["start_page"], ch["end_page"]) for ch in body["chapters"]] == [
        ("Motion", 1, 4), ("Force", 5, 8), ("Work", 9, 12),
    ]
    assert body["chapter_detection"] == "toc"
    assert body["boundaries_editable"] is True
    assert 7000 < body["seconds_remaining"] <= 7200


def test_unknown_and_malformed_session_ids(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    for sid in [str(uuid.uuid4()), "not-a-uuid", "..%2F..%2Fetc"]:
        r = c.get(f"/api/sessions/{sid}")
        assert r.status_code == 404
        assert r.json()["error"] in ("session_not_found", "not_found") and r.json()["message"]


def test_merge_and_split_chapters(session) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = session
    # merge Motion + Force, split Work into two
    new = {"chapters": [
        {"title": "Motion and Force", "start_page": 1, "end_page": 8},
        {"title": "Work (part 1)", "start_page": 9, "end_page": 10},
        {"title": "  Work (part 2) ", "start_page": 11, "end_page": 12},
    ]}
    r = c.put(f"/api/sessions/{sid}/chapters", json=new)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [ch["id"] for ch in body["chapters"]] == ["1", "2", "3"]
    assert body["chapters"][2]["title"] == "Work (part 2)"
    assert body["chapter_detection"] == "manual"
    assert c.get(f"/api/sessions/{sid}").json()["chapters"] == body["chapters"]


def test_skipping_pages_is_allowed(session) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = session
    r = c.put(f"/api/sessions/{sid}/chapters", json={"chapters": [{"title": "Only this", "start_page": 3, "end_page": 6}]})
    assert r.status_code == 200


@pytest.mark.parametrize("chapters, fragment", [
    ([{"title": "A", "start_page": 5, "end_page": 2}], "start page"),
    ([{"title": "A", "start_page": 1, "end_page": 13}], "only 12 pages"),
    ([{"title": "A", "start_page": 1, "end_page": 6}, {"title": "B", "start_page": 6, "end_page": 12}], "overlaps"),
    ([{"title": "B", "start_page": 7, "end_page": 12}, {"title": "A", "start_page": 1, "end_page": 6}], "overlaps"),
])
def test_invalid_boundaries(session, chapters, fragment) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = session
    r = c.put(f"/api/sessions/{sid}/chapters", json={"chapters": chapters})
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "invalid_chapters" and fragment in body["message"] and body["message_hi"]


@pytest.mark.parametrize("payload", [
    {"chapters": []},
    {"chapters": [{"title": "   ", "start_page": 1, "end_page": 2}]},
    {"chapters": [{"title": "A", "start_page": 0, "end_page": 2}]},
])
def test_malformed_boundaries(session, payload) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = session
    r = c.put(f"/api/sessions/{sid}/chapters", json=payload)
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"


def test_boundaries_locked_after_translation_starts(session) -> None:  # type: ignore[no-untyped-def]
    c, root, sid = session
    _start_translation(root, sid)
    r = c.put(f"/api/sessions/{sid}/chapters", json={"chapters": [{"title": "A", "start_page": 1, "end_page": 12}]})
    assert r.status_code == 409 and r.json()["error"] == "translation_started"
    assert c.get(f"/api/sessions/{sid}").json()["boundaries_editable"] is False


def test_change_direction(session) -> None:  # type: ignore[no-untyped-def]
    c, root, sid = session
    r = c.patch(f"/api/sessions/{sid}", json={"source_lang": "hi"})
    assert r.status_code == 200
    assert (r.json()["source_lang"], r.json()["target_lang"]) == ("hi", "en")
    _start_translation(root, sid)
    assert c.patch(f"/api/sessions/{sid}", json={"source_lang": "en"}).status_code == 409


def test_delete_session(session) -> None:  # type: ignore[no-untyped-def]
    c, root, sid = session
    r = c.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200 and r.json() == {"deleted": True}
    assert not (root / sid).exists()
    assert c.get(f"/api/sessions/{sid}").status_code == 404
    assert c.delete(f"/api/sessions/{sid}").status_code == 404


def test_public_config(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    assert c.get("/api/config").json() == {"max_upload_mb": 50, "max_pages": 500, "session_ttl_minutes": 120}
