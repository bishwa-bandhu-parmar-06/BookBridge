"""Simple in-memory sliding-window rate limiter (per client IP). Resets on restart.

Good enough for a single-process MVP; a multi-instance deployment would need a shared
store (e.g. Redis) instead.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import Request

from app import errors


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> float | None:
        """Record one request. Returns None if allowed, else seconds until the next slot frees up."""
        if self.limit <= 0:
            return None
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return max(1.0, q[0] + self.window - now)
            q.append(now)
            if len(self._hits) > 10_000:  # keep memory bounded
                self._prune(now)
            return None

    def _prune(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - self.window]:
            del self._hits[k]


def client_ip(request: Request, trust_proxy: bool, hops: int = 1) -> str:
    """Client IP. Only trusts X-Forwarded-For when explicitly enabled (behind your own proxy).

    Each proxy appends the address it saw, so the entry `hops` from the right is the one our
    own proxy added; anything further left was sent by the client and could be faked."""
    if trust_proxy:
        fwd = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if fwd:
            return fwd[-min(max(hops, 1), len(fwd))]
    return request.client.host if request.client else "unknown"


def rate_limited(retry_after: float) -> errors.AppError:
    minutes = max(1, round(retry_after / 60))
    e = errors.AppError(
        429, "rate_limited",
        f"Too many uploads from your network. Please try again in about {minutes} minute(s).",
        f"आपके नेटवर्क से बहुत अधिक अपलोड हुए हैं। कृपया लगभग {minutes} मिनट बाद फिर कोशिश करें।",
    )
    e.headers = {"Retry-After": str(int(retry_after))}
    return e
