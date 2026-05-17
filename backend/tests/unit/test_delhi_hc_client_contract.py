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
    CaptchaIncorrectError,
    CourtBlockedError,
    CourtClientError,
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
def _reset_caches_and_flags():
    """Reset module-level caches and runtime flags before AND after every
    test in this file so order-of-execution can never leak state.

    `get_settings` is an ``lru_cache``-wrapped factory — clear it both
    sides. `get_flags` is NOT cached (returns a module singleton); we
    instead reset the live ``outbound_fetch_enabled`` attribute to the
    test-env value so kill-switch tests can't leak a False into the next
    test. Removes the ordering risk Raj flagged.
    """
    def _reset() -> None:
        get_settings.cache_clear()
        get_flags().outbound_fetch_enabled = True
    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def _disable_pacing(monkeypatch):
    """Pacing is correct in production but would slow this suite to 12s+
    per test. The pacing logic itself is exercised by inspection — for
    contract tests we just don't want the 3s sleep."""
    from app.clients import delhi_hc_client as mod
    monkeypatch.setattr(mod, "MIN_REQUEST_SPACING_SECONDS", 0.0)


@pytest.fixture(autouse=True)
def _isolate_capture(monkeypatch, tmp_path):
    """The post-demo capture path (DelhiHCClient.submit_search →
    response_capture) defaults to writing into
    parsers/fixtures/real_responses/. Contract tests that drive
    submit_search end-to-end would silently pollute that directory.
    Redirect to a tmp_path AND disable the feature flag belt-and-braces
    so a failing redirect doesn't quietly leak files."""
    from app.clients import response_capture as cap_mod
    monkeypatch.setattr(cap_mod, "DEFAULT_CAPTURE_DIR", tmp_path)
    monkeypatch.setenv("DHC_CAPTURE_REAL_RESPONSES", "false")


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


# ────────────────────────────────────────────────────────────────────────
# Retry + error-mapping tests (Raj review: M3 + M4)
# ────────────────────────────────────────────────────────────────────────


