from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

import pymupdf as fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BODY = (
    "The force acting on a body is equal to the rate of change of its momentum. "
    "This law helps us to understand how objects move when different forces act on them. "
    "In this chapter we will study the motion of objects and the forces that cause it."
)

# Fonts that can draw Devanagari, for building Hindi test PDFs (first one found is used).
_DEVA_FONT_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "app" / "fonts" / "NotoSansDevanagari-Regular.ttf",
    Path("C:/Windows/Fonts/Nirmala.ttf"),
    Path("C:/Windows/Fonts/mangal.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf"),
]


def devanagari_font() -> Path | None:
    return next((p for p in _DEVA_FONT_CANDIDATES if p.is_file()), None)


def make_pdf(
    pages: Iterable[Iterable[tuple[str, float]]],
    *,
    header: str | None = None,
    page_numbers: bool = False,
    toc: list[list] | None = None,
    fontfile: Path | None = None,
    encrypt_password: str | None = None,
) -> bytes:
    """Build a PDF. Each page is a list of (text, fontsize) blocks laid out top to bottom."""
    doc = fitz.open()
    for i, blocks in enumerate(pages):
        page = doc.new_page(width=595, height=842)
        kw = {"fontname": "deva", "fontfile": str(fontfile)} if fontfile else {"fontname": "helv"}
        if header:
            page.insert_textbox(fitz.Rect(50, 20, 545, 45), header, fontsize=9, **kw)
        if page_numbers:
            page.insert_textbox(fitz.Rect(250, 800, 345, 830), str(i + 1), fontsize=9, align=1, **kw)
        y = 90.0
        for text, size in blocks:
            h = max(size * 1.6, size * 1.4 * (1 + len(text) * size * 0.5 / 495))
            rect = fitz.Rect(50, y, 545, y + h + 40)
            rc = page.insert_textbox(rect, text, fontsize=size, **kw)
            used = (h + 40) - rc if rc >= 0 else h + 40
            y += used + size * 1.2
    if toc:
        doc.set_toc(toc)
    if encrypt_password:
        out = doc.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=encrypt_password, owner_pw=encrypt_password + "o"
        )
    else:
        out = doc.tobytes()
    doc.close()
    return out


@pytest.fixture
def english_book() -> bytes:
    pages = []
    for ch in (1, 2, 3):
        pages.append([(f"Chapter {ch}", 20), (f"Topic number {ch}", 16), (BODY, 11), (BODY, 11)])
        pages.append([(BODY, 11), (BODY, 11)])
    return make_pdf(pages, header="Science Textbook Class 9", page_numbers=True)


@pytest.fixture
def client(tmp_path: Path):  # type: ignore[no-untyped-def]
    """(TestClient, sessions_root) with an isolated sessions directory."""
    from fastapi.testclient import TestClient

    from app.config import Settings, get_settings
    from app.deps import get_store
    from app.main import app
    from app.services.jobs import JobRegistry, get_jobs
    from app.services.session_store import SessionStore

    settings = Settings(sessions_dir=tmp_path, translator="mock", _env_file=None)  # type: ignore[call-arg]
    store = SessionStore(tmp_path)
    jobs = JobRegistry()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_jobs] = lambda: jobs
    from app.services.rate_limit import RateLimiter

    original_limiter = app.state.upload_limiter
    app.state.upload_limiter = RateLimiter(limit=0, window_seconds=3600)  # off unless a test sets one
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()
    app.state.upload_limiter = original_limiter
