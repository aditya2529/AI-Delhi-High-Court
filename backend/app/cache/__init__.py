"""In-memory caching layer.

GREEN-ZONE directive (2026-05-17): court data MUST NOT be persisted to
a long-term database. The cache that replaced `parsed_case`/`case_party`/
`case_order` lives entirely in process memory with a hard TTL.

See `app.cache.in_memory_case_cache` for the implementation and
`docs/architecture/DATA-MODEL.md` for the rationale.
"""
from __future__ import annotations

from app.cache.in_memory_case_cache import (
    CacheStats,
    InMemoryCaseCache,
)

__all__ = ["InMemoryCaseCache", "CacheStats"]
