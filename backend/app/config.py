"""Application settings, loaded from environment / .env. Never hardcode keys or model names."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    translator: Literal["gemini", "mock"] = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = ""
    # Comma-separated models to try when GEMINI_MODEL is overloaded or rate-limited.
    gemini_fallback_models: str = ""
    # "Thinking" makes newer models slow and is not needed for translation: minimal | low | medium | high | default
    gemini_thinking_level: str = "minimal"
    # Give up on a model after this many seconds and try the next one. A healthy model answers a
    # batch in ~5-10 s; an overloaded one can hang ~90 s before Google returns 504.
    gemini_timeout_seconds: float = 25.0
    mock_delay_seconds: float = 0.0

    # Translation batching / retries
    translation_batch_chars: int = 4000
    translation_max_attempts: int = 3
    # Batches translated at the same time (keep low on free API tiers).
    translation_concurrency: int = 3

    session_ttl_minutes: int = 120
    cleanup_interval_minutes: int = 10
    max_upload_mb: int = 50
    max_pages: int = 500
    default_pages_per_chunk: int = 10
    sessions_dir: Path = Path("./tmp_sessions")

    # Where the website runs (CORS). Comma-separated for several, e.g.
    # "https://bookbridge.vercel.app,http://localhost:3000".
    frontend_origin: str = "http://localhost:3000"
    # Optional regex for extra origins, e.g. Vercel preview links:
    # "https://bookbridge-[a-z0-9-]+\.vercel\.app"
    frontend_origin_regex: str = ""

    # Per-IP upload rate limit (in-memory). 0 disables it.
    upload_rate_limit_per_hour: int = 10
    # Use X-Forwarded-For for the client IP. Enable ONLY behind your own reverse proxy.
    trust_proxy_headers: bool = False
    # How many proxies in front of the app add to X-Forwarded-For (hosting platforms: usually 1).
    trusted_proxy_hops: int = 1

    # Text-layer threshold: average non-whitespace characters per page below this => "scanned".
    min_chars_per_page: int = 50

    @property
    def frontend_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
