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
        `validate_before_submit=False` (or env DHC_TWO_STEP_SUBMIT=true) to
        skip the explicit validate call if dev recon shows it's optional.
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
    CaseSearchResult,
    CourtBlockedError,
    CourtClient,
    CourtClientError,
    OutboundDisabledError,
)
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

# CAPTCHA freshness placeholder. Real value to be confirmed by dev-with-browser.
# TODO(B.4): confirm CAPTCHA TTL boundary — using 60s placeholder
CAPTCHA_TTL_SECONDS_PLACEHOLDER = 60


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
        self._pending: dict[str, _PendingSession] = {}
        self._last_request_at: float = 0.0
        self._pacing_lock = asyncio.Lock()
        self._robots_parser: Optional[urllib.robotparser.RobotFileParser] = None
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

        resp = await self._request("GET", ENDPOINT_FORM_PAGE)
        cookies = self._cookies_from_response(resp)
        xsrf_raw = cookies.get(COOKIE_XSRF, "")
        if not xsrf_raw:
            raise CourtClientError(
                "Init failed: upstream did not set XSRF-TOKEN cookie"
            )
        pending = _PendingSession(
            cookies=cookies, xsrf_token=_decode_xsrf(xsrf_raw)
        )
        self._pending[_pending_key(case_type, case_number, year)] = pending
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

        Body fields are the reasonable defaults from the form structure
        Arnav captured. The exact upstream field names still need a single
        DevTools session to confirm — see B.2 marker.
        """
        self._guard_outbound_enabled()
        self._guard_hostname_allowed(self._settings.dhc_base_url)

        cookies, xsrf = self._cookies_for(session)
        # TODO(B.2): confirm POST body field names from DevTools session
        body = {
            "case_type": session.case_type,
            "case_number": session.case_number,
            "case_year": str(session.year),
            "captcha": captcha_text,
        }

        if self._validate_before_submit:
            await self._validate_captcha(
                cookies=cookies, xsrf=xsrf, captcha_text=captcha_text,
            )

        resp = await self._post_form(
            ENDPOINT_SUBMIT, body=body, cookies=cookies, xsrf=xsrf,
        )
        merged = {**cookies, **self._cookies_from_response(resp)}
        self._write_back_session(session, merged, xsrf)
        return CaseSearchResult(
            raw_html=resp.text,
            parsed_at_unix=time.time(),
            source_url=str(self._client.base_url.join(ENDPOINT_SUBMIT)),
        )

    async def is_path_allowed_by_robots(self, *, path: str) -> bool:
        """Check robots.txt as a kill switch.

        Recon found /robots.txt returns 404, which under our compliance
        policy means "no rules → access permitted." We still fetch each
        startup (and cache) so a future robots.txt is honoured the moment
        the court publishes one.
        """
        if self._robots_parser is None:
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
    ) -> None:
        """POST the pre-submit captcha validation. Raises on rejection.

        Body field name reuses the placeholder from submit_search (see the
        B.2 TODO there) — both endpoints accept the captcha field under the
        same key per the rendered form structure.
        """
        body = {"captcha": captcha_text}
        resp = await self._post_form(
            ENDPOINT_VALIDATE_CAPTCHA, body=body, cookies=cookies, xsrf=xsrf,
        )
        # Upstream returns JSON {status: bool} per recon — be lenient about
        # exact shape until confirmed in B.2; non-2xx is treated as failure.
        if resp.status_code >= 400:
            raise CourtClientError(
                f"validateCaptcha rejected: status={resp.status_code}"
            )

    async def _post_form(
        self,
        path: str,
        *,
        body: dict[str, str],
        cookies: dict[str, str],
        xsrf: str,
    ) -> httpx.Response:
        """POST a form-encoded body with XSRF + cookies wired."""
        headers = {
            "X-XSRF-TOKEN": xsrf,
            "Referer": str(self._client.base_url.join(ENDPOINT_FORM_PAGE)),
            "X-Requested-With": "XMLHttpRequest",
        }
        return await self._request(
            "POST", path, data=body, headers=headers, cookies=cookies,
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
    ) -> httpx.Response:
        """Single chokepoint: pacing + SSRF guard + retry + send."""
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
        if 400 <= resp.status_code < 500:
            raise CourtClientError(
                f"{method} {path} returned {resp.status_code}"
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
        """Send the request; one retry with exp backoff on 5xx."""
        for attempt in (1, 2):
            resp = await self._client.request(
                method, path, params=params, data=data, headers=headers,
            )
            if resp.status_code < 500 or attempt == 2:
                return resp
            backoff = 1.5 * attempt
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
        """One-shot fetch of /robots.txt; cache the parsed result."""
        try:
            resp = await self._client.get("/robots.txt")
        except httpx.HTTPError as exc:
            log.warning("dhc.robots.fetch_failed", error=str(exc))
            self._robots_parser = None
            return
        if resp.status_code == 404:
            self._robots_parser = None  # permissive
            return
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(resp.text.splitlines())
        self._robots_parser = parser
        self._robots_fetched_at = time.time()

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
