"""FakeCourtClient — fixture-driven implementation of CourtClient for MVP.

Why this exists: Sneha's gate G2 (ToS + robots review) is unmet, so we do
NOT touch the real Delhi HC site today. Every read of court HTML and every
CAPTCHA image is synthesised locally, with the same async-shape and same
error envelope the real client will use. This means the rest of the stack
(routes, parser, persistence) is built against a stable contract and the
real `DelhiHCClient` is a drop-in replacement post-spike.

Fake behaviours:
* `init_session()` — no-op metadata; just attaches a synthetic cookie.
* `fetch_captcha()` — draws 5 random alphanumeric chars on a noisy
  200x80 PNG using PIL.
* `submit_search()` — sleeps a realistic 0.3-1.0s, then either:
    - returns `CaptchaIncorrectError` if the user literally typed "WRONG"
    - reads HTML from `parsers/fixtures/sample_responses/` based on the
      (case_type, case_number, year) tuple
    - falls back to NOTFOUND.html for unknown tuples
* `is_path_allowed_by_robots()` — always True (no real robots to check).
"""
from __future__ import annotations

import asyncio
import base64
import io
import random
import re
import string
import time
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from app.clients.court_client import (
    CaptchaFetchResult,
    CaptchaIncorrectError,
    CaseSearchResult,
    CourtClient,
    OutboundDisabledError,
)
from app.runtime_flags import get_flags
from app.sessions.store import CourtSession


# Project-root-relative fixtures path. Resolves to
# D:/Projects/AI Delhi High Court/parsers/fixtures/sample_responses
_FIXTURES_DIR = (
    Path(__file__).resolve().parents[3]
    / "parsers"
    / "fixtures"
    / "sample_responses"
)


def _slugify_case_type(case_type: str) -> str:
    """Map "W.P.(C)" -> "WPC", "CRL.M.C." -> "CRLMC", "FAO" -> "FAO"."""
    return re.sub(r"[^A-Z0-9]", "", case_type.upper())


def _fixture_filename(case_type: str, case_number: str, year: int) -> str:
    """Build the fixture filename from a case tuple."""
    slug = _slugify_case_type(case_type)
    return f"{slug}_{case_number}_{year}.html"


def _resolve_fixture_path(case_type: str, case_number: str, year: int) -> Path:
    """Resolve to a real fixture path; fallback to NOTFOUND for unknown tuples.

    Special routes (for test hooks, documented in the fixtures README):
      * year == 1900 → COURT_ERROR.html (simulates upstream 500)

    The real Delhi HC site returns a "no records found" page for any
    unknown case — we mirror that behaviour here for the default path.
    """
    if year == 1900:
        return _FIXTURES_DIR / "COURT_ERROR.html"
    direct = _FIXTURES_DIR / _fixture_filename(case_type, case_number, year)
    if direct.is_file():
        return direct
    return _FIXTURES_DIR / "NOTFOUND.html"


def _generate_captcha_png(text: str) -> bytes:
    """Render `text` on a 200x80 noisy PNG. Returns raw bytes.

    Uses PIL's default bitmap font — no system font dependency. Adds
    random pixel noise + a few sweeping lines so the image isn't pure
    text. Good enough for a human to read; we don't actually validate
    the answer in `FakeCourtClient`.
    """
    img = Image.new("RGB", (200, 80), color=(245, 245, 245))
    draw = ImageDraw.Draw(img)

    # Noise: ~600 random grey pixels.
    rng = random.Random(text)  # deterministic per-text — easier debugging
    for _ in range(600):
        x = rng.randint(0, 199)
        y = rng.randint(0, 79)
        shade = rng.randint(120, 200)
        draw.point((x, y), fill=(shade, shade, shade))

    # A few sweeping lines.
    for _ in range(4):
        x0, y0 = rng.randint(0, 199), rng.randint(0, 79)
        x1, y1 = rng.randint(0, 199), rng.randint(0, 79)
        draw.line((x0, y0, x1, y1), fill=(170, 170, 170), width=1)

    # Text — large enough to read; jiggled per-character.
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    x = 20
    for ch in text:
        y = 18 + rng.randint(-5, 5)
        draw.text((x, y), ch, fill=(40, 40, 90), font=font)
        x += 32

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _random_captcha_text(n: int = 5) -> str:
    """5-char uppercase alphanumeric, no 0/O/1/I to keep humans happy."""
    alphabet = "".join(
        c for c in (string.ascii_uppercase + string.digits) if c not in "0O1I"
    )
    return "".join(random.choice(alphabet) for _ in range(n))


