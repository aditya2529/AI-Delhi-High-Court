"""DelhiHCClient — real outbound client to delhihighcourt.nic.in.

CONTRACT:
  Drop-in replacement for `FakeCourtClient`. Subclasses `CourtClient` ABC,
  same method signatures, same exception hierarchy. The route layer should
  never branch on which implementation is wired — `app.services.dependencies`
  is the only place that selects between fake and real (based on
  `Settings.client_mode`).

STATUS:
  STUBBED until Arnav's Phase-0 spike lands (`docs/SPIKE-REPORT.md` +
  `docs/SPIKE-PROTOCOL.md`). The spike must close:
    * ToS + robots.txt review (Sneha G2)
    * Real-fixture capture for the parser (Maya G4)
    * Anti-bot/CAPTCHA shape verification (Arnav)
  Until then, every method raises `NotImplementedError` so any accidental
  use surfaces loudly rather than silently falling back to the fake.

OPS RUNBOOK:
  * Default `CLIENT_MODE=fake`. Production never sets `real` unless the
    spike has signed off AND the kill-switch (`OUTBOUND_FETCH_ENABLED`)
    is verifiably operational.
  * Setting `CLIENT_MODE=real` against this stub emits a loud startup
    WARNING (see `app.services.dependencies.get_court_client`). It is
    NOT a fatal error — the misconfig is only fatal at first use.
"""
from __future__ import annotations

from app.clients.court_client import (
    CaptchaFetchResult,
    CaseSearchResult,
    CourtClient,
)
from app.sessions.store import CourtSession


_STUB_MESSAGE = (
    "DelhiHCClient pending Arnav's Phase-0 spike report. "
    "See docs/SPIKE-REPORT.md and docs/SPIKE-PROTOCOL.md. "
    "Set CLIENT_MODE=fake to use the fixture-driven client."
)


class DelhiHCClient(CourtClient):
    """Real Delhi High Court outbound client. STUB — see module docstring.

    Constructor is intentionally a no-op so dependency wiring doesn't blow
    up at process start; the stub status is signalled by `is_stub` and the
    NotImplementedError raised on first method call.
    """

    is_stub: bool = True

    def __init__(self) -> None:
        """No-op constructor — stubs hold no state.

        Real impl will accept settings (base_url, timeouts, allowlist) and
        construct an `httpx.AsyncClient` with cookie persistence and the
        rate-limit semaphore. Keep that surface settings-driven so tests
        can wire a fake transport without touching the production wiring.
        """

    async def init_session(
        self,
        *,
        case_type: str,
        case_number: str,
        year: int,
    ) -> dict[str, str]:
        """Open an upstream session. STUB — see module docstring."""
        raise NotImplementedError(_STUB_MESSAGE)

    async def fetch_captcha(self, *, session: CourtSession) -> CaptchaFetchResult:
        """Fetch the CAPTCHA image. STUB — see module docstring."""
        raise NotImplementedError(_STUB_MESSAGE)

    async def submit_search(
        self,
        *,
        session: CourtSession,
        captcha_text: str,
    ) -> CaseSearchResult:
        """Submit the form with the user's CAPTCHA. STUB — see module docstring."""
        raise NotImplementedError(_STUB_MESSAGE)

    async def is_path_allowed_by_robots(self, *, path: str) -> bool:
        """Robots.txt allowance check. STUB — see module docstring."""
        raise NotImplementedError(_STUB_MESSAGE)
