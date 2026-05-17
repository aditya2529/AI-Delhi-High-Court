"""Unit tests for FakeCourtClient.

Pins the contract called out in STRATEGIES.md §2 and the routing rules
documented in `parsers/fixtures/sample_responses/README.md`. These tests
must keep passing when the real DelhiHCClient is added — the fake is
the shape-compatibility check for the contract.

Math vs text mode:
  As of the 2026-05-17 founder demo, FakeCourtClient defaults to MATH
  CAPTCHAs to match the real Delhi HC site (see docs/DEMO-FEEDBACK.md
  item #6). TEXT mode is kept behind a flag so the team has a regression
  net for the day Delhi HC ever switches.
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


def _math_session(*, answer: int, case_type: str = "W.P.(C)",
                  case_number: str = "12345", year: int = 2024) -> CourtSession:
    """Build a session pre-seeded with a known math answer.

    Mirrors the end-to-end flow: in production, `fetch_captcha` returns
    the answer as `upstream_token`, and the route layer persists it onto
    `session.csrf_tokens["upstream_token"]`. We do the same shape here
    so tests exercise the real validation path.
    """
    s = CourtSession(session_id="x", case_type=case_type,
                     case_number=case_number, year=year)
    s.csrf_tokens["upstream_token"] = str(answer)
    return s


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

    async def test_math_mode_stores_integer_answer_in_upstream_token(self):
        """MATH mode: the integer answer round-trips through `upstream_token`.

        The route layer relies on this — it persists `upstream_token`
        onto `session.csrf_tokens["upstream_token"]`, and `submit_search`
        reads it back to validate the user's typed answer.
        """
        client = FakeCourtClient(captcha_mode="math")
        session = CourtSession(session_id="x", case_type="W.P.(C)",
                               case_number="12345", year=2024)
        result = await client.fetch_captcha(session=session)
        # Must parse to an integer in the expected range (1+1=2 .. 50+50=100).
        answer = int(result.upstream_token)
        assert 2 <= answer <= 100, (
            f"math answer {answer} outside expected [2, 100] range"
        )


class TestSubmitRoutingMathMode:
    async def test_correct_math_answer_returns_matching_fixture(self):
        """Known (case_type, case_number, year) → that fixture's HTML."""
        client = FakeCourtClient(captcha_mode="math")
        session = _math_session(answer=22)
        result = await client.submit_search(session=session, captcha_text="22")
        assert "W.P.(C) 12345/2024" in result.raw_html
        assert "PENDING" in result.raw_html

    async def test_correct_three_digit_math_answer_accepted(self):
        """100 (max possible: 50+50) must parse + validate cleanly."""
        client = FakeCourtClient(captcha_mode="math")
        session = _math_session(answer=100)
        result = await client.submit_search(session=session, captcha_text="100")
        # Just need a non-error return; default fixture routing applies.
        assert result.raw_html  # non-empty

    async def test_math_answer_with_surrounding_whitespace_accepted(self):
        """Real users add spaces; trim before parse."""
        client = FakeCourtClient(captcha_mode="math")
        session = _math_session(answer=42)
        result = await client.submit_search(
            session=session, captcha_text="  42  "
        )
        assert result.raw_html

    async def test_wrong_math_answer_raises_captcha_incorrect(self):
        """Numeric but wrong → CaptchaIncorrectError."""
        client = FakeCourtClient(captcha_mode="math")
        session = _math_session(answer=22)
        with pytest.raises(CaptchaIncorrectError):
            await client.submit_search(session=session, captcha_text="23")

    async def test_non_integer_math_answer_raises_captcha_incorrect(self):
        """ABC, 22.5, empty — non-integers all reject."""
        client = FakeCourtClient(captcha_mode="math")
        session = _math_session(answer=22)
        for bad in ("ABC", "22.5", "twenty-two"):
            with pytest.raises(CaptchaIncorrectError):
                await client.submit_search(session=session, captcha_text=bad)

    async def test_unknown_tuple_falls_back_to_notfound(self):
        """Unknown tuple → NOTFOUND fixture (mirrors real court behaviour)."""
        client = FakeCourtClient(captcha_mode="math")
        session = _math_session(answer=15, case_type="ZZ",
                                case_number="0", year=2020)
        result = await client.submit_search(session=session, captcha_text="15")
        assert "No records found" in result.raw_html

    async def test_case_number_court_error_returns_court_error_fixture(self):
        """Test hook: explicit sentinel `case_number='COURT_ERROR'` surfaces
        the court-500 fixture. Replaces the old `year=1900` heuristic, which
        coupled the selector to in-band schema data."""
        client = FakeCourtClient(captcha_mode="math")
        session = _math_session(answer=7, case_number="COURT_ERROR")
        result = await client.submit_search(session=session, captcha_text="7")
        assert "500" in result.raw_html
        assert "internal server error" in result.raw_html.lower()

    async def test_case_number_court_error_is_case_insensitive(self):
        """`court_error` / `Court_Error` should also trip the sentinel —
        the selector normalises with .upper() so callers don't need to."""
        client = FakeCourtClient(captcha_mode="math")
        session = _math_session(answer=7, case_number="court_error")
        result = await client.submit_search(session=session, captcha_text="7")
        assert "internal server error" in result.raw_html.lower()