class FakeCourtClient(CourtClient):
    """Drop-in fake. Never touches the wire."""

    def __init__(self, *, fixtures_dir: Optional[Path] = None) -> None:
        self._fixtures_dir = fixtures_dir or _FIXTURES_DIR

    # ─── CourtClient interface ─────────────────────────────────────────

    async def init_session(
        self,
        *,
        case_type: str,
        case_number: str,
        year: int,
    ) -> dict[str, str]:
        """Synthesise upstream session metadata.

        Returns a cookies-dict-ish payload so the route layer can stash
        whatever it gets without caring about real vs fake.
        """
        self._guard_outbound_enabled()
        await self._fake_latency()
        return {
            "cookie_jsessionid": uuid.uuid4().hex,
            "csrf_token": uuid.uuid4().hex,
            "case_type": case_type,
            "case_number": case_number,
            "year": str(year),
        }

    async def fetch_captcha(self, *, session: CourtSession) -> CaptchaFetchResult:
        """Generate a synthetic CAPTCHA image."""
        self._guard_outbound_enabled()
        await self._fake_latency()
        text = _random_captcha_text()
        png_bytes = _generate_captcha_png(text)
        return CaptchaFetchResult(
            image_bytes=png_bytes,
            image_mime="image/png",
            fetched_at_unix=time.time(),
            # The real client would echo the upstream token here. We stash
            # nothing security-relevant in the fake.
            upstream_token=uuid.uuid4().hex,
        )

    async def submit_search(
        self,
        *,
        session: CourtSession,
        captcha_text: str,
    ) -> CaseSearchResult:
        """Read fixture HTML for the case tuple; respect WRONG sentinel."""
        self._guard_outbound_enabled()
        await self._fake_latency()

        # Sentinel: literal "WRONG" simulates upstream captcha rejection.
        if captcha_text.strip().upper() == "WRONG":
            raise CaptchaIncorrectError(
                "Fake client: simulated 'Invalid Captcha' rejection"
            )

        path = _resolve_fixture_path(
            session.case_type, session.case_number, session.year
        )
        raw_html = path.read_text(encoding="utf-8")
        source_url = (
            f"https://delhihighcourt.nic.in/case-status?"
            f"case_type={session.case_type}&case_number={session.case_number}"
            f"&year={session.year}"
        )
        return CaseSearchResult(
            raw_html=raw_html,
            parsed_at_unix=time.time(),
            source_url=source_url,
        )

    async def is_path_allowed_by_robots(self, *, path: str) -> bool:
        """Always True — there are no robots to check for fake calls."""
        return True

    # ─── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    async def _fake_latency() -> None:
        """0.3-1.0s — keeps the frontend honest about loading states."""
        await asyncio.sleep(random.uniform(0.3, 1.0))

    @staticmethod
    def _guard_outbound_enabled() -> None:
        """Honour Sneha's kill switch even though we never touch the wire.

        Two reasons: (1) preserves the contract so swapping in the real
        client requires zero route changes; (2) lets ops practice the
        kill-switch flow against the safe fake.
        """
        if not get_flags().outbound_fetch_enabled:
            raise OutboundDisabledError(
                "Outbound fetching is disabled by runtime kill switch"
            )


def b64_image(image_bytes: bytes) -> str:
    """Encode raw image bytes to ASCII base64 — for JSON transport."""
    return base64.b64encode(image_bytes).decode("ascii")
