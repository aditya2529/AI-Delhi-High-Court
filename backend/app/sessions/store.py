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
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)


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
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
        self._data: dict[str, CourtSession] = {}

    async def create(self, case_type: str, case_number: str, year: int) -> CourtSession:
        session = CourtSession(
            session_id=uuid.uuid4().hex,
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
                return None
            s.last_seen_at = time.time()
            return s

    async def put(self, session: CourtSession) -> None:
        async with self._lock:
            self._data[session.session_id] = session

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._data.pop(session_id, None)
