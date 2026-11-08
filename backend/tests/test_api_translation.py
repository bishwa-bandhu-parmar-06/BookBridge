"""End-to-end translation flow with the MockTranslator (no API key needed).

TestClient runs BackgroundTasks right after the response, so jobs are finished when
the POST returns.
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings, get_settings
from app.deps import get_translator_dep
from app.main import app
from app.services.translator.base import BatchResult, TranslatedParagraph, Translator
from tests.conftest import BODY, make_pdf


@pytest.fixture
def session(client):  # type: ignore[no-untyped-def]
    c, root = client
    pages = [
        [("Chapter 1", 20), ("Motion", 16), (BODY, 11), ("v = u + at", 11), (BODY, 11)],
        [(BODY, 11)],
        [("Chapter 2", 20), ("Force", 16), (BODY, 11)],
        [(BODY, 11)],
    ]
    r = c.post("/api/sessions", files={"file": ("book.pdf", make_pdf(pages), "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [ch["start_page"] for ch in body["chapters"]] == [1, 3]
    return c, root, body["session_id"]


def _translate(c, sid: str, cid: str = "1"):  # type: ignore[no-untyped-def]
    r = c.post(f"/api/sessions/{sid}/chapters/{cid}/translate")
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def test_translate_chapter_flow(session) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = session
    job_id = _translate(c, sid)
    job = c.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done" and job["progress"] == 100

    ch = c.get(f"/api/sessions/{sid}/chapters/1").json()
    assert ch["status"] == "review" and ch["active_job_id"] is None
    paras = ch["paragraphs"]
    assert paras and all(p["page"] in (1, 2) for p in paras)
    for p in paras:
        if p["type"] == "formula":
            assert p["translated"] == p["original"] == "v = u + at"
        else:
            assert p["translated"] == "[HI] " + p["original"]

    # chapter 2 untouched until asked
    ch2 = c.get(f"/api/sessions/{sid}/chapters/2").json()
    assert ch2["status"] == "pending" and ch2["paragraphs"] == []

    # boundaries are now locked
    assert c.get(f"/api/sessions/{sid}").json()["boundaries_editable"] is False
    # translating the same chapter again is refused
    r = c.post(f"/api/sessions/{sid}/chapters/1/translate")
    assert r.status_code == 409 and r.json()["error"] == "chapter_wrong_status"


def test_edit_flag_retranslate_approve(session) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = session
    _translate(c, sid)
    paras = c.get(f"/api/sessions/{sid}/chapters/1").json()["paragraphs"]
    text_ids = [p["id"] for p in paras if p["type"] != "formula"]
    formula_id = next(p["id"] for p in paras if p["type"] == "formula")

    # manual edit
    r = c.patch(f"/api/sessions/{sid}/chapters/1/paragraphs/{text_ids[0]}", json={"translated": "मेरा अनुवाद"})
    assert r.status_code == 200 and r.json()["translated"] == "मेरा अनुवाद" and r.json()["edited"] is True
    # flag
    r = c.patch(f"/api/sessions/{sid}/chapters/1/paragraphs/{text_ids[1]}", json={"flagged": True})
    assert r.json()["flagged"] is True

    # capture the note passed to the translator
    seen: dict = {}

    class NoteTranslator(Translator):
        def translate_batch(self, paragraphs, s, t, glossary, context):  # type: ignore[no-untyped-def]
            seen["note"], seen["ids"] = context.note, [p.id for p in paragraphs]
            return BatchResult([TranslatedParagraph(p.id, "सरल: " + p.text) for p in paragraphs])

    app.dependency_overrides[get_translator_dep] = lambda: NoteTranslator()
    r = c.post(f"/api/sessions/{sid}/chapters/1/retranslate", json={"paragraph_ids": [text_ids[1]], "note": "use simpler words"})
    assert r.status_code == 202, r.text
    assert seen == {"note": "use simpler words", "ids": [text_ids[1]]}
    paras = {p["id"]: p for p in c.get(f"/api/sessions/{sid}/chapters/1").json()["paragraphs"]}
    assert paras[text_ids[1]]["translated"].startswith("सरल: ") and paras[text_ids[1]]["flagged"] is False
    assert paras[text_ids[0]]["translated"] == "मेरा अनुवाद", "other paragraphs untouched"

    # bad re-translate requests
    r = c.post(f"/api/sessions/{sid}/chapters/1/retranslate", json={"paragraph_ids": [formula_id]})
    assert r.status_code == 400
    r = c.post(f"/api/sessions/{sid}/chapters/1/retranslate", json={"paragraph_ids": ["nope"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_paragraphs"
    assert c.get(f"/api/sessions/{sid}/chapters/1").json()["status"] == "review"

    # approve
    r = c.post(f"/api/sessions/{sid}/chapters/1/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    # cannot approve a pending chapter
    assert c.post(f"/api/sessions/{sid}/chapters/2/approve").status_code == 409


def test_failed_paragraphs_block_approval(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    c, root, sid = session

    class Broken(Translator):
        def translate_batch(self, paragraphs, *a):  # type: ignore[no-untyped-def]
            return BatchResult([TranslatedParagraph(p.id, "") for p in paragraphs])  # always invalid

    app.dependency_overrides[get_translator_dep] = lambda: Broken()
    import app.services.translation as tr_mod

    monkeypatch.setattr(tr_mod.time, "sleep", lambda _s: None)
    job_id = _translate(c, sid)
    job = c.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done" and "could not be translated" in job["message"]
    ch = c.get(f"/api/sessions/{sid}/chapters/1").json()
    assert ch["status"] == "review"
    assert all(p["error"] and p["flagged"] for p in ch["paragraphs"] if p["type"] != "formula")
    r = c.post(f"/api/sessions/{sid}/chapters/1/approve")
    assert r.status_code == 409 and r.json()["error"] == "untranslated_paragraphs"


def test_one_job_per_session(session) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = session
    from app.services.jobs import get_jobs

    jobs = app.dependency_overrides[get_jobs]()
    jobs.start(sid, "2", "translate")  # pretend chapter 2 is running
    r = c.post(f"/api/sessions/{sid}/chapters/1/translate")
    assert r.status_code == 409 and r.json()["error"] == "job_running"


def test_stale_translating_chapter_is_reconciled(session) -> None:  # type: ignore[no-untyped-def]
    c, root, sid = session
    p = root / sid / "state.json"
    st = json.loads(p.read_text(encoding="utf-8"))
    st["chapters"][0]["status"] = "translating"  # e.g. server restarted mid-job
    p.write_text(json.dumps(st), encoding="utf-8")
    assert c.get(f"/api/sessions/{sid}/chapters/1").json()["status"] == "failed"
    # and a failed chapter can be translated again
    _translate(c, sid)
    assert c.get(f"/api/sessions/{sid}/chapters/1").json()["status"] == "review"


def test_glossary_from_model_and_user_edits(session) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = session

    class TermTranslator(Translator):
        def translate_batch(self, paragraphs, s, t, glossary, context):  # type: ignore[no-untyped-def]
            return BatchResult([TranslatedParagraph(p.id, "अ " + p.text) for p in paragraphs],
                               {"force": "बल", "momentum": "संवेग"})

    app.dependency_overrides[get_translator_dep] = lambda: TermTranslator()
    _translate(c, sid)
    g = c.get(f"/api/sessions/{sid}/glossary").json()
    assert (g["source_lang"], g["target_lang"]) == ("en", "hi")
    assert {(t["source"], t["target"], t["origin"]) for t in g["terms"]} == {("force", "बल", "model"), ("momentum", "संवेग", "model")}

    r = c.put(f"/api/sessions/{sid}/glossary", json={"terms": [{"source": "force", "target": "बल"}, {"source": "momentum", "target": "आवेग"}]})
    assert r.status_code == 200
    terms = {t["source"]: (t["target"], t["origin"]) for t in r.json()["terms"]}
    assert terms == {"force": ("बल", "model"), "momentum": ("आवेग", "user")}

    # the glossary is passed into later batches (chapter 2)
    seen: list[dict] = []

    class Spy(Translator):
        def translate_batch(self, paragraphs, s, t, glossary, context):  # type: ignore[no-untyped-def]
            seen.append(dict(glossary))
            return BatchResult([TranslatedParagraph(p.id, "x") for p in paragraphs], {"momentum": "WRONG"})

    app.dependency_overrides[get_translator_dep] = lambda: Spy()
    _translate(c, sid, "2")
    assert any(g.get("momentum") == "आवेग" for g in seen)
    terms = {t["source"]: t["target"] for t in c.get(f"/api/sessions/{sid}/glossary").json()["terms"]}
    assert terms["momentum"] == "आवेग", "user term must not be overwritten"


def test_translator_not_configured(session) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = session
    bad = Settings(translator="gemini", gemini_api_key="", gemini_model="", _env_file=None)  # type: ignore[call-arg]
    app.dependency_overrides[get_settings] = lambda: bad
    r = c.post(f"/api/sessions/{sid}/chapters/1/translate")
    assert r.status_code == 503 and r.json()["error"] == "translator_not_configured"


def test_unknown_job_and_chapter(session) -> None:  # type: ignore[no-untyped-def]
    c, _, sid = session
    assert c.get("/api/jobs/does-not-exist").json()["error"] == "job_not_found"
    assert c.get(f"/api/sessions/{sid}/chapters/99").json()["error"] == "chapter_not_found"


# --- auto-translate next chapters ------------------------------------------------------------

from app.services.translation import next_chapter_to_translate  # noqa: E402


def test_next_chapter_to_translate_skips_front_matter_and_done() -> None:
    state = {"chapters": [
        {"id": "1", "title": "Front matter", "status": "pending"},
        {"id": "2", "title": "A", "status": "review"},
        {"id": "3", "title": "B", "status": "pending"},
        {"id": "4", "title": "C", "status": "failed"},
        {"id": "5", "title": "D", "status": "pending"},
    ]}
    assert next_chapter_to_translate(state, "2") == "3"
    assert next_chapter_to_translate(state, "3") == "5"
    assert next_chapter_to_translate(state, "5") == "3"  # wraps around, skips front matter + failed
    assert next_chapter_to_translate(state, None) == "3"


@pytest.fixture
def book_session(client):  # type: ignore[no-untyped-def]
    c, root = client
    pages = [[(BODY, 11)]] * 8
    pdf = make_pdf(pages, toc=[[1, "One", 2], [1, "Two", 4], [1, "Three", 6]])
    r = c.post("/api/sessions", files={"file": ("book.pdf", pdf, "application/pdf")})
    sid = r.json()["session_id"]
    assert [ch["title"] for ch in r.json()["chapters"]] == ["Front matter", "One", "Two", "Three"]
    return c, sid


def test_auto_translate_chains_through_remaining_chapters(book_session) -> None:  # type: ignore[no-untyped-def]
    c, sid = book_session
    r = c.post(f"/api/sessions/{sid}/auto-translate", json={"enabled": True, "after_chapter_id": "1"})
    assert r.status_code == 200 and r.json()["auto_translate"] is True
    # TestClient runs the background chain to completion
    statuses = {ch["title"]: ch["status"] for ch in c.get(f"/api/sessions/{sid}").json()["chapters"]}
    assert statuses == {"Front matter": "pending", "One": "review", "Two": "review", "Three": "review"}


def test_manual_translate_continues_when_auto_is_on(book_session) -> None:  # type: ignore[no-untyped-def]
    c, sid = book_session
    from app.main import app as _app
    from app.services.jobs import get_jobs

    jobs = _app.dependency_overrides[get_jobs]()
    # Turn on while a job is "running": the flag is saved but nothing new starts yet.
    blocker = jobs.start(sid, "9", "translate")
    assert c.post(f"/api/sessions/{sid}/auto-translate", json={"enabled": True}).json()["auto_translate"] is True
    jobs.update(blocker.id, status="done")
    assert c.post(f"/api/sessions/{sid}/chapters/3/translate").status_code == 202
    statuses = [ch["status"] for ch in c.get(f"/api/sessions/{sid}").json()["chapters"]]
    assert statuses == ["pending", "review", "review", "review"]  # 3 then 4 then wraps to 2


def test_auto_translate_off_translates_only_the_chosen_chapter(book_session) -> None:  # type: ignore[no-untyped-def]
    c, sid = book_session
    assert c.post(f"/api/sessions/{sid}/chapters/2/translate").status_code == 202
    statuses = [ch["status"] for ch in c.get(f"/api/sessions/{sid}").json()["chapters"]]
    assert statuses == ["pending", "review", "pending", "pending"]
    assert c.get(f"/api/sessions/{sid}").json()["auto_translate"] is False