def _make_init_then_captcha_handler(
    captured: list[httpx.Request],
    validate_captcha_response: httpx.Response,
) -> Callable[[httpx.Request], httpx.Response]:
    """Handler that lets init + captcha + validate succeed up to the validate
    step, then returns the caller-supplied response for /validateCaptcha.

    Used by the CaptchaIncorrectError regression test: we need a full
    init → captcha → validate path so submit_search reaches the validate
    call we want to assert on.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        if request.method == "GET" and path == ENDPOINT_FORM_PAGE:
            return _form_page_response_with_cookies()
        if request.method == "GET" and path == ENDPOINT_GET_CAPTCHA:
            return httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\nFAKE",
                headers={"content-type": "image/png"},
            )
        if request.method == "POST" and path == ENDPOINT_VALIDATE_CAPTCHA:
            return validate_captcha_response
        if request.method == "POST" and path == ENDPOINT_SUBMIT:
            # Should not be reached when validate returns non-2xx.
            return httpx.Response(200, text="<html>unexpected submit</html>")
        if request.method == "GET" and path == "/robots.txt":
            return httpx.Response(404, text="")
        raise AssertionError(f"unexpected request: {request.method} {path}")
    return handler


class TestValidateCaptcha4xxMapping:
    """M3: validateCaptcha 4xx must surface as CaptchaIncorrectError so the
    route layer maps it to a 200 captcha_failed response, NOT a 503
    court_error.
    """

    async def test_4xx_from_validate_captcha_raises_captcha_incorrect(self):
        """A 422 from /validateCaptcha → CaptchaIncorrectError on submit_search."""
        recorded: list[httpx.Request] = []
        handler = _make_init_then_captcha_handler(
            recorded,
            validate_captcha_response=httpx.Response(
                422, json={"status": False, "message": "captcha invalid"},
            ),
        )
        client, _ = _mk_client(
            validate_before_submit=True, handler=handler, captured=recorded,
        )
        try:
            await client.init_session(
                case_type="W.P.(C)", case_number="1", year=2024,
            )
            session = CourtSession(
                session_id="sid", case_type="W.P.(C)",
                case_number="1", year=2024,
            )
            await client.fetch_captcha(session=session)
            with pytest.raises(CaptchaIncorrectError):
                await client.submit_search(session=session, captcha_text="WRONG")
        finally:
            await client.aclose()
        # Final submit must NOT have been attempted.
        submit_calls = [
            r for r in recorded
            if r.method == "POST" and r.url.path == ENDPOINT_SUBMIT
        ]
        assert submit_calls == [], (
            "submit must be skipped when validateCaptcha rejects the captcha"
        )

    async def test_5xx_from_validate_captcha_raises_court_client_error(self):
        """A 503 from /validateCaptcha → generic CourtClientError (transport)."""
        recorded: list[httpx.Request] = []
        handler = _make_init_then_captcha_handler(
            recorded,
            validate_captcha_response=httpx.Response(503, text="upstream down"),
        )
        client, _ = _mk_client(
            validate_before_submit=True, handler=handler, captured=recorded,
        )
        try:
            await client.init_session(
                case_type="W.P.(C)", case_number="1", year=2024,
            )
            session = CourtSession(
                session_id="sid", case_type="W.P.(C)",
                case_number="1", year=2024,
            )
            await client.fetch_captcha(session=session)
            with pytest.raises(CourtClientError) as excinfo:
                await client.submit_search(session=session, captcha_text="X")
            assert not isinstance(excinfo.value, CaptchaIncorrectError), (
                "5xx must NOT be miscategorised as a captcha-incorrect error"
            )
        finally:
            await client.aclose()


# ────────────────────────────────────────────────────────────────────────
# M4: retry-behaviour tests for _send_with_retry. Counting handlers +
# patched asyncio.sleep keep the suite fast and deterministic.
# ────────────────────────────────────────────────────────────────────────


@pytest.fixture
def _no_sleep(monkeypatch):
    """Patch asyncio.sleep inside the client module so the retry-backoff
    doesn't add seconds to the test wall clock."""
    from app.clients import delhi_hc_client as mod

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", _instant)


def _counting_handler(
    *,
    responses: list[httpx.Response],
    path_to_count: str,
    counter: dict[str, int],
) -> Callable[[httpx.Request], httpx.Response]:
    """Return canned responses in order for `path_to_count`; serve the
    side paths (robots only) with bland defaults.

    The counted path is checked FIRST — these retry tests deliberately
    point `path_to_count` at endpoints the main test flow would normally
    serve themselves, so the count-and-return branch must win.

    Counter dict (passed in by ref) records how many times path_to_count
    was hit — that's the assertion subject for the retry tests.
    """
    idx = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == path_to_count:
            counter["n"] += 1
            i = idx["i"]
            idx["i"] = min(i + 1, len(responses) - 1)
            return responses[i]
        if request.method == "GET" and path == "/robots.txt":
            return httpx.Response(404, text="")
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


