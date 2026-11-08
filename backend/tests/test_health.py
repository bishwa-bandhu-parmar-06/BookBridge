

def test_client_ip_uses_the_proxy_added_entry() -> None:
    from starlette.requests import Request

    from app.services.rate_limit import client_ip

    def req(xff: str | None) -> Request:
        headers = [(b"x-forwarded-for", xff.encode())] if xff else []
        return Request({"type": "http", "headers": headers, "client": ("10.0.0.1", 1)})

    assert client_ip(req("6.6.6.6, 1.2.3.4"), True) == "1.2.3.4"  # leftmost can be faked
    assert client_ip(req("6.6.6.6, 1.2.3.4, 10.1.1.1"), True, 2) == "1.2.3.4"
    assert client_ip(req("1.2.3.4"), True, 3) == "1.2.3.4"
    assert client_ip(req("6.6.6.6"), False) == "10.0.0.1"
    assert client_ip(req(None), True) == "10.0.0.1"


def test_several_frontend_origins() -> None:
    from app.config import Settings

    s = Settings(frontend_origin="https://a.vercel.app/, http://localhost:3000", _env_file=None)  # type: ignore[call-arg]
    assert s.frontend_origins == ["https://a.vercel.app", "http://localhost:3000"]
