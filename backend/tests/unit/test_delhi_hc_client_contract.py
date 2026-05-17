"""Contract tests for `DelhiHCClient` — verifies wire behaviour without network.

What this suite locks in (from Arnav's spike + the build assumptions Arjun
got from the owner):

  * The 4 endpoint paths discovered in Phase-0 recon are the ones called.
  * Every POST sends the URL-decoded XSRF cookie value in X-XSRF-TOKEN.
  * The hc_application_session cookie persists across the 3-step sequence.
  * The honest User-Agent from settings is sent on every request.
  * POST body schema matches the placeholder field names (B.2 unconfirmed).
  * The 3-step flow can be toggled to 2-step via the constructor flag.
  * OUTBOUND_FETCH_ENABLED=false short-circuits BEFORE any request.
  * A hostname not on DHC_HOSTNAME_ALLOWLIST short-circuits BEFORE any request.

How it stays offline: all HTTP is served via `httpx.MockTransport`. The
transport handler returns canned responses and records every Request the
client emitted, so we can assert URL, method, headers, body, and cookie
behaviour without opening a socket. No `respx` is needed.
"""
from __future__ import annotations

import urllib.parse
from typing import Callable

import httpx
import pytest

from app.clients.court_client import (
    CourtBlockedError,
    OutboundDisabledError,
)
from app.clients.delhi_hc_client import (
    COOKIE_SESSION,
    COOKIE_XSRF,
    ENDPOINT_FORM_PAGE,
    ENDPOINT_GET_CAPTCHA,
    ENDPOINT_SUBMIT,
    ENDPOINT_VALIDATE_CAPTCHA,
    DelhiHCClient,
)
from app.config import get_settings
from app.runtime_flags import get_flags
from app.sessions.store import CourtSession


# A realistic Laravel-style URL-encoded XSRF token (the % bytes matter).
RAW_XSRF = "eyJpdiI6Imh5akh2blNPRjBSN2xuYWZyVHpvMkE9PSIsInZhbHVlIjoicGViNnFjMjYwa0tYSkQybUtNS1FXTVVmZWQzdGR0Ky9qaUczNFBaYU1icFFhWnlYNHdxWi83d2lMTGN4TnZaQ3N3THZNT3RZTlNOUStYYzdacXBydUtmOHcrRnEzMFgvVGRINHNoSTRqd2JKRE9GQkFsNU91ZjJZeThiL3VobnkiLCJtYWMiOiJmZDhlNGJjZDE3OTQ1NDM4Nzk4NTNjZDVmMjMyMGQ1ODg4OTM1MmYzNjA0MzBmYjZlYzQwMDE2MWQ4ZjNmZmIxIiwidGFnIjoiIn0%3D"
RAW_SESSION = "eyJpdiI6IkxqdThpeXo1eW1hUG5qcTJ5TWE4Qnc9PSIsInZhbHVlIjoiUFJPdnkya2IxdHdTbktuWU5qUFI0dkxTRElGSTFHZXFmbGlaOHNvVjhUYUswQnk5dWVTQ3VKcEQwc2Q5dk9ySk9LZVRWUDZQVVBNOUtUOUFzK3k5L2dZSHRmK0k1dnhxVWlMZ2dKdldQS0t5MGFHOHZtT04va0d3WTZFYlk5VFIiLCJtYWMiOiJhYzkxMjA2NTYwNmFhYjU1NDY1YzkxOTcwZTYwMWM1NzFkMjZhNzNkYTUzZTlhOTY2ZjIyNmQzYmE3MTY4YjNlIiwidGFnIjoiIn0%3D"
DECODED_XSRF = urllib.parse.unquote(RAW_XSRF)


@pytest.fixture(autouse=True)
def _disable_pacing(monkeypatch):
    """Pacing is correct in production but would slow this suite to 12s+
    per test. The pacing logic itself is exercised by inspection — for
    contract tests we just don't want the 3s sleep."""
    from app.clients import delhi_hc_client as mod
    monkeypatch.setattr(mod, "MIN_REQUEST_SPACING_SECONDS", 0.0)


def _make_handler(captured: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler that records calls and returns canned bodies.

    Behaviour:
      * GET /app/get-case-type-status sets both cookies and returns 200 HTML.
      * GET /app/getCaptcha returns a tiny PNG byte blob with image/png.
      * POST /app/validateCaptcha returns 200 JSON ok.
      * POST /app/get-case-type-status returns 200 HTML with a known marker.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        if request.method == "GET" and path == ENDPOINT_FORM_PAGE:
            return _form_page_response_with_cookies()
        if request.method == "GET" and path == ENDPOINT_GET_CAPTCHA:
            return httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\nFAKE_IMAGE_BYTES",
                headers={"content-type": "image/png"},
            )
        if request.method == "POST" and path == ENDPOINT_VALIDATE_CAPTCHA:
            return httpx.Response(
                200,
                json={"status": True, "message": "ok"},
            )
        if request.method == "POST" and path == ENDPOINT_SUBMIT:
            return httpx.Response(
                200,
                text="<html>case results: marker_CONTRACT_TEST</html>",
            )
        if request.method == "GET" and path == "/robots.txt":
            return httpx.Response(404, text="")
        raise AssertionError(f"unexpected request: {request.method} {path}")
    return handler


