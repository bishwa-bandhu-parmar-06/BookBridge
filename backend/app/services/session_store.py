"""Per-session folder + state.json storage (no database).

Layout of ./tmp_sessions/{session_id}/:
  original.pdf     the uploaded book
  state.json       session state (written atomically, guarded by a per-session lock)
  extracted.json   cleaned paragraphs + image list for the whole book
  images/          extracted images

Privacy: session folders are only reachable by their random UUID, which is validated
strictly (no path traversal), and nothing ever lists the sessions directory to a client.
Expired sessions are treated as non-existent even before the cleanup loop deletes them.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app import errors

log = logging.getLogger(__name__)

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(session_id: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(session_id, threading.RLock())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_session_id(value: str) -> bool:
    return bool(_UUID_RE.match(value))


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # -- paths ---------------------------------------------------------------------------

    def session_dir(self, session_id: str) -> Path:
        # Strict UUID check prevents path traversal and guessing of non-session folders.
        if not is_session_id(session_id):
            raise errors.session_not_found()
        return self.root / session_id

    def existing_dir(self, session_id: str) -> Path:
        d = self.session_dir(session_id)
        if not (d / "state.json").is_file():
            raise errors.session_not_found()
        return d

    # -- lifecycle -----------------------------------------------------------------------

    def create(self) -> tuple[str, Path]:
        session_id = str(uuid.uuid4())
        d = self.root / session_id
        d.mkdir(parents=True, exist_ok=False)
        return session_id, d

    def delete(self, session_id: str) -> bool:
        """Delete a session folder. Returns True if something was deleted."""
        d = self.session_dir(session_id)
        with self.lock(session_id):
            existed = d.exists()
            shutil.rmtree(d, ignore_errors=True)
        with _locks_guard:
            _locks.pop(session_id, None)
        if existed:
            log.info("session deleted sid=%s", session_id)
        return existed

    @contextmanager
    def lock(self, session_id: str) -> Iterator[None]:
        with _lock_for(session_id):
            yield

    # -- JSON files ----------------------------------------------------------------------

    @staticmethod
    def write_json_atomic(path: Path, data: Any) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @staticmethod
    def is_expired(state: dict[str, Any], now: datetime | None = None) -> bool:
        exp = state.get("expires_at")
        if not exp:
            return False
        return (now or utcnow()) >= datetime.fromisoformat(exp)

    def load_state(self, session_id: str) -> dict[str, Any]:
        d = self.existing_dir(session_id)
        with self.lock(session_id):
            try:
                state = json.loads((d / "state.json").read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise errors.session_not_found() from None
        if self.is_expired(state):
            self.delete(session_id)
            raise errors.session_not_found()
        return state

    def save_state(self, session_id: str, state: dict[str, Any]) -> None:
        d = self.session_dir(session_id)
        with self.lock(session_id):
            if not d.is_dir():
                raise errors.session_not_found()
            self.write_json_atomic(d / "state.json", state)

    @contextmanager
    def edit_state(self, session_id: str) -> Iterator[dict[str, Any]]:
        """Load state, let the caller mutate it, then save atomically — all under the lock.

        If the block raises, nothing is saved.
        """
        with self.lock(session_id):
            state = self.load_state(session_id)
            yield state
            self.save_state(session_id, state)

    def load_extracted(self, session_id: str) -> dict[str, Any]:
        d = self.existing_dir(session_id)
        return json.loads((d / "extracted.json").read_text(encoding="utf-8"))

    # -- cleanup -------------------------------------------------------------------------

    def cleanup_expired(self, ttl_minutes: int, now: datetime | None = None) -> int:
        """Delete expired session folders. Returns how many were deleted.

        Expiry comes from state.json's expires_at; folders without a readable state
        (e.g. an upload that crashed mid-way) expire `ttl_minutes` after their mtime.
        """
        now = now or utcnow()
        deleted = 0
        for d in self.root.iterdir():
            if not d.is_dir() or not is_session_id(d.name):
                continue
            try:
                state = json.loads((d / "state.json").read_text(encoding="utf-8"))
                expired = self.is_expired(state, now)
            except (OSError, ValueError):
                mtime = datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc)
                expired = now - mtime >= timedelta(minutes=ttl_minutes)
            if expired and self.delete(d.name):
                deleted += 1
        if deleted:
            log.info("cleanup removed %d expired session(s)", deleted)
        return deleted
