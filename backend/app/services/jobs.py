"""In-memory job registry (no Redis for the MVP). Jobs are lost on restart; chapters left
in 'translating' without a live job are reconciled to 'failed' by the API."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app import errors

JobStatus = Literal["queued", "running", "done", "failed"]
JobKind = Literal["translate", "retranslate"]

FINISHED_JOB_TTL_SECONDS = 3600


@dataclass
class Job:
    id: str
    session_id: str
    chapter_id: str
    kind: JobKind
    status: JobStatus = "queued"
    progress: int = 0
    message: str = "Waiting to start"
    #: temporary warning (e.g. "AI service busy"); cleared when the next part succeeds
    notice: str | None = None
    error: str | None = None
    error_hi: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["job_id"] = d.pop("id")
        end = self.finished_at or time.time()
        d["elapsed_seconds"] = int(end - self.created_at)
        return d


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, session_id: str, chapter_id: str, kind: JobKind) -> Job:
        """Create a job. Only one active job per session (raises job_running)."""
        with self._lock:
            self._prune()
            if any(j.session_id == session_id and j.active for j in self._jobs.values()):
                raise errors.job_running()
            job = Job(id=str(uuid.uuid4()), session_id=session_id, chapter_id=chapter_id, kind=kind)
            self._jobs[job.id] = job
            return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise errors.job_not_found()
        return job

    def active_for_session(self, session_id: str) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs.values() if j.session_id == session_id and j.active), None)

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for k, v in fields.items():
                setattr(job, k, v)
            if job.status in ("done", "failed") and job.finished_at is None:
                job.finished_at = time.time()

    def forget_session(self, session_id: str) -> None:
        with self._lock:
            for jid in [j.id for j in self._jobs.values() if j.session_id == session_id and not j.active]:
                del self._jobs[jid]

    def _prune(self) -> None:
        cutoff = time.time() - FINISHED_JOB_TTL_SECONDS
        for jid in [j.id for j in self._jobs.values() if j.finished_at and j.finished_at < cutoff]:
            del self._jobs[jid]


registry = JobRegistry()


def get_jobs() -> JobRegistry:
    return registry
