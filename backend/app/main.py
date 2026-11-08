"""FastAPI entry point.  Run:  uvicorn app.main:app --reload  (from the backend/ folder)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app import errors
from app.config import get_settings
from app.deps import get_store
from app.errors import AppError, app_error_handler
from app.routers import chapters, export, glossary, jobs, sessions
from app.schemas import PublicConfig
from app.services.rate_limit import RateLimiter, client_ip, rate_limited

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bookbridge")

settings = get_settings()


async def cleanup_loop(interval_seconds: float, ttl_minutes: int) -> None:
    """Delete expired session folders now and then every `interval_seconds`."""
    store = get_store()
    while True:
        try:
            await asyncio.to_thread(store.cleanup_expired, ttl_minutes)
        except Exception:  # noqa: BLE001 - never let the loop die
            log.exception("session cleanup failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(
        cleanup_loop(settings.cleanup_interval_minutes * 60, settings.session_ttl_minutes)
    )
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="BookBridge API", version="1.0.0", lifespan=lifespan)
app.state.upload_limiter = RateLimiter(settings.upload_rate_limit_per_hour, 3600)

_MULTIPART_OVERHEAD = 1024 * 1024


async def upload_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Reject over-limit or oversized uploads BEFORE the body is read.

    FastAPI parses the multipart body before any dependency runs, so this must be middleware.
    """
    if request.method == "POST" and request.url.path.rstrip("/") == "/api/sessions":
        s = get_settings()
        ip = client_ip(request, s.trust_proxy_headers)
        retry_after = request.app.state.upload_limiter.hit(ip)
        if retry_after is not None:
            log.info("upload rate limited")
            return await app_error_handler(request, rate_limited(retry_after))
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > s.max_upload_bytes + _MULTIPART_OVERHEAD:
            return await app_error_handler(request, errors.too_large(s.max_upload_mb))
    return await call_next(request)


# Added before CORS so CORS stays the outermost layer and its headers reach these early errors.
app.add_middleware(BaseHTTPMiddleware, dispatch=upload_guard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],  # lets the frontend read download file names
)

app.add_exception_handler(AppError, app_error_handler)


@app.exception_handler(RequestValidationError)
async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "invalid_request",
            "message": "Some required information is missing or invalid.",
            "message_hi": "कुछ आवश्यक जानकारी नहीं है या गलत है।",
            "details": exc.errors(),
        },
    )


@app.exception_handler(StarletteHTTPException)
async def _http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        content = {"error": "not_found", "message": "Not found.", "message_hi": "नहीं मिला।"}
    elif exc.status_code == 405:
        content = {"error": "method_not_allowed", "message": "This action is not allowed here.", "message_hi": "यह क्रिया यहाँ मान्य नहीं है।"}
    else:
        content = {"error": "http_error", "message": str(exc.detail), "message_hi": ""}
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error: %s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "Something went wrong on our side. Please try again.",
            "message_hi": "हमारी ओर से कुछ गड़बड़ हुई। कृपया फिर से प्रयास करें।",
        },
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config", response_model=PublicConfig)
async def public_config() -> PublicConfig:
    """Limits the frontend shows to users (no secrets)."""
    s = get_settings()
    return PublicConfig(max_upload_mb=s.max_upload_mb, max_pages=s.max_pages, session_ttl_minutes=s.session_ttl_minutes)


app.include_router(sessions.router)
app.include_router(chapters.router)
app.include_router(glossary.router)
app.include_router(jobs.router)
app.include_router(export.router)