def _form_page_response_with_cookies() -> httpx.Response:
    """The init GET sets both Laravel cookies via two Set-Cookie headers."""
    return httpx.Response(
        200,
        text="<html>form page</html>",
        headers=[
            ("set-cookie", f"{COOKIE_XSRF}={RAW_XSRF}; path=/; secure; samesite=lax"),
            ("set-cookie", f"{COOKIE_SESSION}={RAW_SESSION}; path=/; secure; httponly; samesite=lax"),
        ],
    )


def _mk_client(
    *,
    validate_before_submit: bool = True,
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
    captured: list[httpx.Request] | None = None,
) -> tuple[DelhiHCClient, list[httpx.Request]]:
    """Build a DelhiHCClient with an injected MockTransport for tests."""
    recorded: list[httpx.Request] = captured if captured is not None else []
    h = handler or _make_handler(recorded)
    transport = httpx.MockTransport(h)
    # Force settings re-read (autouse conftest sets env vars).
    get_settings.cache_clear()
    client = DelhiHCClient(
        transport=transport,
        validate_before_submit=validate_before_submit,
    )
    return client, recorded


class TestEndpointPathsAndMethods:
    async def test_3_step_flow_calls_all_four_endpoints_in_order(self):
        """init → captcha → validate → submit — paths + methods pinned."""
        client, recorded = _mk_client(validate_before_submit=True)
        try:
            await client.init_session(
                case_type="W.P.(C)", case_number="12345", year=2024,
            )
            session = CourtSession(
                session_id="sid", case_type="W.P.(C)",
                case_number="12345", year=2024,
            )
            await client.fetch_captcha(session=session)
            await client.submit_search(session=session, captcha_text="ABCDE")
        finally:
            await client.aclose()

        observed = [(r.method, r.url.path) for r in recorded]
        assert observed == [
            ("GET", ENDPOINT_FORM_PAGE),
            ("GET", ENDPOINT_GET_CAPTCHA),
            ("POST", ENDPOINT_VALIDATE_CAPTCHA),
            ("POST", ENDPOINT_SUBMIT),
        ]

    async def test_2_step_flow_skips_validate_captcha(self):
        """Flag flip: validate_before_submit=False → no validateCaptcha call."""
        client, recorded = _mk_client(validate_before_submit=False)
        try:
            await client.init_session(
                case_type="FAO", case_number="1", year=2025,
            )
            session = CourtSession(
                session_id="sid", case_type="FAO",
                case_number="1", year=2025,
            )
            await client.fetch_captcha(session=session)
            await client.submit_search(session=session, captcha_text="ABCDE")
        finally:
            await client.aclose()

        observed = [(r.method, r.url.path) for r in recorded]
        assert ("POST", ENDPOINT_VALIDATE_CAPTCHA) not in observed
        assert observed == [
            ("GET", ENDPOINT_FORM_PAGE),
            ("GET", ENDPOINT_GET_CAPTCHA),
            ("POST", ENDPOINT_SUBMIT),
        ]


class TestXsrfHeaderOnEveryPost:
    async def test_xsrf_header_is_url_decoded_cookie_value(self):
        """Every POST carries X-XSRF-TOKEN == urllib.unquote(XSRF-TOKEN)."""
        client, recorded = _mk_client(validate_before_submit=True)
        try:
            await client.init_session(
                case_type="W.P.(C)", case_number="12345", year=2024,
            )
            session = CourtSession(
                session_id="sid", case_type="W.P.(C)",
                case_number="12345", year=2024,
            )
            await client.fetch_captcha(session=session)
            await client.submit_search(session=session, captcha_text="ABCDE")
        finally:
            await client.aclose()

        posts = [r for r in recorded if r.method == "POST"]
        assert len(posts) == 2, "validate + submit"
        for req in posts:
            sent = req.headers.get("x-xsrf-token", "")
            assert sent == DECODED_XSRF, (
                "X-XSRF-TOKEN must be the URL-decoded XSRF-TOKEN cookie value"
            )
            assert "%3D" not in sent, "must be decoded, not raw URL-encoded"


