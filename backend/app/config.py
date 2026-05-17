"""Centralised settings, loaded from environment via pydantic-settings.

All env vars are defined in `.env.example` at the project root. The backend
reads from `.env` (development) or actual env vars (staging/production).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. One source of truth — never read os.environ directly."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # don't crash on unrelated env vars
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    app_name: str = "delhi-hc-case-tracker"
    app_log_level: str = "INFO"
    app_timezone: str = "Asia/Kolkata"

    # ── Backend HTTP ─────────────────────────────────────────────────────
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_cors_origins: str = "http://localhost:3000"

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./backend/data/dhc.db"
    database_echo: bool = False

    # ── Session store ────────────────────────────────────────────────────
    session_backend: Literal["memory", "redis"] = "memory"
    session_ttl_seconds: int = 600
    session_captcha_ttl_seconds: int = 180
    redis_url: str = "redis://localhost:6379/0"

    # ── Court client selection ───────────────────────────────────────────
    # `fake`  → FakeCourtClient (fixture-driven; default, GREEN-ZONE safe)
    # `real`  → DelhiHCClient (stubbed — pending Arnav's Phase-0 spike;
    #            see docs/SPIKE-REPORT.md). Setting `real` while the client
    #            is still stubbed logs a startup WARNING; any actual call
    #            raises NotImplementedError.
    client_mode: Literal["fake", "real"] = "fake"

    # ── Outbound: Delhi High Court ───────────────────────────────────────
    dhc_base_url: str = "https://delhihighcourt.nic.in"
    dhc_user_agent: str = "DelhiHCCaseTracker/0.1"
    dhc_outbound_timeout_seconds: float = 20.0
    dhc_outbound_max_concurrent: int = 4
    dhc_outbound_rate_limit_per_sec: float = 0.33
    dhc_respect_robots_txt: bool = True
    dhc_hostname_allowlist: str = "delhihighcourt.nic.in"
    # When True (default in dev), every successful real-client submit
    # response body is redacted + written to
    # ``parsers/fixtures/real_responses/<case-id>_<unix>.html`` so the
    # parser can be tuned against real HTML next sprint. Set False in
    # production — capture is for development/QA only.
    # See ``backend/app/clients/response_capture.py`` for the redaction
    # rules + Sneha's privacy guard rails.
    dhc_capture_real_responses: bool = True

    # ── Caching ──────────────────────────────────────────────────────────
    parsed_case_cache_ttl_seconds: int = 86_400
    cache_backend: Literal["memory", "redis"] = "memory"

    # ── Admin ────────────────────────────────────────────────────────────
    admin_shared_secret: str = Field(default="change-me-before-deploy")

    # ── Observability ────────────────────────────────────────────────────
    log_file_backend: str = "logs/backend/app.log"
    log_file_outbound: str = "logs/backend/outbound.log"
    sentry_dsn: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]

    @property
    def hostname_allowlist(self) -> list[str]:
        return [h.strip() for h in self.dhc_hostname_allowlist.split(",") if h.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — used everywhere via FastAPI dependency."""
    return Settings()  # type: ignore[call-arg]
