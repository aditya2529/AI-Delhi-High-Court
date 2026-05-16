"""FastAPI dependency wiring — single source of truth for swapping
implementations of CourtClient + SessionStore in tests.

Why module-level singletons: both objects own state (cookie jars,
TTL'd dicts). Re-instantiating per request would break the contract.
"""
from __future__ import annotations

from functools import lru_cache

from app.clients.court_client import CourtClient
from app.clients.fake_court_client import FakeCourtClient
from app.config import Settings, get_settings
from app.parsers.case_parser import DHCParserV1
from app.sessions.store import InMemorySessionStore, SessionStore


@lru_cache(maxsize=1)
def get_session_store() -> SessionStore:
    """Process-wide session store. Backed by `SESSION_BACKEND` config."""
    settings: Settings = get_settings()
    if settings.session_backend == "memory":
        return InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)
    raise RuntimeError(
        f"unsupported session_backend={settings.session_backend!r} — Redis is v2"
    )


@lru_cache(maxsize=1)
def get_court_client() -> CourtClient:
    """Process-wide CourtClient. Always FakeCourtClient until Phase-0 ships."""
    return FakeCourtClient()


@lru_cache(maxsize=1)
def get_case_parser() -> DHCParserV1:
    """Process-wide parser. Stateless — safe to share."""
    return DHCParserV1()
