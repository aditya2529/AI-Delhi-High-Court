"""Session store — holds per-search server-side state for the CAPTCHA round-trip.

A session lives from `/search/init` (cookies + CSRF + CAPTCHA token fetched
from the court site) until either:
  * `/search/submit` returns a terminal status (success / not_found / court_error)
  * TTL expires (default 10 min)
  * User abandons (no cleanup needed; TTL handles it)

The cookies + CSRF token never leave the server — frontend only ever sees an
opaque `session_id`. This is the SSRF + token-leak guard.

`InMemorySessionStore` is for MVP / single-node. `RedisSessionStore` for v2.
"""
from __future__ import annotations

import abc
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


def _now() -> float:
    """Indirect call to `time.time` so tests can monkeypatch the module
    attribute and have it observed by all CourtSession instances.

    `field(default_factory=time.time)` captures the function reference at
    class-definition time — too early for monkeypatching to take effect.
    """
    return time.time()


@dataclass
class CourtSession:
    """Opaque container for everything we need to call the court site again."""

    session_id: str
    cookies: dict[str, str] = field(default_factory=dict)
    csrf_tokens: dict[str, str] = field(default_factory=dict)
    captcha_image_bytes: Optional[bytes] = None
    captcha_fetched_at: float = 0.0
    case_type: str = ""
    case_number: str = ""
    year: int = 0
    created_at: float = field(default_factory=_now)
    last_seen_at: float = field(default_factory=_now)


class SessionStore(abc.ABC):
    """Async abstract base. Implementations swap in via SESSION_BACKEND."""

    @abc.abstractmethod
    async def create(self, case_type: str, case_number: str, year: int) -> CourtSession: ...

    @abc.abstractmethod
    async def get(self, session_id: str) -> Optional[CourtSession]: ...

    @abc.abstractmethod
    async def put(self, session: CourtSession) -> None: ...

    @abc.abstractmethod
    async def delete(self, session_id: str) -> None: ...


class InMemorySessionStore(SessionStore):
    """Single-node dict store with TTL eviction on get().

    Not thread-safe across processes — for production use Redis.

    We also keep a small ring of recently-evicted session_ids (TTL evictions
    only — explicit `delete()` does NOT count, since those are clean
    consumption / restart events). This lets the route layer distinguish
    "session timed out" (return body status=expired) from "this id was
    never valid" (return 404). The ring is bounded to 1024 entries so a
    pathological attacker can't grow it unbounded.
    """

    _EVICTED_RING_MAX = 1024

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
        self._data: dict[str, CourtSession] = {}
        self._recently_evicted: dict[str, float] = {}

    async def create(self, case_type: str, case_number: str, year: int) -> CourtSession:
        # session_id is the canonical RFC 4122 dashed UUID v4 — see
        # docs/api/API-CONTRACT.md §7.3 and DEMO-FEEDBACK.md item #4
        # (DRIFT-001 follow-on). Frontend Zod previously expected this
        # shape; backend was emitting dashless hex. Canonical format
        # now matches end-to-end.
        session = CourtSession(
            session_id=str(uuid.uuid4()),
            case_type=case_type,
            case_number=case_number,
            year=year,
        )
        async with self._lock:
            self._data[session.session_id] = session
        return session

    async def get(self, session_id: str) -> Optional[CourtSession]:
        async with self._lock:
            s = self._data.get(session_id)
            if s is None:
                return None
            if time.time() - s.created_at > self._ttl:
                self._data.pop(session_id, None)
                self._note_eviction(session_id)
                return None
            s.last_seen_at = time.time()
            return s

    async def put(self, session: CourtSession) -> None:
        async with self._lock:
            self._data[session.session_id] = session

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._data.pop(session_id, None)

    def was_recently_evicted(self, session_id: str) -> bool:
        """True if this session_id was TTL-evicted (not explicitly deleted).

        Sync-safe — read of a dict key under the GIL is atomic enough for
        a single check. We don't take the async lock to keep this callable
        from sync route helpers.
        """
        return session_id in self._recently_evicted

    def _note_eviction(self, session_id: str) -> None:
        """Bounded LRU-ish ring of recently-evicted ids. Drops oldest if full."""
        if len(self._recently_evicted) >= self._EVICTED_RING_MAX:
            oldest_id = next(iter(self._recently_evicted))
            self._recently_evicted.pop(oldest_id, None)
        self._recently_evicted[session_id] = time.time()
