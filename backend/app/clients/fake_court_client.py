"""FakeCourtClient — fixture-driven implementation of CourtClient for MVP.

Why this exists: Sneha's gate G2 (ToS + robots review) is unmet, so we do
NOT touch the real Delhi HC site today. Every read of court HTML and every
CAPTCHA image is synthesised locally, with the same async-shape and same
error envelope the real client will use. This means the rest of the stack
(routes, parser, persistence) is built against a stable contract and the
real `DelhiHCClient` is a drop-in replacement post-spike.

CAPTCHA MODE — dev/prod parity:
  Real Delhi HC serves arithmetic CAPTCHAs (e.g. "17 + 3 ="), NOT
  alphanumeric text. We default to MATH so the dev experience matches
  production and the team never re-builds a flow around a wrong CAPTCHA
  shape. TEXT mode is kept behind a flag (`captcha_mode='text'` kwarg or
  `FAKE_COURT_CAPTCHA_MODE=text` env) as a regression net for the day
  Delhi HC ever adds an alphanumeric option.

Fake behaviours:
* `init_session()` — no-op metadata; just attaches a synthetic cookie.
* `fetch_captcha()` —
    - MATH mode (default): random `a + b` with a,b in [1,50]; rendered on
      a small white PNG. Integer answer is stashed in `upstream_token`
      (which the route layer persists to `session.csrf_tokens["upstream_token"]`).
    - TEXT mode: 5 random alphanumeric chars on a noisy 200x80 PNG.
* `submit_search()` — sleeps a realistic 0.3-1.0s, then either:
    - returns `CaptchaIncorrectError` if the user literally typed "WRONG"
      (case-insensitive sentinel — works in both modes)
    - MATH mode: parses `captcha_text` as int, compares to the answer
      stored on the session. Non-integer or mismatch → CaptchaIncorrectError.
      If no answer is stored (session was built without `fetch_captcha`),
      math validation is skipped — keeps unit-test ergonomics where a
      session is hand-rolled.
    - reads HTML from `parsers/fixtures/sample_responses/` based on the
      (case_type, case_number, year) tuple
    - falls back to NOTFOUND.html for unknown tuples
* `is_path_allowed_by_robots()` — always True (no real robots to check).
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import random
import re
import string
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

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


CaptchaMode = Literal["math", "text"]

# Default CAPTCHA mode matches the real Delhi HC site (arithmetic). TEXT
# mode is opt-in via constructor kwarg or env var.
_DEFAULT_CAPTCHA_MODE: CaptchaMode = "math"
_ENV_CAPTCHA_MODE = "FAKE_COURT_CAPTCHA_MODE"

# Math operand range — sums land in 2-100 (1-3 digit answers), matching
# the real-world observation from the founder's 2026-05-17 test
# ("19 + 3 =" → 22, see docs/DEMO-FEEDBACK.md item #6).
_MATH_OPERAND_MIN = 1
_MATH_OPERAND_MAX = 50

# Real-site CAPTCHA visual style: small white background, dark text. We
# guess at ~180x60px since Maya hasn't pinned the exact dimensions yet.
_MATH_IMAGE_SIZE = (180, 60)


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
    """Build the JSON fixture filename from a case tuple.

    Post-2026-05-17 pivot: case-search responses are JSON, not HTML, so
    the case fixtures live as ``.json`` files. Sentinel HTML pages (the
    Apache/Laravel 500, "No records found", "Invalid Captcha") remain
    ``.html`` because that's the actual shape the upstream serves for
    those error paths.
    """
    slug = _slugify_case_type(case_type)
    return f"{slug}_{case_number}_{year}.json"


def _resolve_fixture_path(case_type: str, case_number: str, year: int) -> Path:
    """Resolve to a real fixture path; fallback to NOTFOUND for unknown tuples.

    Special routes (test hooks, documented in the fixtures README):
      * ``case_number.upper() == 'COURT_ERROR'`` → COURT_ERROR.html
        (simulates upstream 500). Explicit selector by design — the
        previous ``year == 1900`` heuristic coupled the test hook to
        in-band data; explicit sentinel is cleaner.

    The real Delhi HC site returns a "no records found" page for any
    unknown case — we mirror that behaviour here for the default path,
    serving the JSON empty-result envelope (``NOTFOUND.json``) since
    that's what the live DataTables endpoint actually emits. Falls
    back to ``NOTFOUND.html`` if the JSON variant is missing (defensive
    transition support).
    """
    if case_number.upper() == "COURT_ERROR":
        return _FIXTURES_DIR / "COURT_ERROR.html"
    direct = _FIXTURES_DIR / _fixture_filename(case_type, case_number, year)
    if direct.is_file():
        return direct
    not_found_json = _FIXTURES_DIR / "NOTFOUND.json"
    if not_found_json.is_file():
        return not_found_json
    return _FIXTURES_DIR / "NOTFOUND.html"


def _generate_text_captcha_png(text: str) -> bytes:
    """Render `text` on a 200x80 noisy PNG. Returns raw bytes.

    Uses PIL's default bitmap font — no system font dependency. Adds
    random pixel noise + a few sweeping lines so the image isn't pure
    text. Good enough for a human to read; we don't actually validate
    the answer in `FakeCourtClient` text mode.
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


