"""Real-court response capture — write upstream HTML to disk for later replay.

Why this exists
---------------
On 2026-05-17 the founder ran ``CLIENT_MODE=real`` end-to-end against
delhihighcourt.nic.in. The CAPTCHA round-trip worked but the parser
returned ``"Not available"`` for every field with ``parser_degraded=true``,
because the parser had only ever been trained on the synthetic fixtures
under ``parsers/fixtures/sample_responses/``. We needed the raw HTML the
court actually sent back so the parser can be re-pointed at it — and the
HTML response body was NOT being persisted anywhere (``logs/backend/app.log``
was empty; ``outbound.log`` did not exist).

This module fixes the capture gap so the next ``CLIENT_MODE=real`` run by
the founder will leave a fixture in ``parsers/fixtures/real_responses/``
automatically. The team commitment per Sneha's privacy rules + the
GREEN-ZONE rails:

  * Capture is GATED by ``DHC_CAPTURE_REAL_RESPONSES`` (default True in
    dev, recommended False in prod). Off → zero filesystem activity.
  * Capture is only invoked from ``DelhiHCClient`` (the real outbound
    client). The fake client never captures — its bytes are synthetic
    and would pollute the real-fixture bucket.
  * Sensitive bits are redacted before write:
      - IPv4 + IPv6 addresses
      - ``XSRF-TOKEN`` and ``hc_application_session`` cookie values
      - Bearer tokens / Laravel encrypted blobs (any ``eyJ...`` payload
        of plausible length)
      - ``X-XSRF-TOKEN`` header values
    Petitioner / respondent names are public court-published data per
    the Court's own disclaimer (SPIKE-REPORT §A.5) and are kept intact.
  * Capture failures NEVER raise back to the caller — a write error
    must not break the user's search. Logged at WARNING, swallowed.

Filename convention
-------------------
``<safe-case-id>_<unix-epoch-int>.html`` so multiple runs against the
same case_id naturally version (the latest mtime wins for replay).
``safe-case-id`` strips characters that would break Windows paths
(``W.P.(C)|2344|2024`` → ``WPC_2344_2024``).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Final, Optional

from app.utils.logging import get_logger

log = get_logger(__name__)


# ─── Tunables / constants ──────────────────────────────────────────────────

# Public default location. Computed from this file's path so the capture
# survives any cwd shift (tests run from the project root; production
# may run from a Docker WORKDIR).
_THIS = Path(__file__).resolve()
# backend/app/clients/response_capture.py → project root is 3 parents up.
_REPO_ROOT = _THIS.parents[3]
DEFAULT_CAPTURE_DIR: Final[Path] = _REPO_ROOT / "parsers" / "fixtures" / "real_responses"

# Filename-safe case id pattern — strip everything that isn't alnum / underscore.
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9_]+")

# Redaction patterns. Order matters for the long encrypted blobs first
# (otherwise the bearer-token pattern eats a fragment of an XSRF token).
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# IPv6 — match a sequence of 2-4 hex groups separated by `:`, requires
# at least two `:` chars and one hex group ≥ 3 chars to avoid matching
# every `:` in URLs.
_IPV6 = re.compile(r"\b(?:[A-Fa-f0-9]{1,4}:){2,7}[A-Fa-f0-9]{1,4}\b")
# Laravel encrypted blobs / bearer-style JWTs. Min length avoids false
# positives on short base64-ish strings; URL-decoded form `=` becomes `%3D`
# but the encoded blobs in HTML/headers are usually the raw form.
_BEARER_BLOB = re.compile(r"eyJ[A-Za-z0-9_\-+/=%]{64,}")

# Cookie header / Set-Cookie pairs we always scrub. The values can leak
# session identity even when the encoded payload looks innocuous.
_SENSITIVE_COOKIE_NAMES: Final[tuple[str, ...]] = (
    "XSRF-TOKEN",
    "hc_application_session",
)


# ─── Public surface ────────────────────────────────────────────────────────


def safe_case_id_for_filename(
    case_type: str, case_number: str, year: int
) -> str:
    """Map a case tuple to a filename-safe stem.

    Examples:
        ('W.P.(C)', '2344', 2024) → 'WPC_2344_2024'
        ('CRL.M.C.', '999', 2023) → 'CRLMC_999_2023'

    Strips punctuation that's hostile to Windows file paths
    (``.`` / ``(`` / ``)`` / ``|``) so the same fixture name works on
    every dev workstation.
    """
    # Scrub each component independently so all-punctuation inputs don't
    # leave behind ``_``-only stems like ``__0`` that look broken to a
    # human eye. An empty component becomes ``X`` (a deliberate placeholder
    # — never blank; never numeric so it doesn't collide with a real value).
    parts = [
        _FILENAME_UNSAFE.sub("", str(s)) or "X"
        for s in (case_type, case_number, year)
    ]
    cleaned = "_".join(parts)
    # Defensive: a totally degenerate input should still produce a valid stem.
    return cleaned or "UNKNOWN_0_0"


def redact_html(raw_html: str) -> str:
    """Strip session-identifying bits from a raw response body.

    What goes:
      * IPv4 + IPv6 addresses
      * Cookie values for ``XSRF-TOKEN`` and ``hc_application_session``
        (both in ``Cookie:`` strings AND in any embedded JSON snippet)
      * Bearer-style ``eyJ...`` blobs (covers both the encrypted Laravel
        XSRF payload and any JWT-shaped token)
      * ``X-XSRF-TOKEN`` header values

    What stays:
      * Petitioner / respondent names (public court data per the Court's
        own disclaimer; SPIKE-REPORT §A.5)
      * Case numbers, hearing dates, order titles, bench composition
      * Class names, IDs, and structural markup (the whole point — the
        parser needs these intact)

    Idempotent: redacting an already-redacted document returns it unchanged.
    Empty / None-ish input is returned verbatim so the caller never has
    to special-case it.
    """
    if not raw_html:
        return raw_html

    out = raw_html

    # Cookie values first — both name=value pairs and JSON-embedded forms.
    # Pattern matches `NAME=<value>` where <value> is anything up to the
    # next `;`, `"`, whitespace, or end-of-string.
    for name in _SENSITIVE_COOKIE_NAMES:
        # Cookie/Set-Cookie style: NAME=value (terminated by ; or " or whitespace)
        pat = re.compile(
            rf'({re.escape(name)})\s*=\s*([^;"\s,]+)',
        )
        out = pat.sub(rf"\1=REDACTED", out)
        # JSON-embedded: "NAME": "value"
        json_pat = re.compile(
            rf'("{re.escape(name)}"\s*:\s*)"[^"]*"',
        )
        out = json_pat.sub(rf'\1"REDACTED"', out)

    # X-XSRF-TOKEN header values, when echoed into the page (rare but
    # possible in debug surfaces).
    xsrf_header = re.compile(
        r"(X-XSRF-TOKEN\s*:\s*)[^\r\n,;\s]+",
        re.IGNORECASE,
    )
    out = xsrf_header.sub(r"\1REDACTED", out)

    # Bearer-style encrypted blobs anywhere in the body.
    out = _BEARER_BLOB.sub("REDACTED_TOKEN", out)

    # IP addresses last so cookie-value redaction doesn't double-process them.
    out = _IPV4.sub("0.0.0.0", out)
    out = _IPV6.sub("::", out)

    return out


def _extension_for_body(raw_body: str, content_type: Optional[str]) -> str:
    """Pick a file extension that matches the body's actual shape.

    Post-2026-05-17 pivot: the live court case-search endpoint returns
    application/json, NOT HTML. Saving the body as ``.html`` was the
    bug the founder flagged in the 2026-05-17 capture — fixed here by
    inspecting either the upstream content-type header (preferred) or
    sniffing the body (fallback for callers that don't pipe through
    content-type).
    """
    if content_type:
        ct = content_type.split(";", 1)[0].strip().lower()
        if "json" in ct:
            return ".json"
        if "html" in ct or "xml" in ct:
            return ".html"
    # Sniff fallback — JSON envelopes always start with { or [ after lstrip.
    if raw_body and raw_body.lstrip()[:1] in "{[":
        return ".json"
    return ".html"


def capture_real_response(
    *,
    raw_html: str,
    case_type: str,
    case_number: str,
    year: int,
    capture_dir: Optional[Path] = None,
    now_unix: Optional[float] = None,
    content_type: Optional[str] = None,
) -> Optional[Path]:
    """Write the redacted body to disk; return the path written.

    Returns ``None`` if the write failed for any reason (disk full,
    permissions, parent dir creation failed) — capture must never
    propagate an error back to the search flow.

    The caller is responsible for the ``DHC_CAPTURE_REAL_RESPONSES``
    feature-flag check; this function is a pure side-effect with no
    config dependency so it stays unit-testable in isolation.

    Args:
        raw_html: the response body as returned by the upstream. The
            historical name reflects when responses were HTML-only; today
            this may be either HTML or JSON (see ``content_type``).
        case_type / case_number / year: identity for the filename stem.
        capture_dir: override the default location (used by tests + the
            future "capture into a sprint-specific bucket" hook).
        now_unix: override the timestamp (used by tests for determinism).
        content_type: the upstream's ``Content-Type`` response header, if
            available. Drives the file extension (``.json`` for JSON
            responses, ``.html`` for HTML). If absent, the body is sniffed.

    The filename pattern is ``<safe-case-id>_<unix-int>.<ext>``. Multiple
    captures of the same case naturally version by timestamp.
    """
    target_dir = capture_dir if capture_dir is not None else DEFAULT_CAPTURE_DIR
    ts = int(now_unix if now_unix is not None else time.time())
    stem = safe_case_id_for_filename(case_type, case_number, year)
    ext = _extension_for_body(raw_html, content_type)
    target = target_dir / f"{stem}_{ts}{ext}"

    redacted = redact_html(raw_html)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(redacted, encoding="utf-8")
    except OSError as exc:
        # Never fail the user's search because the capture step blew up.
        # WARNING (not ERROR) because no contract is violated.
        log.warning(
            "dhc.capture.write_failed",
            target=str(target),
            error=str(exc),
            case_type=case_type,
            case_number=case_number,
            year=year,
        )
        return None

    log.info(
        "dhc.capture.written",
        target=str(target),
        size_bytes=len(redacted),
        case_type=case_type,
        case_number=case_number,
        year=year,
    )
    return target
