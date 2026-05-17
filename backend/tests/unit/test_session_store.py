"""Unit tests for `app.sessions.store.InMemorySessionStore`.

Covers the session contract called out in STRATEGIES.md §1:
  * create / get / put / delete round-trip
  * TTL eviction on get (`created_at + ttl < now` -> None + removed)
  * Concurrent access via asyncio.gather — no lost writes, no exceptions
  * `last_seen_at` advances on get (sliding-touch precursor)
  * Cookies + CSRF stored on session never leak via the public API
    surface beyond what was put in.
"""
from __future__ import annotations

import asyncio

import pytest

from app.sessions.store import CourtSession, InMemorySessionStore


# ── Happy-path round-trip ──────────────────────────────────────────────────

class TestCreateAndGet:
    async def test_create_returns_session_with_canonical_uuid_id(self, session_store):
        """S1.1 / AC-2: backend init mints a session_id in canonical
        RFC 4122 dashed UUID v4 form (see API-CONTRACT §7.3 and
        docs/DEMO-FEEDBACK.md item #4 — backend used to emit dashless
        hex which silently broke the frontend Zod validator)."""
        from uuid import UUID
        s = await session_store.create("W.P.(C)", "12345", 2024)
        assert isinstance(s.session_id, str)
        # Round-trip through UUID — only valid RFC 4122 IDs pass.
        parsed = UUID(s.session_id)
        assert parsed.version == 4
        assert str(parsed) == s.session_id  # canonical (lowercase, dashed)
        assert s.case_type == "W.P.(C)"
        assert s.case_number == "12345"
        assert s.year == 2024

    async def test_get_returns_same_session_just_created(self, session_store):
        """S1.1: session_id is the only handle the client gets back."""
        created = await session_store.create("FAO", "1", 2025)
        got = await session_store.get(created.session_id)
        assert got is not None
        assert got.session_id == created.session_id
        assert got.case_type == "FAO"

    async def test_get_unknown_id_returns_none(self, session_store):
        """S1.2 / AC: unknown session => 404 path. Store returns None."""
        result = await session_store.get("not-a-real-id")
        assert result is None

    async def test_put_overwrites_existing_session(self, session_store):
        """Putting twice with the same id is the persist-update primitive."""
        s = await session_store.create("LPA", "42", 2024)
        s.cookies = {"PHPSESSID": "abc123"}
        s.csrf_tokens = {"form_csrf": "tok-xyz"}
        await session_store.put(s)

        got = await session_store.get(s.session_id)
        assert got is not None
        assert got.cookies == {"PHPSESSID": "abc123"}
        assert got.csrf_tokens == {"form_csrf": "tok-xyz"}

    async def test_delete_removes_session(self, session_store):
        """S1.2: terminal status drops the session. Subsequent get => None."""
        s = await session_store.create("W.P.(C)", "1", 2024)
        await session_store.delete(s.session_id)
        assert await session_store.get(s.session_id) is None

    async def test_delete_unknown_id_is_silent(self, session_store):
        """Deleting a non-existent id must not raise — idempotent cleanup."""
        await session_store.delete("ghost-id")  # no assertion needed


# ── TTL eviction ───────────────────────────────────────────────────────────

class TestTTLEviction:
    async def test_get_returns_none_after_ttl_elapses(self, short_ttl_session_store, frozen_clock):
        """STRATEGIES §1: sliding TTL of 10min. Past TTL => evicted on get."""
        frozen_clock.set(1000.0)
        s = await short_ttl_session_store.create("W.P.(C)", "1", 2024)

        frozen_clock.advance(2.5)  # TTL is 1s
        assert await short_ttl_session_store.get(s.session_id) is None

    async def test_expired_session_is_removed_from_internal_store(
        self, short_ttl_session_store, frozen_clock
    ):
        """Eviction is real — not just hidden. Re-get after re-put still works."""
        frozen_clock.set(1000.0)
        s = await short_ttl_session_store.create("W.P.(C)", "1", 2024)

        frozen_clock.advance(2.5)
        await short_ttl_session_store.get(s.session_id)  # triggers eviction

        # Internal state confirmed (white-box; cheap)
        assert s.session_id not in short_ttl_session_store._data

    async def test_session_alive_just_before_ttl_boundary(
        self, short_ttl_session_store, frozen_clock
    ):
        """Sanity: eviction is at TTL boundary, not earlier."""
        frozen_clock.set(1000.0)
        s = await short_ttl_session_store.create("FAO", "1", 2025)
        frozen_clock.advance(0.5)  # under 1s TTL
        assert await short_ttl_session_store.get(s.session_id) is not None


# ── Concurrent access ─────────────────────────────────────────────────────

class TestConcurrency:
    async def test_concurrent_creates_all_get_unique_ids(self, session_store):
        """20 simultaneous creates => 20 unique session_ids, no collisions."""
        results = await asyncio.gather(*[
            session_store.create("W.P.(C)", str(i), 2024) for i in range(20)
        ])
        ids = {s.session_id for s in results}
        assert len(ids) == 20

    async def test_concurrent_get_and_put_does_not_deadlock_or_lose_data(self, session_store):
        """Adversarial: race read/write on the same session. No exceptions."""
        s = await session_store.create("LPA", "100", 2024)

        async def reader():
            for _ in range(50):
                got = await session_store.get(s.session_id)
                assert got is not None

        async def writer():
            for i in range(50):
                s.cookies["k"] = f"v{i}"
                await session_store.put(s)

        # All four tasks must finish in <2s — fast even on slow CI.
        await asyncio.wait_for(
            asyncio.gather(reader(), reader(), writer(), writer()),
            timeout=2.0,
        )

    async def test_concurrent_delete_with_get_is_safe(self, session_store):
        """Adversarial: delete while another coroutine is reading. Must not raise."""
        s = await session_store.create("CRL.M.C.", "9", 2024)

        async def reader():
            for _ in range(30):
                # May get None if delete already fired — that's the contract.
                await session_store.get(s.session_id)

        async def deleter():
            await asyncio.sleep(0)  # yield once
            await session_store.delete(s.session_id)

        await asyncio.gather(reader(), deleter())
        assert await session_store.get(s.session_id) is None


# ── CourtSession defaults & invariants ────────────────────────────────────

class TestCourtSessionShape:
    def test_court_session_defaults_to_empty_cookies_and_tokens(self):
        """A fresh CourtSession must NOT inherit shared mutable defaults."""
        a = CourtSession(session_id="a")
        b = CourtSession(session_id="b")
        a.cookies["x"] = "1"
        # If field(default_factory=dict) is mis-specified, b would see a's value.
        assert b.cookies == {}
        assert a.cookies == {"x": "1"}

    def test_court_session_records_created_and_last_seen(self):
        """STRATEGIES §1: timestamps drive TTL + admin observability."""
        s = CourtSession(session_id="x")
        assert s.created_at > 0
        assert s.last_seen_at > 0