def _generate_math_captcha_png(prompt: str) -> bytes:
    """Render `prompt` (e.g. '17 + 3 =') on a small white PNG.

    Visual style mirrors real-world Delhi HC observation: clean white
    background, dark text, no noise lines. Real-site exact dimensions
    are not yet pinned (Maya bucket); we use ~180x60 as a reasonable
    guess. Fail-soft on system-font absence — fall back to the bitmap.
    """
    width, height = _MATH_IMAGE_SIZE
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    # Centre horizontally; the textbbox API lets us measure first.
    bbox = draw.textbbox((0, 0), prompt, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = max(0, (width - text_w) // 2)
    y = max(0, (height - text_h) // 2 - 4)
    draw.text((x, y), prompt, fill=(30, 30, 30), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _random_captcha_text(n: int = 5) -> str:
    """5-char uppercase alphanumeric, no 0/O/1/I to keep humans happy."""
    alphabet = "".join(
        c for c in (string.ascii_uppercase + string.digits) if c not in "0O1I"
    )
    return "".join(random.choice(alphabet) for _ in range(n))


def _random_math_problem() -> tuple[str, int]:
    """Return (prompt, answer). e.g. ('17 + 3 =', 20).

    Operands are 1..50 so the answer fits the 1-3 digit answer space the
    real site uses. Only addition for now — matches every observed
    real-world sample.
    """
    a = random.randint(_MATH_OPERAND_MIN, _MATH_OPERAND_MAX)
    b = random.randint(_MATH_OPERAND_MIN, _MATH_OPERAND_MAX)
    return f"{a} + {b} =", a + b


def _resolve_captcha_mode(explicit: Optional[CaptchaMode]) -> CaptchaMode:
    """Pick the effective mode: explicit kwarg > env var > default."""
    if explicit is not None:
        return explicit
    raw = os.environ.get(_ENV_CAPTCHA_MODE, "").strip().lower()
    if raw in ("math", "text"):
        return raw  # type: ignore[return-value]
    return _DEFAULT_CAPTCHA_MODE


class FakeCourtClient(CourtClient):
    """Drop-in fake. Never touches the wire."""

    def __init__(
        self,
        *,
        fixtures_dir: Optional[Path] = None,
        captcha_mode: Optional[CaptchaMode] = None,
    ) -> None:
        """Wire fixtures + captcha mode.

        `captcha_mode` overrides the `FAKE_COURT_CAPTCHA_MODE` env var.
        Both are optional; default is `'math'` to match the real Delhi HC
        site. See module docstring for rationale.
        """
        self._fixtures_dir = fixtures_dir or _FIXTURES_DIR
        self._captcha_mode: CaptchaMode = _resolve_captcha_mode(captcha_mode)

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
        """Generate a synthetic CAPTCHA image.

        MATH mode: the integer answer is returned in `upstream_token` so
        the route layer persists it onto `session.csrf_tokens["upstream_token"]`
        and `submit_search` can compare against the user's typed answer.

        TEXT mode: `upstream_token` is an opaque random hex (no
        server-side validation — only the WRONG sentinel matters).
        """
        self._guard_outbound_enabled()
        await self._fake_latency()
        if self._captcha_mode == "math":
            prompt, answer = _random_math_problem()
            png_bytes = _generate_math_captcha_png(prompt)
            # The answer travels through the route layer as
            # CaptchaFetchResult.upstream_token, which gets stored on the
            # persisted session — `submit_search` reads it back from there.
            token = str(answer)
        else:
            text = _random_captcha_text()
            png_bytes = _generate_text_captcha_png(text)
            token = uuid.uuid4().hex
        return CaptchaFetchResult(
            image_bytes=png_bytes,
            image_mime="image/png",
            fetched_at_unix=time.time(),
            upstream_token=token,
        )

    async def submit_search(
        self,
        *,
        session: CourtSession,
        captcha_text: str,
    ) -> CaseSearchResult:
        """Read fixture HTML for the case tuple; validate CAPTCHA per mode."""
        self._guard_outbound_enabled()
        await self._fake_latency()

        # Sentinel: literal "WRONG" simulates upstream captcha rejection.
        # Honoured in BOTH modes — useful for forcing the failure path in
        # integration tests without computing a math answer.
        if captcha_text.strip().upper() == "WRONG":
            raise CaptchaIncorrectError(
                "Fake client: simulated 'Invalid Captcha' rejection"
            )

        if self._captcha_mode == "math":
            self._validate_math_captcha(session=session, captcha_text=captcha_text)

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
    def _validate_math_captcha(*, session: CourtSession, captcha_text: str) -> None:
        """Compare the user's typed integer against the stored answer.

        The stored answer lives on `session.csrf_tokens["upstream_token"]`
        (written by the route layer after `fetch_captcha`). If absent —
        e.g. a unit test that constructs a session directly without a
        prior captcha fetch — we skip validation rather than raise, so
        hand-rolled sessions remain ergonomic. The end-to-end flow always
        populates the field, so the production-shaped path stays honest.

        Non-integer input or numeric mismatch → CaptchaIncorrectError.
        """
        expected_raw = session.csrf_tokens.get("upstream_token", "").strip()
        if not expected_raw:
            return  # no stored answer — see docstring
        try:
            expected = int(expected_raw)
        except ValueError:
            # Stored value isn't a math answer (e.g. text-mode hex from a
            # mode swap). Skip — don't punish the caller for our state.
            return
        try:
            submitted = int(captcha_text.strip())
        except ValueError as exc:
            raise CaptchaIncorrectError(
                "Fake client: math captcha answer must be an integer"
            ) from exc
        if submitted != expected:
            raise CaptchaIncorrectError(
                f"Fake client: math captcha answer {submitted} != {expected}"
            )

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
