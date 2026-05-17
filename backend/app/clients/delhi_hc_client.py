"""DelhiHCClient — real outbound client to delhihighcourt.nic.in.

CONTRACT:
  Drop-in replacement for `FakeCourtClient`. Subclasses `CourtClient` ABC,
  same method signatures, same exception hierarchy. The route layer never
  branches on which implementation is wired — `app.services.dependencies`
  selects between fake and real based on `Settings.client_mode`.

DEFAULTS:
  `CLIENT_MODE=fake` remains the project default. This client only runs
  when explicitly opted in.

REAL-CLIENT DESIGN (post-spike, see docs/SPIKE-REPORT.md §G):
  Endpoints discovered by Arnav's recon:
    GET   /app/get-case-type-status   — sets XSRF-TOKEN + hc_application_session
    GET   /app/getCaptcha?<query>     — CAPTCHA image bytes
    POST  /app/generate-captcha       — rotate CAPTCHA (refresh)
    POST  /app/validateCaptcha        — pre-submit CAPTCHA validation
    POST  /app/get-case-type-status   — final case search submit

  CSRF: Laravel XSRF — read XSRF-TOKEN cookie value, URL-decode it (Laravel
        URL-encodes the encrypted token in the Set-Cookie), echo it back as
        the X-XSRF-TOKEN header on every state-changing POST.
  Cookies: persist hc_application_session + XSRF-TOKEN across init → captcha
           → validate → submit, scoped to one shared httpx.AsyncClient cookie
           jar per concurrent search (keyed by case tuple, then handed off to
           the SessionStore's CourtSession.cookies for submit).
  Flow: defaults to 3-step (validateCaptcha → submit). Set
        `validate_before_submit=False` on the constructor to skip the
        explicit validate call if dev recon shows it's optional.
  Rate-limit: hardcoded ≥3s spacing between requests, process-global. One
              retry with exponential backoff on 5xx; no retry on 4xx.
  Safety: respects OUTBOUND_FETCH_ENABLED kill switch + DHC_HOSTNAME_ALLOWLIST
          SSRF guard. Both refuse before any byte hits the wire.
"""
from __future__ import annotations

import asyncio
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.clients.court_client import (
    CaptchaFetchResult,
    CaptchaIncorrectError,
    CaseSearchResult,
    CourtBlockedError,
    CourtClient,
    CourtClientError,
    OutboundDisabledError,
)
from app.clients.response_capture import capture_real_response
from app.config import Settings, get_settings
from app.runtime_flags import get_flags
from app.sessions.store import CourtSession
from app.utils.logging import get_logger

log = get_logger(__name__)


# Endpoint paths (relative to DHC_BASE_URL). Centralised so the contract
# test can pin them by reference rather than by literal string drift.
ENDPOINT_FORM_PAGE = "/app/get-case-type-status"
ENDPOINT_GET_CAPTCHA = "/app/getCaptcha"
ENDPOINT_REFRESH_CAPTCHA = "/app/generate-captcha"
ENDPOINT_VALIDATE_CAPTCHA = "/app/validateCaptcha"
ENDPOINT_SUBMIT = "/app/get-case-type-status"

# Cookie names observed in the Phase-0 stateful recon.
COOKIE_XSRF = "XSRF-TOKEN"
COOKIE_SESSION = "hc_application_session"

# Polite-client pacing (per Arnav's recon §B.7 + STRATEGIES.md §2).
MIN_REQUEST_SPACING_SECONDS = 3.0

# Retry policy for 5xx transport failures. One retry total, then surface
# the failure to the caller. 4xx is never retried — it's a contract error.
MAX_RETRY_ATTEMPTS = 1
RETRY_BACKOFF_BASE_SECONDS = 1.5


@dataclass
class _PendingSession:
    """Bridge object — populated in init_session, consumed in fetch_captcha.

    init_session opens the upstream cookie jar (GET form page) but the
    CourtClient ABC does not pass a CourtSession back to init_session, so
    we stash the cookies/token here keyed by (case_type, case_number, year)
    until fetch_captcha is called. After fetch_captcha hands the cookies to
    the route-layer CourtSession, this entry is dropped.
    """

    cookies: dict[str, str] = field(default_factory=dict)
    xsrf_token: str = ""
    created_at: float = field(default_factory=time.time)


