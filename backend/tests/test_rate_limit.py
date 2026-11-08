from app.main import app
from app.services.rate_limit import RateLimiter
from tests.conftest import BODY, make_pdf


def test_sliding_window() -> None:
    rl = RateLimiter(limit=3, window_seconds=3600)
    assert [rl.hit("a", now=t) for t in (0, 10, 20)] == [None, None, None]
    assert rl.hit("a", now=30) == 3570  # oldest hit (t=0) frees up at t=3600
    assert rl.hit("b", now=30) is None, "other IPs are independent"
    assert rl.hit("a", now=3600) is None, "slot freed after the window"


def test_disabled_when_zero() -> None:
    rl = RateLimiter(limit=0, window_seconds=3600)
    assert all(rl.hit("a") is None for _ in range(100))


def test_upload_rate_limit_and_cors(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    original = app.state.upload_limiter
    app.state.upload_limiter = RateLimiter(limit=2, window_seconds=3600)
    try:
        pdf = make_pdf([[(BODY, 11)]])
        headers = {"Origin": "http://localhost:3000"}
        assert c.post("/api/sessions", files={"file": ("a.pdf", pdf)}, headers=headers).status_code == 200
        assert c.post("/api/sessions", files={"file": ("a.pdf", b"not a pdf")}, headers=headers).status_code == 400
        r = c.post("/api/sessions", files={"file": ("a.pdf", pdf)}, headers=headers)
        assert r.status_code == 429
        body = r.json()
        assert body["error"] == "rate_limited" and body["message"] and body["message_hi"]
        assert int(r.headers["retry-after"]) > 3000
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000", "CORS must wrap early errors"
        # other endpoints are not limited
        assert c.get("/api/health").status_code == 200
    finally:
        app.state.upload_limiter = original


def test_oversized_upload_rejected_before_reading(client) -> None:  # type: ignore[no-untyped-def]
    c, _ = client
    big = b"%PDF-" + b"0" * (52 * 1024 * 1024)
    r = c.post("/api/sessions", files={"file": ("big.pdf", big)})
    assert r.status_code == 413 and r.json()["error"] == "file_too_large"