class TestSessionCookiePersistence:
    async def test_hc_application_session_persists_across_3_steps(self):
        """The hc_application_session cookie set on init flows to every later call."""
        client, recorded = _mk_client(validate_before_submit=True)
        try:
            await client.init_session(
                case_type="W.P.(C)", case_number="12345", year=2024,
            )
            session = CourtSession(
                session_id="sid", case_type="W.P.(C)",
                case_number="12345", year=2024,
            )
            await client.fetch_captcha(session=session)
            await client.submit_search(session=session, captcha_text="ABCDE")
        finally:
            await client.aclose()

        # Skip the very first init GET (sets the cookie). All subsequent
        # requests must carry hc_application_session.
        later = recorded[1:]
        assert later, "should have at least 3 subsequent requests"
        for req in later:
            cookie_header = req.headers.get("cookie", "")
            assert COOKIE_SESSION in cookie_header, (
                f"{COOKIE_SESSION} missing on {req.method} {req.url.path}: "
                f"cookie header={cookie_header!r}"
            )

        # And the route-layer session must have been written back with both
        # cookies so refresh-captcha can rehydrate without going through init.
        assert session.cookies.get(COOKIE_XSRF), "XSRF cookie must persist on session"
        assert session.cookies.get(COOKIE_SESSION), "session cookie must persist on session"


class TestHonestUserAgent:
    async def test_user_agent_from_settings_on_every_request(self):
        """All requests carry settings.dhc_user_agent as User-Agent."""
        expected_ua = get_settings().dhc_user_agent
        client, recorded = _mk_client(validate_before_submit=True)
        try:
            await client.init_session(
                case_type="W.P.(C)", case_number="12345", year=2024,
            )
            session = CourtSession(
                session_id="sid", case_type="W.P.(C)",
                case_number="12345", year=2024,
            )
            await client.fetch_captcha(session=session)
            await client.submit_search(session=session, captcha_text="ABCDE")
        finally:
            await client.aclose()

        for req in recorded:
            assert req.headers.get("user-agent") == expected_ua, (
                f"User-Agent drift on {req.method} {req.url.path}"
            )


class TestPostBodySchema:
    async def test_submit_body_matches_b2_placeholder_field_names(self):
        """POST body uses the documented B.2-unconfirmed field names."""
        client, recorded = _mk_client(validate_before_submit=False)
        try:
            await client.init_session(
                case_type="W.P.(C)", case_number="12345", year=2024,
            )
            session = CourtSession(
                session_id="sid", case_type="W.P.(C)",
                case_number="12345", year=2024,
            )
            await client.fetch_captcha(session=session)
            await client.submit_search(session=session, captcha_text="ZX9QP")
        finally:
            await client.aclose()

        submit = [r for r in recorded if r.method == "POST" and r.url.path == ENDPOINT_SUBMIT][0]
        body = urllib.parse.parse_qs(submit.content.decode("utf-8"))
        assert body == {
            "case_type": ["W.P.(C)"],
            "case_number": ["12345"],
            "case_year": ["2024"],
            "captcha": ["ZX9QP"],
        }


class TestKillSwitch:
    async def test_outbound_disabled_blocks_init_before_request(self, monkeypatch):
        """OUTBOUND_FETCH_ENABLED=false → raise BEFORE any HTTP call."""
        recorded: list[httpx.Request] = []
        client, _ = _mk_client(captured=recorded)
        monkeypatch.setattr(get_flags(), "outbound_fetch_enabled", False)
        try:
            with pytest.raises(OutboundDisabledError):
                await client.init_session(
                    case_type="W.P.(C)", case_number="1", year=2024,
                )
        finally:
            await client.aclose()
        assert recorded == [], "no request should have been emitted"

    async def test_outbound_disabled_blocks_submit_before_request(self, monkeypatch):
        recorded: list[httpx.Request] = []
        client, _ = _mk_client(captured=recorded)
        # Init first to populate the session, then flip the switch.
        await client.init_session(case_type="W.P.(C)", case_number="1", year=2024)
        session = CourtSession(
            session_id="sid", case_type="W.P.(C)", case_number="1", year=2024,
        )
        await client.fetch_captcha(session=session)
        baseline_count = len(recorded)
        monkeypatch.setattr(get_flags(), "outbound_fetch_enabled", False)
        try:
            with pytest.raises(OutboundDisabledError):
                await client.submit_search(session=session, captcha_text="X")
        finally:
            await client.aclose()
        assert len(recorded) == baseline_count, "no new request after kill switch"


class TestHostnameAllowlist:
    async def test_hostname_not_on_allowlist_raises_before_request(
        self, monkeypatch
    ):
        """SSRF guard: base_url host not on allowlist → CourtBlockedError, no call."""
        monkeypatch.setenv("DHC_BASE_URL", "https://evil.example.com")
        monkeypatch.setenv("DHC_HOSTNAME_ALLOWLIST", "delhihighcourt.nic.in")
        get_settings.cache_clear()
        recorded: list[httpx.Request] = []
        client, _ = _mk_client(captured=recorded)
        try:
            with pytest.raises(CourtBlockedError):
                await client.init_session(
                    case_type="W.P.(C)", case_number="1", year=2024,
                )
        finally:
            await client.aclose()
        assert recorded == [], "SSRF guard must fire before any wire activity"