def _decode_xsrf(raw_cookie_value: str) -> str:
    """URL-decode a Laravel XSRF-TOKEN cookie value.

    Laravel writes the encrypted token URL-encoded; clients echo the
    DECODED form back as X-XSRF-TOKEN. See SPIKE-REPORT §G (B.3).
    """
    return urllib.parse.unquote(raw_cookie_value)


def _pending_key(case_type: str, case_number: str, year: int) -> str:
    """Stable key for the _PendingSession map across init → captcha."""
    return f"{case_type}|{case_number}|{year}"


def _ms_since(started_unix: float) -> int:
    """Elapsed-ms helper for structured-log timings. Truncates to int."""
    return int((time.time() - started_unix) * 1000)


def _log_step(
    *,
    agent: str,
    case_type: str,
    case_number: str,
    year: int,
    http_status: Optional[int],
    elapsed_ms: int,
    cookie_names: tuple[str, ...],
    outcome: str,
    error: Optional[str] = None,
) -> None:
    """Emit a one-line structured trace for an init|validate|submit step.

    Why a single helper: the founder needs to be able to grep for one
    `request_id` and get the full step-by-step trail. Centralising the
    event name (`dhc.step`) + field set makes the grep deterministic and
    keeps drift between init/validate/submit log shapes to zero.

    NOTE: cookie *names* only — never values. The XSRF + session cookies
    are Laravel-encrypted but still session-scoped secrets; we log their
    presence, not their content. `request_id` is intentionally NOT
    threaded here — that's a request-scope contextvar handled by the
    route layer's logging middleware, and structlog's
    `merge_contextvars` processor will splice it onto every record
    automatically.
    """
    log.info(
        "dhc.step",
        agent=agent,
        case_type=case_type,
        case_number=case_number,
        year=year,
        http_status=http_status,
        elapsed_ms=elapsed_ms,
        cookie_names=list(cookie_names),
        outcome=outcome,
        error=error,
    )


