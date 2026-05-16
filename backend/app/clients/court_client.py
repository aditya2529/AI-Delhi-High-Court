"""Outbound HTTP client to the Delhi High Court site.

Design notes (see docs/architecture/STRATEGIES.md):
  * Uses httpx.AsyncClient with cookie persistence per CourtSession
  * Rate-limited at the process level — semaphore + token bucket
  * SSRF guard: every outbound URL host must be in DHC_HOSTNAME_ALLOWLIST
  * Respects robots.txt as a kill switch — if disallowed, raise CourtBlockedError
  * NO model-based CAPTCHA solving. The image is returned to the frontend.

This file is a SKELETON. Real implementation lands in Arjun's sprint.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass


class CourtClientError(Exception):
    """Generic outbound failure (network, 5xx, timeout)."""


class CourtBlockedError(CourtClientError):
    """robots.txt disallowed the path, OR hostname allowlist rejected, OR we
    detected a take-down notice in the response body. Treat as terminal."""


class CaptchaExpiredError(CourtClientError):
    """Upstream said the CAPTCHA token expired before submission."""


class CaptchaIncorrectError(CourtClientError):
    """Upstream rejected the CAPTCHA text — refresh and let the user retry."""


@dataclass
class CaptchaFetchResult:
    image_bytes: bytes
    image_mime: str            # "image/png" | "image/jpeg" | "image/gif"
    fetched_at_unix: float
    upstream_token: str        # whatever CSRF-ish token the form expects


@dataclass
class CaseSearchResult:
    raw_html: str
    parsed_at_unix: float
    source_url: str


class CourtClient(abc.ABC):
    """Interface for outbound calls to the Delhi HC site.

    Two implementations expected:
      * `DelhiHCClient` — real one (Arjun's sprint)
      * `FakeCourtClient` — fixture-driven, for tests and local dev
    """

    @abc.abstractmethod
    async def init_session(self, *, case_type: str, case_number: str, year: int): ...

    @abc.abstractmethod
    async def fetch_captcha(self, *, session) -> CaptchaFetchResult: ...

    @abc.abstractmethod
    async def submit_search(self, *, session, captcha_text: str) -> CaseSearchResult: ...

    @abc.abstractmethod
    async def is_path_allowed_by_robots(self, *, path: str) -> bool: ...
