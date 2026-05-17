"""InMemoryCaseCache — TTL-bounded, in-process cache for parsed court results.

GREEN-ZONE replacement for the now-removed `parsed_case` / `case_party` /
`case_order` SQLAlchemy tables. Court data is **never** persisted to disk
by this cache; it lives only in the Python process and is bounded by a
hard TTL (default 24h, configurable via `settings.parsed_case_cache_ttl_seconds`).

Why an in-memory dict and not Redis (or anything on disk):
  * The owner directive is unambiguous: "NO long-term database storage of
    court data". A best-effort cleanup-job-against-a-DB is a runtime
    *promise*, not a *guarantee*. A process-local dict that vanishes on
    restart is the most honest implementation of the rule.
  * `CACHE_BACKEND=redis` is reserved for a v2 swap. Until then, the only
    accepted backend is "memory".

Semantics:
  * `get(case_type, case_number, year)`  → returns ParsedCase or None.
    A single-pass sweep removes any *other* expired keys it encounters on
    the way, so the cache self-prunes without a background task. Expired
    keys count as cache-miss + are evicted.
  * `put(case_type, case_number, year, case)`  → stores under the natural
    key, overwriting any prior entry. `expires_at = now + ttl`.
  * `stats()`  → snapshot {size, hits, misses, expirations, ttl_seconds}
    for the /admin observability page.

Concurrency:
  * One `asyncio.Lock` protects the dict. The cache is intended for a
    single-process FastAPI app; this is not a multi-worker primitive.
    For multi-worker deployments we'd swap to Redis (v2).

What we deliberately do NOT do:
  * Persist to disk on shutdown — would defeat the directive.
  * Background sweep thread/task — the on-`get` sweep is enough for the
    expected hit rate; a coordinated sweeper adds a moving part for no
    benefit at MVP scale.
  * Eviction by size — the cache is bounded by TTL only. If the cache
    ever needs an upper-bound, add an LRU lid here; do not move to disk.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from app.parsers.case_parser import ParsedCase

# 24h. Kept in sync with settings.parsed_case_cache_ttl_seconds so that
# constructing without an explicit ttl still matches the documented default.
DEFAULT_TTL_SECONDS = 86_400


# A normalised cache key — case_type uppercased & stripped, case_number
# leading-zero-stripped (so "00001" and "1" collide as the court treats
# them), year as int.
CacheKey = Tuple[str, str, int]


def _now() -> float:
    """Indirect time.time so tests can monkeypatch the module attribute."""
    return time.time()


def _normalise(case_type: str, case_number: str, year: int) -> CacheKey:
    """Canonical key tuple. Mirrors how the route layer normalises input
    (case_type as-typed but trimmed; case_number with leading zeros
    stripped, like search.py does via `.lstrip('0') or '0'`)."""
    ct = (case_type or "").strip()
    cn = (case_number or "").lstrip("0") or "0"
    return (ct, cn, int(year))


@dataclass
class _Entry:
    """Internal store entry. `expires_at` is an absolute epoch (seconds)."""
    case: ParsedCase
    expires_at: float


@dataclass
class CacheStats:
    """Snapshot of cache counters. Wire-shape for /admin observability."""
    size: int
    hits: int
    misses: int
    expirations: int
    ttl_seconds: int


class InMemoryCaseCache:
    """Process-local, TTL-bounded cache. See module docstring for rationale.

    The cache surfaces three async methods (`get`, `put`, `stats`) plus a
    sync `clear()` used by tests. Production code should never call
    `clear()`.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        if ttl_seconds <= 0:
            raise ValueError(
                f"InMemoryCaseCache ttl_seconds must be > 0; got {ttl_seconds}"
            )
        if ttl_seconds > 86_400:
            # Hard ceiling — the directive caps cache at 24h. We refuse to
            # be configured looser than that. Tighter is fine.
            raise ValueError(
                f"InMemoryCaseCache ttl_seconds must be <= 86400 (24h) "
                f"per GREEN-ZONE directive; got {ttl_seconds}"
            )
        self._ttl: int = ttl_seconds
        self._lock = asyncio.Lock()
        self._data: dict[CacheKey, _Entry] = {}
        self._hits: int = 0
        self._misses: int = 0
        self._expirations: int = 0

    # ── public API ────────────────────────────────────────────────────

    async def get(
        self, case_type: str, case_number: str, year: int
    ) -> Optional[ParsedCase]:
        """Return the cached ParsedCase or None. Sweeps expired keys.

        Semantics:
          * Hit (not expired)  → returns the ParsedCase, bumps `hits`.
          * Hit (expired)      → removes the entry, bumps `expirations`
                                 *and* `misses`, returns None.
          * Miss               → bumps `misses`, returns None.

        Side-effect: while holding the lock we run a single-pass sweep
        over the dict and drop any entries whose `expires_at < now`. This
        gives us TTL enforcement without a background task.
        """
        key = _normalise(case_type, case_number, year)
        now = _now()
        async with self._lock:
            self._sweep_locked(now)
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            # Should not happen post-sweep, but be defensive — the sweep
            # uses the same `now` so we cannot disagree.
            if entry.expires_at <= now:
                self._data.pop(key, None)
                self._expirations += 1
                self._misses += 1
                return None
            self._hits += 1
            return entry.case

    async def put(
        self,
        case_type: str,
        case_number: str,
        year: int,
        case: ParsedCase,
    ) -> None:
        """Store/overwrite. `expires_at = now + ttl`."""
        key = _normalise(case_type, case_number, year)
        now = _now()
        async with self._lock:
            self._data[key] = _Entry(case=case, expires_at=now + self._ttl)

    async def stats(self) -> CacheStats:
        """Snapshot of counters. Cheap — does not sweep."""
        async with self._lock:
            return CacheStats(
                size=len(self._data),
                hits=self._hits,
                misses=self._misses,
                expirations=self._expirations,
                ttl_seconds=self._ttl,
            )

    def clear(self) -> None:
        """Test-only: drop all entries + reset counters. Sync because
        tests call it from fixtures that don't run in an event loop.

        NEVER call from production code — there is no policy use case
        for wiping the cache except 'restart the process'.
        """
        self._data.clear()
        self._hits = 0
        self._misses = 0
        self._expirations = 0

    # ── internals ─────────────────────────────────────────────────────

    def _sweep_locked(self, now: float) -> None:
        """Single-pass eviction. Caller MUST hold `_lock`.

        Cheap: O(n) over the cache size. For MVP traffic n is tens to low
        hundreds; we do not need a sorted-by-expiry structure.
        """
        expired = [k for k, e in self._data.items() if e.expires_at <= now]
        for k in expired:
            self._data.pop(k, None)
            self._expirations += 1
