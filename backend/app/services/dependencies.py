"""FastAPI dependency wiring — single source of truth for swapping
implementations of CourtClient + SessionStore + InMemoryCaseCache in tests.

Why module-level singletons: SessionStore, CourtClient, and the cache all
own state (cookie jars, TTL'd dicts, hit/miss counters). Re-instantiating
per request would break the contract.

GREEN-ZONE (2026-05-17): `get_case_cache()` provides the process-local
InMemoryCaseCache that replaced the deleted `parsed_case`/`case_party`/
`case_order` tables. Backend honours `settings.cache_backend`; only
`"memory"` is implemented in v1. `"redis"` is reserved for v2.
"""
from __future__ import annotations

from functools import lru_cache

from app.cache.in_memory_case_cache import InMemoryCaseCache
from app.clients.court_client import CourtClient
from app.clients.delhi_hc_client import DelhiHCClient
from app.clients.fake_court_client import FakeCourtClient
from app.config import Settings, get_settings
from app.parsers.case_parser import DHCParserV1
from app.sessions.store import InMemorySessionStore, SessionStore
from app.utils.logging import get_logger

log = get_logger(__name__)


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
    """Process-wide CourtClient. Dispatches on `Settings.client_mode`.

    `fake` → FakeCourtClient (default; GREEN-ZONE safe).
    `real` → DelhiHCClient. Currently stubbed; we log a loud WARNING on
             selection so misconfigured envs are visible at startup. The
             stub itself raises NotImplementedError on any actual call —
             we deliberately do NOT silently fall back to the fake.
    """
    settings: Settings = get_settings()
    if settings.client_mode == "fake":
        return FakeCourtClient()
    if settings.client_mode == "real":
        client = DelhiHCClient()
        if getattr(client, "is_stub", False):
            log.warning(
                "client_mode.real_but_stubbed",
                detail=(
                    "CLIENT_MODE=real but DelhiHCClient is stubbed — "
                    "see docs/SPIKE-REPORT.md before continuing. Any "
                    "outbound call will raise NotImplementedError."
                ),
            )
        return client
    raise RuntimeError(
        f"unsupported client_mode={settings.client_mode!r} — "
        "must be 'fake' or 'real'"
    )


@lru_cache(maxsize=1)
def get_case_parser() -> DHCParserV1:
    """Process-wide parser. Stateless — safe to share."""
    return DHCParserV1()


@lru_cache(maxsize=1)
def get_case_cache() -> InMemoryCaseCache:
    """Process-wide parsed-case cache. In-memory ONLY in v1.

    Per the GREEN-ZONE directive (no long-term DB storage of court data),
    the cache is intentionally process-local and ephemeral. A hard
    restart wipes it; the next /search for any case is a cache miss.
    That's the design, not a defect.
    """
    settings: Settings = get_settings()
    if settings.cache_backend == "memory":
        return InMemoryCaseCache(
            ttl_seconds=settings.parsed_case_cache_ttl_seconds
        )
    raise RuntimeError(
        f"unsupported cache_backend={settings.cache_backend!r} — Redis is v2"
    )
