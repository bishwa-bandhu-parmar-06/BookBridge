import json
import os
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from app.errors import AppError
from app.services.session_store import SessionStore, utcnow


def _state(sid: str, expires_in_min: float = 60) -> dict:
    now = utcnow()
    return {
        "session_id": sid,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=expires_in_min)).isoformat(),
        "counter": 0,
    }


def test_create_save_load(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid, d = store.create()
    assert d.is_dir() and d.parent == tmp_path.resolve()
    store.save_state(sid, _state(sid))
    assert store.load_state(sid)["session_id"] == sid
    assert not list(d.glob(".tmp_*")), "temp files must be renamed away"


@pytest.mark.parametrize("bad", ["../etc", "..", "abc", "00000000-0000-0000-0000-000000000000", "X" * 36, "a/b"])
def test_rejects_non_uuid_ids(tmp_path: Path, bad: str) -> None:
    store = SessionStore(tmp_path)
    with pytest.raises(AppError) as ei:
        store.load_state(bad)
    assert ei.value.code == "session_not_found"


def test_unknown_session(tmp_path: Path) -> None:
    import uuid

    with pytest.raises(AppError):
        SessionStore(tmp_path).load_state(str(uuid.uuid4()))


def test_expired_session_is_gone_on_access(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid, d = store.create()
    store.save_state(sid, _state(sid, expires_in_min=-1))
    with pytest.raises(AppError):
        store.load_state(sid)
    assert not d.exists()


def test_edit_state_saves_and_rolls_back(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid, _ = store.create()
    store.save_state(sid, _state(sid))
    with store.edit_state(sid) as st:
        st["counter"] = 5
    assert store.load_state(sid)["counter"] == 5
    with pytest.raises(RuntimeError):
        with store.edit_state(sid) as st:
            st["counter"] = 99
            raise RuntimeError("boom")
    assert store.load_state(sid)["counter"] == 5


def test_edit_state_is_serialised(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid, _ = store.create()
    store.save_state(sid, _state(sid))

    def bump() -> None:
        for _ in range(20):
            with store.edit_state(sid) as st:
                v = st["counter"]
                time.sleep(0.0005)
                st["counter"] = v + 1

    threads = [threading.Thread(target=bump) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.load_state(sid)["counter"] == 100


def test_cleanup_expired(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    fresh, _ = store.create()
    store.save_state(fresh, _state(fresh, 60))
    old, _ = store.create()
    store.save_state(old, _state(old, -5))
    # a crashed upload: folder without state.json, older than the TTL
    broken, broken_dir = store.create()
    past = time.time() - 3 * 3600
    os.utime(broken_dir, (past, past))
    # a recent folder without state (upload in progress) must survive
    in_progress, _ = store.create()
    # something that is not a session folder is never touched
    (tmp_path / "keep-me").mkdir()

    assert store.cleanup_expired(ttl_minutes=120) == 2
    remaining = {p.name for p in tmp_path.iterdir()}
    assert remaining == {fresh, in_progress, "keep-me"}


def test_delete(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid, d = store.create()
    store.save_state(sid, _state(sid))
    assert store.delete(sid) is True
    assert not d.exists()
    assert store.delete(sid) is False


def test_state_is_utf8_json(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid, d = store.create()
    st = _state(sid)
    st["title"] = "अध्याय १"
    store.save_state(sid, st)
    assert "अध्याय १" in (d / "state.json").read_text(encoding="utf-8")
    assert json.loads((d / "state.json").read_text(encoding="utf-8"))["title"] == "अध्याय १"
