"""Shared pytest fixtures for the Delhi HC Case Tracker test suite.

Design notes (Maya, QA lead):
  * Tests are independent — every test gets a fresh `InMemorySessionStore`
    and a fresh FastAPI app instance. No shared mutable globals.
  * The HTTP layer is exercised through `httpx.AsyncClient` with an ASGI
    transport — no socket open, no Uvicorn boot. Fast and deterministic.
  * Time is NOT real. Anywhere we'd `time.sleep`, we monkey-patch
    `time.time()` via the `frozen_clock` fixture instead — keeps async
    tests under 2 seconds total.
  * `fixture_html` loads sample HTML straight from
    `parsers/fixtures/sample_responses/` — same dir the production code
    expects. If those files move, tests fail loudly, which is correct.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Callable

import pytest

# Make `import app...` work without needing PYTHONPATH gymnastics. The CI
# command `pytest backend/tests -q` runs from the project root; tests still
# need the `backend` dir on sys.path so `from app.X import Y` resolves.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _PROJECT_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

FIXTURES_DIR = _PROJECT_ROOT / "parsers" / "fixtures" / "sample_responses"


# ── pytest-asyncio ─────────────────────────────────────────────────────────
# Use auto mode so we don't have to decorate every async test individually.
def pytest_collection_modifyitems(config, items):  # noqa: D401 - pytest hook
    """Auto-apply ``pytest.mark.asyncio`` to any ``async def`` test function."""
    asyncio_mark = pytest.mark.asyncio
    for item in items:
        if isinstance(item, pytest.Function) and asyncio.iscoroutinefunction(item.function):
            item.add_marker(asyncio_mark)


# ── Settings: force test-friendly env vars BEFORE app import ───────────────
@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Hermetic env. Every test starts from the same config baseline.

    Why a tempfile DB (not `:memory:`): the app boots Alembic on startup
    via a synchronous engine, and the async runtime pool opens its own
    connections. Two independent `:memory:` databases never share
    schema, so tables created by Alembic are invisible to the async
    pool. A per-test tempfile sidesteps that without changing prod code.
    """
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
    )
    monkeypatch.setenv("SESSION_BACKEND", "memory")
    monkeypatch.setenv("SESSION_TTL_SECONDS", "600")
    monkeypatch.setenv("ADMIN_SHARED_SECRET", "test-admin-secret")
    monkeypatch.setenv("OUTBOUND_FETCH_ENABLED", "true")
    monkeypatch.setenv("CLIENT_MODE", "fake")
    # Wipe the lru_cache so each test gets a fresh Settings() object.
    from app.config import get_settings  # local import — env must be set first
    get_settings.cache_clear()
    # Reset the module-level engine + DI singletons so each test gets a
    # fresh binding to the new tempfile URL. Synchronously clear; the
    # async engine is rebuilt lazily on first use.
    try:
        from app.db import session as _db_session
        _db_session._engine = None  # type: ignore[attr-defined]
        _db_session._sessionmaker = None  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        from app.services.dependencies import (
            get_case_parser, get_court_client, get_session_store,
        )
        get_session_store.cache_clear()
        get_court_client.cache_clear()
        get_case_parser.cache_clear()
    except Exception:
        pass
    # Reset the runtime kill-switch — kill-switch tests mutate it as a
    # side effect of admin endpoint exercise.
    try:
        from app.runtime_flags import get_flags
        get_flags().outbound_fetch_enabled = True
    except Exception:
        pass


# ── Session store ──────────────────────────────────────────────────────────
@pytest.fixture
def session_store():
    """Fresh InMemorySessionStore per test. No cross-test bleed."""
    from app.sessions.store import InMemorySessionStore
    return InMemorySessionStore(ttl_seconds=600)


@pytest.fixture
def short_ttl_session_store():
    """1-second TTL store for expiry tests. Use with `frozen_clock`."""
    from app.sessions.store import InMemorySessionStore
    return InMemorySessionStore(ttl_seconds=1)


# ── Fixture loader ─────────────────────────────────────────────────────────
@pytest.fixture
def fixture_html() -> Callable[[str], str]:
    """Returns a function: name -> raw HTML string. Raises if not found."""
    def _load(name: str) -> str:
        path = FIXTURES_DIR / name
        if not path.exists():
            raise FileNotFoundError(
                f"Test fixture missing: {path}. "
                f"Expected one of {sorted(p.name for p in FIXTURES_DIR.glob('*.html'))}."
            )
        return path.read_text(encoding="utf-8")
    return _load


# ── Frozen clock — for TTL / expiry tests without real sleep ───────────────
@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch):
    """Replace `time.time` in the sessions module with a controllable clock.

    Usage:
        def test_expiry(frozen_clock):
            frozen_clock.set(1000.0)
            ... do thing ...
            frozen_clock.advance(120)  # +2 minutes
    """
    import time as _time
    from app.sessions import store as _store_mod

    class _Clock:
        def __init__(self) -> None:
            self.now: float = 1_700_000_000.0  # arbitrary fixed epoch

        def set(self, value: float) -> None:
            self.now = float(value)

        def advance(self, seconds: float) -> None:
            self.now += float(seconds)

        def __call__(self) -> float:
            return self.now

    clock = _Clock()
    monkeypatch.setattr(_store_mod.time, "time", clock)
    return clock


# ── FastAPI app + async test client ────────────────────────────────────────
@pytest.fixture
def app_instance():
    """Build a fresh FastAPI app per test.

    NOTE: ``app.main.create_app`` reads settings at construction time, so the
    ``_test_env`` autouse fixture must have run already (it has — pytest
    resolves autouse fixtures first).
    """
    from app.main import create_app
    return create_app()


@pytest.fixture
async def async_client(app_instance):
    """ASGI in-process client. No socket; no Uvicorn. Fast and deterministic.

    We invoke the app's lifespan manually because httpx.ASGITransport
    does not drive lifespan events. Without this the startup
    `alembic upgrade head` never runs and tables don't exist.
    """
    import httpx
    from app.main import _run_alembic_upgrade

    # Run migrations against the test tempfile DB before any request fires.
    _run_alembic_upgrade()

    transport = httpx.ASGITransport(app=app_instance)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── Admin auth helper ──────────────────────────────────────────────────────
@pytest.fixture
def admin_headers() -> dict[str, str]:
    """Headers that pass the admin secret check in tests."""
    return {"X-Admin-Secret": "test-admin-secret"}


# ── Convenience: valid /search/init body ───────────────────────────────────
@pytest.fixture
def valid_init_body() -> dict:
    """A well-formed init request used across the integration suite."""
    return {"case_type": "W.P.(C)", "case_number": "12345", "year": 2024}
