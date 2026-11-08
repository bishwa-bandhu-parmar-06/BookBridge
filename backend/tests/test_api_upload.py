import json
from pathlib import Path



def test_upload_creates_session(client, english_book: bytes) -> None:  # type: ignore[no-untyped-def]
    c, root = client
    r = c.post("/api/sessions", files={"file": ("science.pdf", english_book, "application/pdf")}, data={"source_lang": "auto"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_lang"] == "en" and body["target_lang"] == "hi"
    assert len(body["chapters"]) == 3
    sdir = root / body["session_id"]
    assert (sdir / "original.pdf").is_file()
    state = json.loads((sdir / "state.json").read_text(encoding="utf-8"))
    assert state["book_title"] == "science"
    assert all(ch["status"] == "pending" for ch in state["chapters"])
    extracted = json.loads((sdir / "extracted.json").read_text(encoding="utf-8"))
    assert extracted["paragraphs"]


def test_upload_respects_user_direction(client, english_book: bytes) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    r = c.post("/api/sessions", files={"file": ("b.pdf", english_book)}, data={"source_lang": "hi"})
    body = r.json()
    assert body["source_lang"] == "hi" and body["target_lang"] == "en" and body["detected_lang"] == "en"
    assert body["warnings"]


def test_upload_rejects_non_pdf_with_friendly_message(client) -> None:  # type: ignore[no-untyped-def]
    c, root = client
    r = c.post("/api/sessions", files={"file": ("notes.pdf", b"hello world, not a pdf", "application/pdf")})
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "not_pdf" and body["message"] and body["message_hi"]
    assert not any(root.iterdir()), "no session folder should be left behind"