class TestSendWithRetry:
    """M4: pin the retry policy in code so future drift fails loudly.

    Policy (MAX_RETRY_ATTEMPTS=1):
      - 4xx → return immediately, NO retry. Caller sees CourtClientError.
      - 5xx → 200 → retry once, success. Handler hit exactly twice.
      - 5xx → 5xx → one retry, then surface failure. Handler hit twice.
    """

    async def test_4xx_does_not_retry_and_raises_court_client_error(
        self, _no_sleep,
    ):
        """A single 404 from the form page → CourtClientError, ONE call."""
        counter = {"n": 0}
        handler = _counting_handler(
            responses=[httpx.Response(404, text="not found")],
            path_to_count=ENDPOINT_FORM_PAGE,
            counter=counter,
        )
        # We can't reuse _mk_client here because _counting_handler owns
        # ENDPOINT_FORM_PAGE — build the client inline with the handler.
        get_settings.cache_clear()
        client = DelhiHCClient(transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(CourtClientError):
                await client.init_session(
                    case_type="W.P.(C)", case_number="1", year=2024,
                )
        finally:
            await client.aclose()
        assert counter["n"] == 1, (
            "4xx must NOT be retried — observed %d calls" % counter["n"]
        )

    async def test_5xx_then_200_retries_once_and_succeeds(self, _no_sleep):
        """5xx → 200 sequence: caller sees success, handler hit TWICE."""
        counter = {"n": 0}
        handler = _counting_handler(
            responses=[
                httpx.Response(503, text="transient"),
                _form_page_response_with_cookies(),
            ],
            path_to_count=ENDPOINT_FORM_PAGE,
            counter=counter,
        )
        get_settings.cache_clear()
        client = DelhiHCClient(transport=httpx.MockTransport(handler))
        try:
            result = await client.init_session(
                case_type="W.P.(C)", case_number="1", year=2024,
            )
        finally:
            await client.aclose()
        assert counter["n"] == 2, (
            "expected 1 retry on 5xx — observed %d calls" % counter["n"]
        )
        assert result[COOKIE_XSRF] == RAW_XSRF, "post-retry response must be used"

    async def test_5xx_then_5xx_retries_once_then_raises(self, _no_sleep):
        """5xx → 5xx: ONE retry only (not three), caller sees CourtClientError."""
        counter = {"n": 0}
        handler = _counting_handler(
            responses=[
                httpx.Response(503, text="down"),
                httpx.Response(502, text="still down"),
            ],
            path_to_count=ENDPOINT_FORM_PAGE,
            counter=counter,
        )
        get_settings.cache_clear()
        client = DelhiHCClient(transport=httpx.MockTransport(handler))
        try:
            # 5xx that survives retry is mapped to CourtClientError by
            # `_request` itself (added 2026-05-17 to keep upstream 5xx HTML
            # from leaking into the parser — see DelhiHCClient._request
            # docstring). The init_session XSRF check is therefore
            # unreachable on this path; the caller still sees a
            # CourtClientError, which is the contract under test.
            with pytest.raises(CourtClientError):
                await client.init_session(
                    case_type="W.P.(C)", case_number="1", year=2024,
                )
        finally:
            await client.aclose()
        assert counter["n"] == 2, (
            "MAX_RETRY_ATTEMPTS=1 → exactly 2 sends (1 + 1 retry); "
            "observed %d" % counter["n"]
        )


# ────────────────────────────────────────────────────────────────────────
# Regression: real-mode submit on /2023 cases returned HTTP 500 on
# 2026-05-17 (founder report). Root cause: upstream-5xx HTML reaching the
# parser via _request's pass-through. Lock the contract: upstream 5xx
# from the submit POST must raise CourtClientError, NOT return raw HTML.
# ────────────────────────────────────────────────────────────────────────


def _make_submit_status_handler(
    captured: list[httpx.Request],
    *,
    submit_response: httpx.Response,
) -> Callable[[httpx.Request], httpx.Response]:
    """init + captcha + validate succeed; submit returns the caller's response.

    Used by the upstream-500 regression test: we need init/captcha/validate
    to succeed all the way through so the submit POST is the one path
    under test.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        if request.method == "GET" and path == ENDPOINT_FORM_PAGE:
            return _form_page_response_with_cookies()
        if request.method == "GET" and path == ENDPOINT_GET_CAPTCHA:
            return httpx.Response(
                200, content=b"\x89PNG\r\n\x1a\nFAKE",
                headers={"content-type": "image/png"},
            )
        if request.method == "POST" and path == ENDPOINT_VALIDATE_CAPTCHA:
            return httpx.Response(200, json={"status": True, "message": "ok"})
        if request.method == "POST" and path == ENDPOINT_SUBMIT:
            return submit_response
        if request.method == "GET" and path == "/robots.txt":
            return httpx.Response(404, text="")
        raise AssertionError(f"unexpected request: {request.method} {path}")
    return handler


class TestSubmit5xxMapping:
    """Pin the contract for upstream 5xx on the final submit POST.

    Before 2026-05-17 this path silently passed the 500 HTML body to
    `DHCParserV1.parse_with_outcome`, which could raise unhandled
    extraction errors → global 500 handler → opaque user-facing failure
    with only a fresh request_id to grep on. The fix routes 5xx through
    `CourtClientError`, which the search service maps to
    `status='court_error'` per API-CONTRACT §3.
    """

    async def test_submit_500_after_retry_raises_court_client_error(
        self, _no_sleep,
    ):
        """5xx → 5xx on POST /get-case-type-status → CourtClientError, not raw HTML."""
        recorded: list[httpx.Request] = []
        handler = _make_submit_status_handler(
            recorded,
            submit_response=httpx.Response(
                500,
                text="<html><body><h1>500 Internal Server Error</h1></body></html>",
            ),
        )
        client, _ = _mk_client(
            validate_before_submit=True, handler=handler, captured=recorded,
        )
        try:
            await client.init_session(
                case_type="W.P.(C)", case_number="6569", year=2023,
            )
            session = CourtSession(
                session_id="sid", case_type="W.P.(C)",
                case_number="6569", year=2023,
            )
            await client.fetch_captcha(session=session)
            with pytest.raises(CourtClientError) as excinfo:
                await client.submit_search(session=session, captcha_text="42")
            # Must NOT be a CaptchaIncorrectError — 5xx is transport, not
            # a captcha rejection. The route layer relies on this typing
            # to pick the right user-facing envelope.
            from app.clients.court_client import CaptchaIncorrectError
            assert not isinstance(excinfo.value, CaptchaIncorrectError)
        finally:
            await client.aclose()
        # Submit was attempted (1 + 1 retry on 5xx → 2 submit POSTs).
        submit_calls = [
            r for r in recorded
            if r.method == "POST" and r.url.path == ENDPOINT_SUBMIT
        ]
        assert len(submit_calls) == 2, (
            "MAX_RETRY_ATTEMPTS=1 means 2 sends on persistent 5xx; "
            f"observed {len(submit_calls)}"
        )

    async def test_submit_500_then_200_recovers_via_retry(self, _no_sleep):
        """5xx → 200 on submit: caller sees success; the 200 HTML is parsed."""
        # Counter-style handler tied to ENDPOINT_SUBMIT path only.
        recorded: list[httpx.Request] = []
        submit_responses = [
            httpx.Response(503, text="<html>transient</html>"),
            httpx.Response(
                200,
                text="<html>case results: marker_RETRY_OK</html>",
            ),
        ]
        submit_idx = {"i": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            path = request.url.path
            if request.method == "GET" and path == ENDPOINT_FORM_PAGE:
                return _form_page_response_with_cookies()
            if request.method == "GET" and path == ENDPOINT_GET_CAPTCHA:
                return httpx.Response(
                    200, content=b"\x89PNG\r\n\x1a\nFAKE",
                    headers={"content-type": "image/png"},
                )
            if request.method == "POST" and path == ENDPOINT_VALIDATE_CAPTCHA:
                return httpx.Response(200, json={"status": True})
            if request.method == "POST" and path == ENDPOINT_SUBMIT:
                i = submit_idx["i"]
                submit_idx["i"] = min(i + 1, len(submit_responses) - 1)
                return submit_responses[i]
            if request.method == "GET" and path == "/robots.txt":
                return httpx.Response(404, text="")
            raise AssertionError(f"unexpected request: {request.method} {path}")

        get_settings.cache_clear()
        client = DelhiHCClient(transport=httpx.MockTransport(handler))
        try:
            await client.init_session(
                case_type="W.P.(C)", case_number="6569", year=2023,
            )
            session = CourtSession(
                session_id="sid", case_type="W.P.(C)",
                case_number="6569", year=2023,
            )
            await client.fetch_captcha(session=session)
            result = await client.submit_search(
                session=session, captcha_text="42",
            )
        finally:
            await client.aclose()
        assert "marker_RETRY_OK" in result.raw_html, (
            "post-retry 200 body must be the one returned to the caller"
        )


# ────────────────────────────────────────────────────────────────────────
# Structured logging — the founder asked for one-grep traceability from
# a request_id to the full step-by-step trail. Pin the event name and
# field set so future drift fails a test, not a 2am debug session.
# ────────────────────────────────────────────────────────────────────────


class TestStructuredLogging:
    """Pin the structured-log shape with `structlog.testing.capture_logs`.

    Why not pytest's `caplog`: the unit tests run without
    `configure_logging()` (no FastAPI app boot), so structlog's stdlib
    logger factory is not wired through pytest's stdlib capture. The
    `capture_logs` helper short-circuits structlog's processor chain
    and records every event as a dict — exactly the shape we want to
    assert on.
    """

    async def test_3_step_success_emits_dhc_step_for_each_agent(self):
        """init + validate + submit each emit a `dhc.step` log with the
        documented field set.
        """
        import structlog

        client, _ = _mk_client(validate_before_submit=True)
        try:
            with structlog.testing.capture_logs() as captured:
                await client.init_session(
                    case_type="W.P.(C)", case_number="6569", year=2023,
                )
                session = CourtSession(
                    session_id="sid", case_type="W.P.(C)",
                    case_number="6569", year=2023,
                )
                await client.fetch_captcha(session=session)
                await client.submit_search(session=session, captcha_text="42")
        finally:
            await client.aclose()

        steps = [e for e in captured if e.get("event") == "dhc.step"]
        agents = [e.get("agent") for e in steps]
        assert "init" in agents, f"init step missing; got {agents}"
        assert "validate" in agents, f"validate step missing; got {agents}"
        assert "submit" in agents, f"submit step missing; got {agents}"

        # Every dhc.step event carries the documented field set.
        required_fields = {
            "agent", "case_type", "case_number", "year",
            "http_status", "elapsed_ms", "cookie_names", "outcome",
        }
        for ev in steps:
            missing = required_fields - set(ev.keys())
            assert not missing, (
                f"dhc.step missing fields {missing} in event {ev!r}"
            )
            # Case tuple matches the user's input.
            assert ev["case_number"] == "6569"
            assert ev["year"] == 2023
            assert ev["outcome"] == "success"
            # Cookie *names* only — never values. XSRF + session cookies
            # are session-scoped secrets.
            assert isinstance(ev["cookie_names"], list)
            for name in ev["cookie_names"]:
                assert "=" not in name, "cookie names only, not values"

    async def test_submit_5xx_logs_http_error_outcome(self, _no_sleep):
        """A 500 on submit must emit a `dhc.step` with outcome=http_error
        so the trail is grep-able even when the request fails.
        """
        import structlog

        recorded: list[httpx.Request] = []
        handler = _make_submit_status_handler(
            recorded,
            submit_response=httpx.Response(
                500, text="<html>500</html>",
            ),
        )
        client, _ = _mk_client(
            validate_before_submit=True, handler=handler, captured=recorded,
        )
        try:
            with structlog.testing.capture_logs() as captured:
                await client.init_session(
                    case_type="W.P.(C)", case_number="10327", year=2023,
                )
                session = CourtSession(
                    session_id="sid", case_type="W.P.(C)",
                    case_number="10327", year=2023,
                )
                await client.fetch_captcha(session=session)
                with pytest.raises(CourtClientError):
                    await client.submit_search(session=session, captcha_text="42")
        finally:
            await client.aclose()

        submit_steps = [
            e for e in captured
            if e.get("event") == "dhc.step" and e.get("agent") == "submit"
        ]
        assert submit_steps, "submit-agent dhc.step must be emitted on failure"
        assert submit_steps[-1]["outcome"] == "http_error", (
            f"submit step on 5xx must carry outcome=http_error; "
            f"got {submit_steps[-1]}"
        )
        assert submit_steps[-1]["error"], (
            "error field must be populated on http_error outcome"
        )