class TestCaptchaIncorrectSentinel:
    """The WRONG sentinel works in both modes — useful for integration
    tests that want to force the failure path without computing an answer.
    """

    async def test_literal_wrong_raises_in_math_mode(self):
        """MATH default: `WRONG` short-circuits BEFORE the int parse."""
        client = FakeCourtClient(captcha_mode="math")
        session = _math_session(answer=22)
        with pytest.raises(CaptchaIncorrectError):
            await client.submit_search(session=session, captcha_text="WRONG")

    async def test_literal_wrong_raises_in_text_mode(self):
        """TEXT mode: `WRONG` is the historical sentinel — preserved."""
        client = FakeCourtClient(captcha_mode="text")
        session = CourtSession(session_id="x", case_type="W.P.(C)",
                               case_number="12345", year=2024)
        with pytest.raises(CaptchaIncorrectError):
            await client.submit_search(session=session, captcha_text="WRONG")

    async def test_wrong_is_case_insensitive(self):
        """`wrong` / `Wrong` should also trip the sentinel — humans type messily."""
        client = FakeCourtClient(captcha_mode="math")
        session = _math_session(answer=22)
        with pytest.raises(CaptchaIncorrectError):
            await client.submit_search(session=session, captcha_text="wrong")


class TestTextModeRegression:
    """TEXT mode is a regression net for the day Delhi HC adds a text
    CAPTCHA option. None of these tests are about today's behaviour —
    they pin the SHAPE so a future swap doesn't silently break.
    """

    async def test_text_mode_captcha_returns_png(self):
        """TEXT mode still produces a valid PNG image + opaque token."""
        client = FakeCourtClient(captcha_mode="text")
        session = CourtSession(session_id="x", case_type="W.P.(C)",
                               case_number="12345", year=2024)
        result = await client.fetch_captcha(session=session)
        assert result.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        # Token is an opaque hex (uuid4().hex), not a number.
        assert len(result.upstream_token) >= 16

    async def test_text_mode_accepts_any_non_wrong_text(self):
        """TEXT mode does not server-side-validate — only WRONG rejects.
        This mirrors the original behaviour pre-2026-05-17."""
        client = FakeCourtClient(captcha_mode="text")
        session = CourtSession(session_id="x", case_type="W.P.(C)",
                               case_number="12345", year=2024)
        result = await client.submit_search(
            session=session, captcha_text="ABCDE",
        )
        assert "W.P.(C) 12345/2024" in result.raw_html


class TestModeResolution:
    """`captcha_mode` kwarg > FAKE_COURT_CAPTCHA_MODE env > default ('math')."""

    async def test_default_mode_is_math(self, monkeypatch):
        """No kwarg, no env → math (matches real Delhi HC)."""
        monkeypatch.delenv("FAKE_COURT_CAPTCHA_MODE", raising=False)
        client = FakeCourtClient()
        session = CourtSession(session_id="x", case_type="FAO",
                               case_number="1", year=2024)
        result = await client.fetch_captcha(session=session)
        # Math token parses to an int in the expected range.
        assert 2 <= int(result.upstream_token) <= 100

    async def test_env_var_selects_text_mode(self, monkeypatch):
        """FAKE_COURT_CAPTCHA_MODE=text → opaque hex token."""
        monkeypatch.setenv("FAKE_COURT_CAPTCHA_MODE", "text")
        client = FakeCourtClient()
        session = CourtSession(session_id="x", case_type="FAO",
                               case_number="1", year=2024)
        result = await client.fetch_captcha(session=session)
        with pytest.raises(ValueError):
            int(result.upstream_token)  # text mode token is hex, not an int

    async def test_kwarg_overrides_env(self, monkeypatch):
        """Explicit kwarg wins over env var — the kwarg is the local override."""
        monkeypatch.setenv("FAKE_COURT_CAPTCHA_MODE", "text")
        client = FakeCourtClient(captcha_mode="math")
        session = CourtSession(session_id="x", case_type="FAO",
                               case_number="1", year=2024)
        result = await client.fetch_captcha(session=session)
        assert 2 <= int(result.upstream_token) <= 100


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
        session = _math_session(answer=22)
        with pytest.raises(OutboundDisabledError):
            await client.submit_search(session=session, captcha_text="22")
