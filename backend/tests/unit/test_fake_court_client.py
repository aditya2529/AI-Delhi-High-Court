"""Unit tests for FakeCourtClient.

Pins the contract called out in STRATEGIES.md §2 and the routing rules
documented in `parsers/fixtures/sample_responses/README.md`. These tests
must keep passing when the real DelhiHCClient is added — the fake is
the shape-compatibility check for the contract.
"""
from __future__ import annotations

import base64

import pytest

from app.clients.court_client import (
    CaptchaIncorrectError,
    OutboundDisabledError,
)
from app.clients.fake_court_client import FakeCourtClient, b64_image
from app.runtime_flags import get_flags
from app.sessions.store import CourtSession


class TestCaptchaImage:
    async def test_fetch_captcha_returns_png_bytes(self):
        """Happy path: returns a non-empty PNG byte blob + MIME + token."""
        client = FakeCourtClient()
        session = CourtSession(session_id="x", case_type="W.P.(C)",
                               case_number="12345", year=2024)
        result = await client.fetch_captcha(session=session)
        assert result.image_mime == "image/png"
        assert result.image_bytes.startswith(b"\x89PNG\r\n\x1a\n"), \
            "image_bytes must be a valid PNG header"
        assert len(result.image_bytes) > 200
        assert isinstance(result.upstream_token, str)
        assert result.upstream_token  # non-empty

    async def test_b64_encode_is_ascii(self):
        """The b64 helper produces an ASCII string suitable for JSON."""
        client = FakeCourtClient()
        session = CourtSession(session_id="x", case_type="FAO",
                               case_number="1", year=2025)
        result = await client.fetch_captcha(session=session)
        encoded = b64_image(result.image_bytes)
        assert encoded.isascii()
        # round-trip
        assert base64.b64decode(encoded) == result.image_bytes


class TestSubmitRouting:
    async def test_known_tuple_returns_matching_fixture(self):
        """Known (case_type, case_number, year) → that fixture's HTML."""
        client = FakeCourtClient()
        session = CourtSession(session_id="x", case_type="W.P.(C)",
                               case_number="12345", year=2024)
        result = await client.submit_search(session=session, captcha_text="ABCDE")
        assert "W.P.(C) 12345/2024" in result.raw_html
        assert "PENDING" in result.raw_html

    async def test_unknown_tuple_falls_back_to_notfound(self):
        """Unknown tuple → NOTFOUND fixture (mirrors real court behaviour)."""
        client = FakeCourtClient()
        session = CourtSession(session_id="x", case_type="ZZ",
                               case_number="0", year=2020)
        result = await client.submit_search(session=session, captcha_text="ABCDE")
        assert "No records found" in result.raw_html

    async def test_case_number_court_error_returns_court_error_fixture(self):
        """Test hook: explicit sentinel `case_number='COURT_ERROR'` surfaces
        the court-500 fixture. Replaces the old `year=1900` heuristic, which
        coupled the selector to in-band schema data."""
        client = FakeCourtClient()
        session = CourtSession(session_id="x", case_type="W.P.(C)",
                               case_number="COURT_ERROR", year=2024)
        result = await client.submit_search(session=session, captcha_text="X")
        assert "500" in result.raw_html
        assert "internal server error" in result.raw_html.lower()

    async def test_case_number_court_error_is_case_insensitive(self):
        """`court_error` / `Court_Error` should also trip the sentinel —
        the selector normalises with .upper() so callers don't need to."""
        client = FakeCourtClient()
        session = CourtSession(session_id="x", case_type="W.P.(C)",
                               case_number="court_error", year=2024)
        result = await client.submit_search(session=session, captcha_text="X")
        assert "internal server error" in result.raw_html.lower()


class TestCaptchaIncorrectSentinel:
    async def test_literal_wrong_raises_captcha_incorrect(self):
        """`captcha_text == 'WRONG'` → CaptchaIncorrectError. Sentinel for the
        route layer to simulate upstream rejection."""
        client = FakeCourtClient()
        session = CourtSession(session_id="x", case_type="W.P.(C)",
                               case_number="12345", year=2024)
        with pytest.raises(CaptchaIncorrectError):
            await client.submit_search(session=session, captcha_text="WRONG")

    async def test_wrong_is_case_insensitive(self):
        """`wrong` / `Wrong` should also trip the sentinel — humans type messily."""
        client = FakeCourtClient()
        session = CourtSession(session_id="x", case_type="W.P.(C)",
                               case_number="12345", year=2024)
        with pytest.raises(CaptchaIncorrectError):
            await client.submit_search(session=session, captcha_text="wrong")


class TestKillSwitch:
    async def test_outbound_disabled_blocks_init_session(self, monkeypatch):
        """Sneha's kill switch must refuse outbound calls even on the fake."""
        flags = get_flags()
        monkeypatch.setattr(flags, "outbound_fetch_enabled", False)
        client = FakeCourtClient()
        with pytest.raises(OutboundDisabledError):
            await client.init_session(
                case_type="W.P.(C)", case_number="1", year=2024
            )

    async def test_outbound_disabled_blocks_submit(self, monkeypatch):
        flags = get_flags()
        monkeypatch.setattr(flags, "outbound_fetch_enabled", False)
        client = FakeCourtClient()
        session = CourtSession(session_id="x", case_type="W.P.(C)",
                               case_number="12345", year=2024)
        with pytest.raises(OutboundDisabledError):
            await client.submit_search(session=session, captcha_text="ABCDE")