class DelhiHCClient(CourtClient):
    """Real Delhi High Court outbound client.

    Holds a single httpx.AsyncClient with a per-host cookie jar. The
    ABC method shapes mirror FakeCourtClient so the route layer is
    implementation-agnostic. Concurrent searches are isolated by the
    per-search cookie set on the route-layer CourtSession; outbound
    requests rehydrate the relevant cookies before each call.
    """

    is_stub: bool = False

    def __init__(
        self,
        *,
        settings: Optional[Settings] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        validate_before_submit: bool = True,
    ) -> None:
        """Wire the AsyncClient + read settings.

        `transport` exists so contract tests can inject httpx.MockTransport
        without touching production wiring or making real network calls.
        `validate_before_submit` toggles the 3-step (default) vs 2-step
        submit flow — flip to False if dev recon shows validateCaptcha is
        optional (B.2 confirmation pending).
        """
        self._settings = settings or get_settings()
        self._validate_before_submit = validate_before_submit
        # NOTE: see Raj review — bridge is sequential-single-user only;
        # concurrency fix deferred to next sprint pending ABC adjustment.
        self._pending: dict[str, _PendingSession] = {}
        self._last_request_at: float = 0.0
        self._pacing_lock = asyncio.Lock()
        self._robots_parser: Optional[urllib.robotparser.RobotFileParser] = None
        self._robots_loaded: bool = False
        self._robots_fetched_at: float = 0.0
        self._client = httpx.AsyncClient(
            base_url=self._settings.dhc_base_url,
            timeout=self._settings.dhc_outbound_timeout_seconds,
            transport=transport,
            headers={
                "User-Agent": self._settings.dhc_user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
            },
        )

    async def aclose(self) -> None:
        """Release the underlying AsyncClient. Idempotent."""
        await self._client.aclose()

    # ─── CourtClient interface ─────────────────────────────────────────

    async def init_session(
        self,
        *,
        case_type: str,
        case_number: str,
        year: int,
    ) -> dict[str, str]:
        """GET the form page, capture cookies + XSRF token.

        Returns a metadata dict for symmetry with FakeCourtClient. The
        actual cookie/token state is stashed in `_pending` keyed by the
        case tuple for fetch_captcha to consume next.
        """
        self._guard_outbound_enabled()
        self._guard_hostname_allowed(self._settings.dhc_base_url)

        started = time.time()
        try:
            resp = await self._request("GET", ENDPOINT_FORM_PAGE)
        except CourtClientError as exc:
            _log_step(
                agent="init", case_type=case_type, case_number=case_number,
                year=year, http_status=None, elapsed_ms=_ms_since(started),
                cookie_names=(), outcome="exception", error=str(exc)[:200],
            )
            raise
        cookies = self._cookies_from_response(resp)
        xsrf_raw = cookies.get(COOKIE_XSRF, "")
        if not xsrf_raw:
            _log_step(
                agent="init", case_type=case_type, case_number=case_number,
                year=year, http_status=resp.status_code,
                elapsed_ms=_ms_since(started),
                cookie_names=tuple(sorted(cookies.keys())),
                outcome="http_error",
                error="upstream did not set XSRF-TOKEN cookie",
            )
            raise CourtClientError(
                "Init failed: upstream did not set XSRF-TOKEN cookie"
            )
        pending = _PendingSession(
            cookies=cookies, xsrf_token=_decode_xsrf(xsrf_raw)
        )
        self._pending[_pending_key(case_type, case_number, year)] = pending
        _log_step(
            agent="init", case_type=case_type, case_number=case_number,
            year=year, http_status=resp.status_code,
            elapsed_ms=_ms_since(started),
            cookie_names=tuple(sorted(cookies.keys())),
            outcome="success",
        )
        return {
            "case_type": case_type,
            "case_number": case_number,
            "year": str(year),
            COOKIE_XSRF: xsrf_raw,
            COOKIE_SESSION: cookies.get(COOKIE_SESSION, ""),
        }

    async def fetch_captcha(self, *, session: CourtSession) -> CaptchaFetchResult:
        """GET the CAPTCHA image. Persists cookies onto the CourtSession.

        Pulls the pending cookie jar from `_pending` if this is the first
        call (init → captcha handoff); otherwise rehydrates from the
        CourtSession (refresh case).
        """
        self._guard_outbound_enabled()
        self._guard_hostname_allowed(self._settings.dhc_base_url)

        cookies, xsrf = self._cookies_for(session)
        # Cache-buster query so any upstream/edge cache returns a fresh image.
        params = {"_": str(int(time.time() * 1000))}
        resp = await self._request(
            "GET", ENDPOINT_GET_CAPTCHA, params=params, cookies=cookies,
        )
        merged = {**cookies, **self._cookies_from_response(resp)}
        self._write_back_session(session, merged, xsrf)
        return CaptchaFetchResult(
            image_bytes=resp.content,
            image_mime=resp.headers.get("content-type", "image/png").split(";")[0].strip(),
            fetched_at_unix=time.time(),
            upstream_token=xsrf,
        )

    async def submit_search(
        self,
        *,
        session: CourtSession,
        captcha_text: str,
    ) -> CaseSearchResult:
        """3-step submit: validateCaptcha (optional) → final POST.

        Body field names confirmed via the real-world submit on 2026-05-17
        (see SPIKE-REPORT.md Section G).
        """
        self._guard_outbound_enabled()
        self._guard_hostname_allowed(self._settings.dhc_base_url)

        cookies, xsrf = self._cookies_for(session)
        # B.2 RESOLVED: field names confirmed via real-world submit
        # 2026-05-17 (see SPIKE-REPORT.md Section G).
        body = {
            "case_type": session.case_type,
            "case_number": session.case_number,
            "case_year": str(session.year),
            "captcha": captcha_text,
        }

        if self._validate_before_submit:
            await self._validate_captcha(
                cookies=cookies, xsrf=xsrf, captcha_text=captcha_text,
                case_type=session.case_type,
                case_number=session.case_number,
                year=session.year,
            )

        started = time.time()
        try:
            resp = await self._post_form(
                ENDPOINT_SUBMIT, body=body, cookies=cookies, xsrf=xsrf,
            )
        except CaptchaIncorrectError as exc:
            _log_step(
                agent="submit", case_type=session.case_type,
                case_number=session.case_number, year=session.year,
                http_status=None, elapsed_ms=_ms_since(started),
                cookie_names=tuple(sorted(cookies.keys())),
                outcome="captcha_failed", error=str(exc)[:200],
            )
            raise
        except CourtClientError as exc:
            _log_step(
                agent="submit", case_type=session.case_type,
                case_number=session.case_number, year=session.year,
                http_status=None, elapsed_ms=_ms_since(started),
                cookie_names=tuple(sorted(cookies.keys())),
                outcome="http_error", error=str(exc)[:200],
            )
            raise
        merged = {**cookies, **self._cookies_from_response(resp)}
        self._write_back_session(session, merged, xsrf)
        raw_html = resp.text
        _log_step(
            agent="submit", case_type=session.case_type,
            case_number=session.case_number, year=session.year,
            http_status=resp.status_code, elapsed_ms=_ms_since(started),
            cookie_names=tuple(sorted(merged.keys())),
            outcome="success",
        )
        # Persist the redacted body for parser tuning (BLOCKED-ON-FOUNDER
        # capture path — see backend/app/clients/response_capture.py and
        # docs/DEMO-FEEDBACK.md "Parser returns 'Not available' against
        # real HTML"). Gated by DHC_CAPTURE_REAL_RESPONSES so prod can
        # turn it off without touching code. Failures are swallowed —
        # capture must never break a user search.
        if self._settings.dhc_capture_real_responses:
            capture_real_response(
                raw_html=raw_html,
                case_type=session.case_type,
                case_number=session.case_number,
                year=session.year,
                # Post-2026-05-17 pivot: case-search responses are JSON.
                # Pipe the upstream content-type through so the capture
                # layer picks the right extension (.json vs .html) and we
                # never again save a JSON body as .html (the bug Maya
                # flagged on the captured WPC_2344_2024 fixture).
                content_type=resp.headers.get("content-type"),
            )
        return CaseSearchResult(
            raw_html=raw_html,
            parsed_at_unix=time.time(),
            source_url=str(self._client.base_url.join(ENDPOINT_SUBMIT)),
        )

    async def is_path_allowed_by_robots(self, *, path: str) -> bool:
        """Check robots.txt as a kill switch.

        Recon found /robots.txt returns 404 → "no rules → permitted."
        We fetch once per process (the ``_robots_loaded`` flag flips on
        success OR 404), so a 404 cannot trigger a re-fetch storm. A
        process restart is required to pick up a future robots.txt —
        the right cadence for a kill-switch input.
        """
        if not self._robots_loaded:
            await self._load_robots()
        parser = self._robots_parser
        if parser is None:
            # Empty / missing robots → permissive per project policy.
            return True
        return parser.can_fetch(self._settings.dhc_user_agent, path)

    # ─── Internals ─────────────────────────────────────────────────────

    async def _validate_captcha(
        self,
        *,
        cookies: dict[str, str],
        xsrf: str,
        captcha_text: str,
        case_type: str,
        case_number: str,
        year: int,
    ) -> None:
        """POST the pre-submit captcha validation. Raises on rejection.

        4xx → `CaptchaIncorrectError` (route maps to a 200 captcha_failed,
        NOT a 503 court_error). 5xx → `CourtClientError` (transport).

        B.4 RESOLVED: observed upstream CAPTCHA TTL is >=3 minutes; the
        founder's 2026-05-17 submit landed at ~30s and succeeded. We do
        not enforce a client-side TTL here — the upstream's own 4xx is
        the source of truth and already maps to CaptchaIncorrectError.
        """
        # B.2b RESOLVED: /validateCaptcha body shape confirmed via the
        # real-world submit on 2026-05-17 (see SPIKE-REPORT.md Section G).
        body = {"captcha": captcha_text}
        started = time.time()
        try:
            resp = await self._post_form(
                ENDPOINT_VALIDATE_CAPTCHA, body=body,
                cookies=cookies, xsrf=xsrf, raise_on_4xx=False,
            )
        except CourtClientError as exc:
            _log_step(
                agent="validate", case_type=case_type,
                case_number=case_number, year=year,
                http_status=None, elapsed_ms=_ms_since(started),
                cookie_names=tuple(sorted(cookies.keys())),
                outcome="exception", error=str(exc)[:200],
            )
            raise
        if 400 <= resp.status_code < 500:
            _log_step(
                agent="validate", case_type=case_type,
                case_number=case_number, year=year,
                http_status=resp.status_code,
                elapsed_ms=_ms_since(started),
                cookie_names=tuple(sorted(cookies.keys())),
                outcome="captcha_failed",
            )
            raise CaptchaIncorrectError(
                f"validateCaptcha rejected captcha: status={resp.status_code}"
            )
        if resp.status_code >= 500:
            _log_step(
                agent="validate", case_type=case_type,
                case_number=case_number, year=year,
                http_status=resp.status_code,
                elapsed_ms=_ms_since(started),
                cookie_names=tuple(sorted(cookies.keys())),
                outcome="http_error",
            )
            raise CourtClientError(
                f"validateCaptcha upstream error: status={resp.status_code}"
            )
        _log_step(
            agent="validate", case_type=case_type,
            case_number=case_number, year=year,
            http_status=resp.status_code,
            elapsed_ms=_ms_since(started),
            cookie_names=tuple(sorted(cookies.keys())),
            outcome="success",
        )

    async def _post_form(
        self,
        path: str,
        *,
        body: dict[str, str],
        cookies: dict[str, str],
        xsrf: str,
        raise_on_4xx: bool = True,
    ) -> httpx.Response:
        """POST a form-encoded body with XSRF + cookies wired.

        ``raise_on_4xx=False`` lets the caller translate 4xx into a typed
        exception (e.g. ``CaptchaIncorrectError``) instead of the generic
        transport error.
        """
        headers = {
            "X-XSRF-TOKEN": xsrf,
            "Referer": str(self._client.base_url.join(ENDPOINT_FORM_PAGE)),
            "X-Requested-With": "XMLHttpRequest",
        }
        return await self._request(
            "POST", path, data=body, headers=headers, cookies=cookies,
            raise_on_4xx=raise_on_4xx,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, str]] = None,
        data: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
        cookies: Optional[dict[str, str]] = None,
        raise_on_4xx: bool = True,
    ) -> httpx.Response:
        """Single chokepoint: pacing + SSRF guard + retry + send.

        ``raise_on_4xx=False`` lets the caller translate a 4xx into a
        typed exception (e.g. ``CaptchaIncorrectError``).
        """
        full_url = str(self._client.base_url.join(path))
        self._guard_hostname_allowed(full_url)
        await self._respect_min_spacing()
        # Per-call cookies are sent as an explicit Cookie header (avoids the
        # httpx deprecation around per-request cookies= AND keeps concurrent
        # searches isolated — we never touch the AsyncClient's shared jar).
        final_headers = dict(headers or {})
        if cookies:
            final_headers["Cookie"] = "; ".join(
                f"{k}={v}" for k, v in cookies.items()
            )
        try:
            resp = await self._send_with_retry(
                method=method, path=path, params=params,
                data=data, headers=final_headers,
            )
        except httpx.HTTPError as exc:
            raise CourtClientError(f"Transport error on {method} {path}: {exc}") from exc
        if raise_on_4xx and 400 <= resp.status_code < 500:
            raise CourtClientError(
                f"{method} {path} returned {resp.status_code}"
            )
        # 5xx that survived retry is a transport failure — surface as a
        # typed error so the route layer maps it to `court_error` instead
        # of handing the 500 HTML body to the parser. Callers that need to
        # inspect a 5xx body explicitly can pass `raise_on_4xx=False`
        # (e.g. /validateCaptcha already does its own status mapping).
        # Root cause traced 2026-05-17 from the three /2023 case 500s the
        # founder reported — without this branch, the upstream 500 HTML
        # reaches `DHCParserV1.parse_with_outcome` and can raise an
        # unhandled extraction exception, which falls through to the
        # global 500 handler.
        if raise_on_4xx and resp.status_code >= 500:
            raise CourtClientError(
                f"{method} {path} returned {resp.status_code} after retry"
            )
        return resp

    async def _send_with_retry(
        self,
        *,
        method: str,
        path: str,
        params: Optional[dict[str, str]],
        data: Optional[dict[str, str]],
        headers: Optional[dict[str, str]],
    ) -> httpx.Response:
        """Send the request; retry on 5xx up to MAX_RETRY_ATTEMPTS times.

        Total send count is ``1 + MAX_RETRY_ATTEMPTS``. 4xx is NEVER
        retried — it's a contract error, not a transport blip.
        """
        max_sends = MAX_RETRY_ATTEMPTS + 1
        for attempt in range(1, max_sends + 1):
            resp = await self._client.request(
                method, path, params=params, data=data, headers=headers,
            )
            if resp.status_code < 500 or attempt == max_sends:
                return resp
            backoff = RETRY_BACKOFF_BASE_SECONDS * attempt
            log.warning(
                "dhc.upstream.5xx_retry",
                method=method, path=path, status=resp.status_code,
                backoff_seconds=backoff,
            )
            await asyncio.sleep(backoff)
        return resp  # unreachable; for type-checker

    async def _respect_min_spacing(self) -> None:
        """Sleep so consecutive outbound requests are ≥ MIN_REQUEST_SPACING apart."""
        async with self._pacing_lock:
            now = time.time()
            wait = MIN_REQUEST_SPACING_SECONDS - (now - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.time()

    async def _load_robots(self) -> None:
        """One-shot fetch of /robots.txt; cache the parsed result.

        Always flips ``_robots_loaded=True`` (success, 404, or transport
        error) so subsequent calls skip the network — prevents the
        "permissive-on-404 → re-fetch every call" storm Raj flagged.
        """
        try:
            resp = await self._client.get("/robots.txt")
        except httpx.HTTPError as exc:
            log.warning("dhc.robots.fetch_failed", error=str(exc))
            self._robots_parser = None
            self._robots_loaded = True
            return
        if resp.status_code == 404:
            self._robots_parser = None  # permissive
            self._robots_loaded = True
            return
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(resp.text.splitlines())
        self._robots_parser = parser
        self._robots_fetched_at = time.time()
        self._robots_loaded = True

    def _cookies_for(self, session: CourtSession) -> tuple[dict[str, str], str]:
        """Resolve the cookie jar + XSRF token to use for a request.

        Order of precedence: cookies persisted on the CourtSession (the
        normal path for captcha-refresh and submit), then the in-process
        _pending bridge from a fresh init_session, then empty (which
        will cause the upstream to error — surfaced as CourtClientError).
        """
        if session.cookies:
            xsrf_raw = session.cookies.get(COOKIE_XSRF, "")
            return dict(session.cookies), _decode_xsrf(xsrf_raw)
        key = _pending_key(session.case_type, session.case_number, session.year)
        pending = self._pending.pop(key, None)
        if pending is None:
            return {}, ""
        return dict(pending.cookies), pending.xsrf_token

    def _write_back_session(
        self,
        session: CourtSession,
        cookies: dict[str, str],
        xsrf_decoded: str,
    ) -> None:
        """Persist cookie jar + XSRF token onto the CourtSession."""
        session.cookies.update(cookies)
        if xsrf_decoded:
            session.csrf_tokens["xsrf"] = xsrf_decoded

    @staticmethod
    def _cookies_from_response(resp: httpx.Response) -> dict[str, str]:
        """Extract Set-Cookie pairs from a response into a flat dict."""
        return {name: value for name, value in resp.cookies.items()}

    def _guard_outbound_enabled(self) -> None:
        """Refuse before any outbound byte if the kill switch is off."""
        if not get_flags().outbound_fetch_enabled:
            raise OutboundDisabledError(
                "Outbound fetching is disabled by runtime kill switch"
            )

    def _guard_hostname_allowed(self, url: str) -> None:
        """SSRF guard — only call hosts on DHC_HOSTNAME_ALLOWLIST."""
        host = urlparse(url).hostname or ""
        if host not in self._settings.hostname_allowlist:
            raise CourtBlockedError(
                f"hostname {host!r} not on DHC_HOSTNAME_ALLOWLIST"
            )
