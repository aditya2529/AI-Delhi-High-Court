"""Case-result parser — converts the court site's response into ParsedCase JSON.

POST-2026-05-17 PIVOT (B.6 — real-fixture day)
----------------------------------------------
The captured real response from delhihighcourt.nic.in (see
``parsers/fixtures/real_responses/WPC_2344_2024_*.html``, contents are
application/json despite the .html extension) revealed that the Delhi HC
case-search endpoint returns a DataTables-style JSON envelope, NOT the
server-rendered HTML page we built the v1 parser for. The relevant shape::

    {
      "draw": 0,
      "recordsTotal": 1,
      "data": [{
        "ctype":     "<a>W.P.(C)</a> - 2344 / 2024 <br><font color='red'>[DISPOSED]</font>...",
        "cno":       "2344",
        "cyear":     2024,
        "pet":       "SHRUTI KATIYAR<br>VS.&nbsp; <br> REGISTRAR GENERAL, DELHI HIGH COURT...",
        "res":       "REGISTRAR GENERAL, DELHI HIGH COURT",
        "pet_adv":   "HARSH TIKOO",
        "res_adv":   "",
        "status":    "D ",
        "old_h_dt":  "02/04/2024",
        "courtno":   "200",
        "orderdate": "NEXT DATE: NA<br>Last Date: 02/04/2024<br>COURT NO: NA",
        ...
      }],
      "input": {...}
    }

Dual-mode design
~~~~~~~~~~~~~~~~
* JSON is the primary path (live court endpoint). HTML stays as a fallback
  — Delhi HC may serve HTML on other endpoints (e.g. error pages), and
  the existing synthetic-HTML fixtures + tests are still useful regression
  anchors during the transition.
* Mode detection: we sniff the body — first non-whitespace char ``{`` or
  ``[`` ⇒ JSON; otherwise HTML. The client signature isn't changed so
  this is fully internal to the parser. Cheap, robust (court returns
  ``{...}`` with no leading whitespace), and avoids invasive plumbing.
* On total parse failure (either mode) we still return a ParsedCase shell
  with ``raw_html_hash`` + ``source_url`` populated so the UI's
  "open at court site" fallback works.

Field map (JSON mode → ParsedCase, per founder spec)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``case_type``       ← ``data[0].ctype``: strip tags, take portion before " - ".
* ``case_number``     ← ``data[0].cno``.
* ``year``            ← ``data[0].cyear``.
* ``status``          ← merge of ``data[0].status`` (single char, mapped) and
  the bracketed label in ``ctype`` (``[DISPOSED]``/``[PENDING]``). If both
  present and disagree, the bracketed label wins (it's the user-facing one).
* ``last_hearing_date`` ← parse ``orderdate`` for ``Last Date: DD/MM/YYYY``
  → normalised to ISO ``YYYY-MM-DD``.
* ``next_hearing_date`` ← parse ``orderdate`` for ``NEXT DATE: <value>``;
  ``NA`` ⇒ None.
* ``court_no``        ← parse ``orderdate`` for ``COURT NO: <value>``; if
  the parsed value is ``NA`` and ``data[0].courtno`` is non-empty, fall back
  to the structured field but log a warning (orderdate wins on a real conflict).
* ``parties.petitioner`` ← ``data[0].pet`` split on ``VS.`` (note period;
  may be followed by ``&nbsp;``), first half, tags stripped + entities decoded.
* ``parties.respondent`` ← ``data[0].res`` directly (more reliable than
  splitting ``pet`` again).
* ``orders``          ← if ``ctype`` contains an ``<a href>`` to
  ``/app/case-type-status-details/...``, emit a single details link entry.
* ``judgments``       ← same but for ``/app/case-type-status-judgment/...``.

Status code map
~~~~~~~~~~~~~~~
The court uses single-char codes in ``data[0].status``. Today only ``D``
(Disposed) has been observed in real data; ``P``, ``A`` are educated
guesses pending real-fixture confirmation. Unknown codes pass through
verbatim and tag ``parser_degraded`` for that field only (NOT the whole
response — the rest of the record is still useful).
"""
from __future__ import annotations

import abc
import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from app.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class CaseParty:
    name: str
    role: str  # "petitioner" | "respondent" | "intervenor" | "amicus"


@dataclass
class CaseOrder:
    order_date: str   # ISO-8601 date
    title: str
    url: Optional[str]
    kind: str         # "order" | "judgment" | "daily-order" | "details"


@dataclass
class ParsedCase:
    case_id: str
    case_type: str
    case_number: str
    year: int
    status: Optional[str]
    last_hearing_date: Optional[str]
    next_hearing_date: Optional[str]
    court_no: Optional[str]
    judge_bench: Optional[str]
    parties: list[CaseParty] = field(default_factory=list)
    orders: list[CaseOrder] = field(default_factory=list)
    judgments: list[CaseOrder] = field(default_factory=list)
    raw_html_hash: str = ""
    source_url: str = ""
    parsed_at: str = ""
    parser_version: str = "v0.1.0"
    parse_confidence: float = 0.0    # 0.0-1.0; 0 = total failure, 1 = full success


class CaseParser(abc.ABC):
    """Interface — versioned so we can A/B parser implementations during a
    site-layout change."""

    @abc.abstractmethod
    def parse(self, raw_html: str, *, source_url: str) -> ParsedCase: ...


def html_fingerprint(raw_html: str) -> str:
    """SHA-256 of the raw response — used to detect upstream layout changes by
    grouping failures around recurring hashes. Works for both HTML and JSON
    bodies; the name is historical."""
    return hashlib.sha256(raw_html.encode("utf-8", errors="replace")).hexdigest()


def empty_parse(case_type: str, case_number: str, year: int,
                raw_html: str, source_url: str) -> ParsedCase:
    """Total-failure fallback. Frontend renders a graceful 'couldn't read' state."""
    return ParsedCase(
        case_id=f"{case_type}|{case_number}|{year}",
        case_type=case_type,
        case_number=case_number,
        year=year,
        status=None,
        last_hearing_date=None,
        next_hearing_date=None,
        court_no=None,
        judge_bench=None,
        raw_html_hash=html_fingerprint(raw_html),
        source_url=source_url,
        parsed_at=datetime.now(timezone.utc).isoformat(),
        parse_confidence=0.0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Parse outcomes — body-level `status` per API-CONTRACT §3
# ─────────────────────────────────────────────────────────────────────────────

PARSE_OUTCOME_SUCCESS = "success"
PARSE_OUTCOME_NOT_FOUND = "not_found"
PARSE_OUTCOME_COURT_ERROR = "court_error"
PARSE_OUTCOME_CAPTCHA_FAILED = "captcha_failed"


# Minimum `parse_confidence` at which a result is considered safe to render
# as a fully structured ParsedCase. Below this floor, the parser still emits
# a ParsedCase (so the source_url + raw_html_hash flow is intact) but flags
# `parser_degraded=True` so the route layer / frontend can fall back to the
# "couldn't read reliably — open court site" view.
#
# Tuned per Arnav's Phase-0 spike (docs/SPIKE-REPORT.md §C.2). Lowered from
# the original strict-golden-fixture band of 0.70 → 0.55 because:
#   * 0.70 over-rejects fresh-filing pages (no orders/judgments yet) — the
#     exact segment whose lawyers most need updates.
#   * 0.55 demands status OR (last+next-hearing) OR (status + one hearing
#     date), which is the minimum useful case page.
PARSER_CONFIDENCE_FLOOR = 0.55


@dataclass
class ParseOutcome:
    """What the parser returns to the route layer.

    `outcome` maps directly to the API contract's body-level `status`.
    `case` is populated iff outcome == "success" (possibly degraded —
    indicated by `parser_degraded`).
    """

    outcome: str
    case: Optional[ParsedCase]
    parser_degraded: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Status code map — observed-in-real-data vs assumed-from-domain-knowledge
# ─────────────────────────────────────────────────────────────────────────────

# OBSERVED in real captures (as of 2026-05-17):
#   D → Disposed (from real fixture WPC_2344_2024_*, which has status="D ").
#
# ASSUMED (domain-knowledge guess; will confirm once real fixtures cover
# these states). The parser still recognises them so PENDING cases don't
# fall through to the "unknown" branch unnecessarily; if any of these are
# wrong we'll discover the moment a real fixture lands.
STATUS_CODE_MAP: dict[str, str] = {
    "D": "Disposed",       # OBSERVED
    "P": "Pending",        # ASSUMED
    "A": "Adjourned",      # ASSUMED
    "R": "Reserved",       # ASSUMED
    "W": "Withdrawn",      # ASSUMED
    # If you add a row here, document its source (OBSERVED in <fixture> vs
    # ASSUMED <reason>) so we don't silently grow a guess pile.
}

# Bracketed ctype labels are the user-facing status text on the live site
# (e.g. ``<font color='red'>[DISPOSED]</font>``). When both this label and
# the single-char ``status`` field are present and disagree, the bracketed
# label wins because it's what a human would see on the court website.
_CTYPE_STATUS_LABELS: dict[str, str] = {
    "DISPOSED": "Disposed",
    "PENDING": "Pending",
    "ADJOURNED": "Adjourned",
    "RESERVED": "Reserved",
    "WITHDRAWN": "Withdrawn",
    "TRANSFERRED": "Transferred",
    "DISMISSED": "Dismissed",
}


# ─────────────────────────────────────────────────────────────────────────────
# Mode detection
# ─────────────────────────────────────────────────────────────────────────────


def looks_like_json(raw_body: str) -> bool:
    """Sniff: does this body smell like a JSON envelope?

    Cheap structural check — first non-whitespace char is ``{`` or ``[``.
    The live court endpoint returns a JSON object with no leading
    whitespace, so this is both fast and robust. We never have to plumb
    content-type through the client signature, which keeps the parser
    a pure function of its input.

    Returns False on empty/None to keep the HTML branch the safe default.
    """
    if not raw_body:
        return False
    stripped = raw_body.lstrip()
    if not stripped:
        return False
    return stripped[0] in "{["


# ─────────────────────────────────────────────────────────────────────────────
# DHCParserV1 (synthetic-HTML) + DHCParserV2 (real JSON)
# ─────────────────────────────────────────────────────────────────────────────


class DHCParserV1(CaseParser):
    """Dual-mode Delhi HC parser.

    Despite the legacy ``V1`` name (kept so existing imports + the search
    service don't break), this is now the dual-mode entry point:

      * If the raw body sniffs as JSON → ``_parse_json_envelope`` (primary,
        post-2026-05-17 real-shape path).
      * Otherwise → ``_parse_html_legacy`` (synthetic-HTML golden fixtures
        + any HTML-shaped error/sentinel pages the court might still serve).

    ``parser_version`` jumped from ``v1.0.0`` → ``v2.0.0`` to reflect the
    major shape change. Anyone keying cache TTLs / regression triage on
    the version string gets a clean cut-over.

    Sentinel pages (not-found, captcha-failed, court 500, broken) in HTML
    mode are classified by class-name marker or content-text. JSON mode
    treats ``recordsTotal == 0`` or ``data == []`` as a sentinel "no
    records found" (mirrors how the live DataTables endpoint signals an
    empty result).
    """

    # Major bump: shape changed from HTML to JSON-primary.
    # v1.0.0 → v2.0.0 — see docs/SPIKE-REPORT.md §C.4 adjustment rule.
    parser_version: str = "v2.0.0"

    # ── HTML sentinel selectors (legacy path) ────────────────────────────
    _NOT_FOUND_SELECTORS = (".no-records-found", ".alert-info")
    _CAPTCHA_FAILED_PHRASE = "invalid captcha"
    _COURT_ERROR_SELECTORS = (".error-page",)
    _COURT_ERROR_HEADINGS = ("500", "502", "503", "internal server error")

    # ── JSON mode regexes (compiled once at import) ──────────────────────
    # ``ctype``: "<a>W.P.(C)</a> - 2344 / 2024 ..." → "W.P.(C)" before " - ".
    _CTYPE_TYPE_SPLIT = re.compile(r"\s+-\s+")
    # ``orderdate`` field patterns — multiline OK; we strip <br> first.
    _RE_LAST_DATE = re.compile(
        r"Last\s+Date\s*:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE
    )
    _RE_NEXT_DATE = re.compile(
        r"NEXT\s+DATE\s*:\s*([^\n<]+)", re.IGNORECASE
    )
    _RE_COURT_NO = re.compile(
        r"COURT\s+NO\s*:\s*([^\n<]+)", re.IGNORECASE
    )
    # Bracketed status label inside ``ctype``: ``[DISPOSED]``, ``[PENDING]``.
    _RE_BRACKET_STATUS = re.compile(r"\[([A-Z]{4,})\]")
    # ``<a href=...>`` links inside ``ctype`` (no quotes around URL in the
    # real fixture — match a non-space/non-quote run).
    _RE_HREF_DETAILS = re.compile(
        r'href\s*=\s*["\']?(?P<url>[^\s"\'>]*case-type-status-details[^\s"\'>]*)',
        re.IGNORECASE,
    )
    _RE_HREF_JUDGMENT = re.compile(
        r'href\s*=\s*["\']?(?P<url>[^\s"\'>]*case-type-status-judgment[^\s"\'>]*)',
        re.IGNORECASE,
    )
    # ``VS.`` separator between petitioner + respondent in ``pet``. Tolerant
    # of trailing ``&nbsp;`` / whitespace either side.
    _RE_VS_SPLIT = re.compile(r"\bVS\.(?:\s|&nbsp;|\xa0)*", re.IGNORECASE)

    def parse(self, raw_html: str, *, source_url: str) -> ParsedCase:
        """Thin shim — most callers want `parse_with_outcome`."""
        outcome = self.parse_with_outcome(
            raw_html,
            source_url=source_url,
            case_type="",
            case_number="",
            year=0,
        )
        if outcome.case is None:
            return empty_parse("", "", 0, raw_html, source_url)
        return outcome.case

    def parse_with_outcome(
        self,
        raw_html: str,
        *,
        source_url: str,
        case_type: str,
        case_number: str,
        year: int,
    ) -> ParseOutcome:
        """Top-level entry. Sniffs mode + dispatches.

        ``raw_html`` is the historical parameter name — it now accepts
        either an HTML body or a JSON envelope. Renaming the kwarg would
        break the existing call sites in search_service / harness without
        a behavioural reason.
        """
        if looks_like_json(raw_html):
            return self._parse_json_envelope(
                raw_body=raw_html, source_url=source_url,
                case_type=case_type, case_number=case_number, year=year,
            )
        return self._parse_html_legacy(
            raw_html=raw_html, source_url=source_url,
            case_type=case_type, case_number=case_number, year=year,
        )

    # ────────────────────────────────────────────────────────────────────
    # JSON path (primary)
    # ────────────────────────────────────────────────────────────────────

    def _parse_json_envelope(
        self,
        *,
        raw_body: str,
        source_url: str,
        case_type: str,
        case_number: str,
        year: int,
    ) -> ParseOutcome:
        """Parse the DataTables-style JSON envelope.

        Branches:
          * JSON decode error → ``empty_parse`` shell + degraded=True.
          * ``data == []`` or ``recordsTotal == 0`` → ``not_found`` sentinel.
          * Otherwise → extract from ``data[0]``.
        """
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            return self._json_hard_failure(
                raw_body=raw_body, source_url=source_url,
                case_type=case_type, case_number=case_number, year=year,
                reason="json_decode_error",
            )

        if not isinstance(payload, dict):
            return self._json_hard_failure(
                raw_body=raw_body, source_url=source_url,
                case_type=case_type, case_number=case_number, year=year,
                reason="json_root_not_object",
            )

        data = payload.get("data")
        records_total = payload.get("recordsTotal")

        # Empty result → sentinel (mirrors the HTML "No records found" page).
        if (
            records_total == 0
            or data is None
            or (isinstance(data, list) and not data)
        ):
            return ParseOutcome(outcome=PARSE_OUTCOME_NOT_FOUND, case=None)

        if not isinstance(data, list) or not isinstance(data[0], dict):
            return self._json_hard_failure(
                raw_body=raw_body, source_url=source_url,
                case_type=case_type, case_number=case_number, year=year,
                reason="json_data_shape_unexpected",
            )

        try:
            return self._extract_case_from_json(
                row=data[0], raw_body=raw_body, source_url=source_url,
                case_type=case_type, case_number=case_number, year=year,
            )
        except Exception as exc:  # pragma: no cover — defensive
            log.warning(
                "parser.json.extract_failed",
                error=str(exc),
                case_type=case_type, case_number=case_number, year=year,
            )
            return self._json_hard_failure(
                raw_body=raw_body, source_url=source_url,
                case_type=case_type, case_number=case_number, year=year,
                reason="json_extract_exception",
            )

    def _json_hard_failure(
        self,
        *,
        raw_body: str,
        source_url: str,
        case_type: str,
        case_number: str,
        year: int,
        reason: str,
    ) -> ParseOutcome:
        """Build the degraded-shell outcome for JSON-mode total failures.

        Logs the reason so post-mortem triage can group failures by cause
        rather than rediscovering the same edge case repeatedly.
        """
        log.warning(
            "parser.json.hard_failure",
            reason=reason,
            case_type=case_type, case_number=case_number, year=year,
        )
        shell = empty_parse(case_type, case_number, year, raw_body, source_url)
        shell.parser_version = self.parser_version
        return ParseOutcome(
            outcome=PARSE_OUTCOME_SUCCESS,
            case=shell,
            parser_degraded=True,
        )

    def _extract_case_from_json(
        self,
        *,
        row: dict[str, Any],
        raw_body: str,
        source_url: str,
        case_type: str,
        case_number: str,
        year: int,
    ) -> ParseOutcome:
        """Map a single ``data[0]`` row to ParsedCase. Field-by-field."""
        ctype_raw = self._json_str(row, "ctype")
        # Status: prefer the bracketed ctype label (user-facing); fall back
        # to the single-char ``status`` code → STATUS_CODE_MAP.
        status, status_field_degraded = self._extract_status(
            status_raw=self._json_str(row, "status"),
            ctype_raw=ctype_raw,
        )

        # Hearing fields + court_no from the human-formatted ``orderdate``.
        orderdate_raw = self._json_str(row, "orderdate")
        last_hearing = self._extract_last_hearing(orderdate_raw)
        next_hearing = self._extract_next_hearing(orderdate_raw)
        court_no_from_orderdate, orderdate_court_no_marker_present = (
            self._extract_court_no_with_marker(orderdate_raw)
        )
        court_no_structured = self._normalise_na(self._json_str(row, "courtno"))

        # orderdate wins on disagreement (it's user-facing on the site).
        # Three cases:
        #   1) orderdate had a "COURT NO: <real value>" → use it; warn if
        #      structured disagrees.
        #   2) orderdate had "COURT NO: NA" → respect that (site says NA,
        #      we honour it). Falling back to a structured "200" here
        #      would mis-represent what a human sees on the court page.
        #   3) orderdate had NO "COURT NO:" marker at all → fall back to
        #      structured (the human-facing field simply didn't have it).
        if court_no_from_orderdate is not None:
            court_no = court_no_from_orderdate
            if (
                court_no_structured
                and court_no_structured != court_no_from_orderdate
            ):
                log.warning(
                    "parser.json.court_no_conflict",
                    orderdate_value=court_no_from_orderdate,
                    structured_value=court_no_structured,
                    case_type=case_type, case_number=case_number, year=year,
                )
        elif orderdate_court_no_marker_present:
            # Site explicitly says NA — respect it. Don't fall back.
            court_no = None
        else:
            # No marker at all → use structured as a last resort.
            court_no = court_no_structured

        # Parties.
        parties = self._extract_parties(
            pet_raw=self._json_str(row, "pet"),
            res_raw=self._json_str(row, "res"),
        )

        # Orders + judgments from inline ``<a href>`` in ``ctype``.
        orders = self._extract_links(ctype_raw, self._RE_HREF_DETAILS, kind="details")
        judgments = self._extract_links(
            ctype_raw, self._RE_HREF_JUDGMENT, kind="judgment"
        )

        # Identity overrides: trust caller-supplied case_type/number/year
        # over the upstream echo (consistent with the v1 HTML path's
        # docstring — user input is canonical).
        case_type_final = case_type or self._extract_case_type_from_ctype(ctype_raw)
        case_number_final = case_number or self._json_str(row, "cno") or ""
        year_final = year or self._coerce_int(row.get("cyear"))

        confidence = self._compute_confidence_json(
            status=status, last_hearing=last_hearing, next_hearing=next_hearing,
            court_no=court_no, parties=parties,
            has_orders=bool(orders or judgments),
        )

        case = ParsedCase(
            case_id=f"{case_type_final}|{case_number_final}|{year_final}",
            case_type=case_type_final,
            case_number=case_number_final,
            year=year_final,
            status=status,
            last_hearing_date=last_hearing,
            next_hearing_date=next_hearing,
            court_no=court_no,
            judge_bench=None,   # not present in the JSON envelope
            parties=parties,
            orders=orders,
            judgments=judgments,
            raw_html_hash=html_fingerprint(raw_body),
            source_url=source_url,
            parsed_at=datetime.now(timezone.utc).isoformat(),
            parser_version=self.parser_version,
            parse_confidence=confidence,
        )

        # parser_degraded fires only when MOST fields couldn't be mapped, OR
        # when the confidence is below the display floor. A single unknown
        # status code doesn't degrade the whole response.
        _ = status_field_degraded  # currently informational only
        degraded_by_confidence = case.parse_confidence < PARSER_CONFIDENCE_FLOOR
        return ParseOutcome(
            outcome=PARSE_OUTCOME_SUCCESS,
            case=case,
            parser_degraded=degraded_by_confidence,
        )

    # ── JSON-mode field helpers ──────────────────────────────────────────

    @staticmethod
    def _json_str(row: dict[str, Any], key: str) -> str:
        """Read a string-ish field defensively. Numeric values become str;
        None / missing → ''. Keeps every downstream regex/split safe."""
        val = row.get(key)
        if val is None:
            return ""
        return str(val)

    @staticmethod
    def _coerce_int(val: Any) -> int:
        """Best-effort int. Returns 0 on garbage so the schema's int type
        is honoured even on a malformed upstream row."""
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            try:
                return int(val.strip())
            except (ValueError, TypeError):
                return 0
        return 0

    def _extract_case_type_from_ctype(self, ctype: str) -> str:
        """Pull the case_type from a ``ctype`` string. Used only when the
        caller didn't supply one (e.g. legacy ``parse()`` shim)."""
        if not ctype:
            return ""
        cleaned = self._strip_tags_and_entities(ctype)
        # Split on " - " — left side is the type, right side is "<num> / <year>"
        parts = self._CTYPE_TYPE_SPLIT.split(cleaned, maxsplit=1)
        return parts[0].strip() if parts else ""

    def _extract_status(
        self, *, status_raw: str, ctype_raw: str
    ) -> tuple[Optional[str], bool]:
        """Resolve the case status from the two signals available.

        Returns (status_string_or_None, field_degraded_flag).
        Precedence:
          1. Bracketed label inside ``ctype`` (user-facing on the site).
          2. Single-char ``status`` code → STATUS_CODE_MAP.
          3. If single-char code is non-empty but unknown, return it
             verbatim and flag the field as degraded.
        """
        # 1) Bracketed label.
        bracket_status: Optional[str] = None
        if ctype_raw:
            m = self._RE_BRACKET_STATUS.search(ctype_raw)
            if m:
                label = m.group(1).upper()
                bracket_status = _CTYPE_STATUS_LABELS.get(label, label.title())

        # 2) Single-char code.
        code = (status_raw or "").strip().upper()
        code_status: Optional[str] = None
        code_known = False
        if code:
            if code in STATUS_CODE_MAP:
                code_status = STATUS_CODE_MAP[code]
                code_known = True
            else:
                # Unknown code — pass through verbatim, flag degraded.
                code_status = code

        if bracket_status is not None:
            # Bracket wins on conflict (it's what users see on the site).
            return bracket_status, False
        if code_status is not None:
            return code_status, (not code_known)
        return None, False

    def _extract_last_hearing(self, orderdate: str) -> Optional[str]:
        """``Last Date: 02/04/2024`` → ISO ``2024-04-02``. ``NA`` → None."""
        if not orderdate:
            return None
        m = self._RE_LAST_DATE.search(orderdate)
        if not m:
            return None
        return self._dmy_to_iso(m.group(1))

    def _extract_next_hearing(self, orderdate: str) -> Optional[str]:
        """``NEXT DATE: <value>`` → value or None (``NA`` ⇒ None).

        If the value looks like ``DD/MM/YYYY`` we ISO-normalise it; otherwise
        we return the raw value so a textual "TO BE ANNOUNCED" surfaces
        rather than being silently dropped.
        """
        if not orderdate:
            return None
        m = self._RE_NEXT_DATE.search(orderdate)
        if not m:
            return None
        raw = m.group(1).strip()
        cleaned = self._normalise_na(raw)
        if cleaned is None:
            return None
        # Trim trailing HTML noise that the regex's `[^\n<]+` may leave.
        cleaned = cleaned.split("<")[0].strip()
        iso = self._dmy_to_iso(cleaned)
        return iso if iso else cleaned or None

    def _extract_court_no(self, orderdate: str) -> Optional[str]:
        """``COURT NO: <value>`` → value or None (``NA`` ⇒ None).

        Convenience wrapper around ``_extract_court_no_with_marker`` that
        drops the marker-present flag. Used where the caller doesn't need
        to distinguish "NA was said" from "field never mentioned".
        """
        value, _present = self._extract_court_no_with_marker(orderdate)
        return value

    def _extract_court_no_with_marker(
        self, orderdate: str,
    ) -> tuple[Optional[str], bool]:
        """``COURT NO: <value>`` → (value_or_None, marker_was_present).

        Two return components so the caller can distinguish:
          * (None, True)  — site explicitly said COURT NO: NA → honour it.
          * (None, False) — no COURT NO marker at all → fall back is safe.
          * (val,  True)  — real value extracted.
        """
        if not orderdate:
            return None, False
        m = self._RE_COURT_NO.search(orderdate)
        if not m:
            return None, False
        raw = m.group(1).strip().split("<")[0].strip()
        return self._normalise_na(raw), True

    @staticmethod
    def _normalise_na(val: Optional[str]) -> Optional[str]:
        """Map common 'no value' sentinels to None.

        ``NA`` / ``N/A`` / empty / whitespace all collapse. Anything else
        is returned trimmed. We don't lower-case because a real value like
        "200" should round-trip verbatim.
        """
        if val is None:
            return None
        s = val.strip()
        if not s:
            return None
        if s.upper() in ("NA", "N/A", "--", "-"):
            return None
        return s

    @staticmethod
    def _dmy_to_iso(value: str) -> Optional[str]:
        """``DD/MM/YYYY`` → ``YYYY-MM-DD``. Returns None on parse failure
        so the caller can fall back to surfacing the raw string."""
        try:
            dt = datetime.strptime(value.strip(), "%d/%m/%Y")
        except (ValueError, TypeError):
            return None
        return dt.strftime("%Y-%m-%d")

    def _extract_parties(
        self, *, pet_raw: str, res_raw: str
    ) -> list[CaseParty]:
        """Build the parties list from the JSON ``pet`` + ``res`` fields.

        ``pet`` typically holds ``"<PETITIONER><br>VS.&nbsp; <br> <RESPONDENT>"``;
        we split on ``VS.`` and take the LEFT half. Respondent comes from
        the dedicated ``res`` field (cleaner — no splitting heuristics).

        Both halves get tags stripped + entities decoded + whitespace
        collapsed before being emitted.
        """
        parties: list[CaseParty] = []

        # Petitioner — left of "VS." in pet.
        if pet_raw:
            left_half = self._RE_VS_SPLIT.split(pet_raw, maxsplit=1)[0]
            petitioner = self._clean_party_name(left_half)
            if petitioner:
                parties.append(CaseParty(name=petitioner, role="petitioner"))

        # Respondent — direct from res field.
        respondent = self._clean_party_name(res_raw) if res_raw else ""
        if respondent:
            parties.append(CaseParty(name=respondent, role="respondent"))

        return parties

    def _clean_party_name(self, raw: str) -> str:
        """Strip HTML tags, decode entities, collapse whitespace."""
        if not raw:
            return ""
        text = self._strip_tags_and_entities(raw)
        # Collapse any whitespace run (incl. tabs/newlines from the JSON)
        # to a single space, then trim.
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _strip_tags_and_entities(raw: str) -> str:
        """Pull the visible text out of an HTML fragment. Uses BS4 so we
        handle tag soup the same way the legacy HTML parser does."""
        if not raw:
            return ""
        # Run entity-decode FIRST so &nbsp; etc. become real chars before
        # BS4 sees them (BS4 also decodes, but doing it once up front means
        # later regex splits behave consistently).
        decoded = html.unescape(raw)
        soup = BeautifulSoup(decoded, "lxml")
        return soup.get_text(" ", strip=True)

    def _extract_links(
        self, ctype: str, pattern: re.Pattern[str], *, kind: str,
    ) -> list[CaseOrder]:
        """Pull a single representative link out of the ``ctype`` cell.

        The DataTables row's ``ctype`` field embeds clickable links for
        "Click here for Orders" / "Click here for Judgments". We emit one
        ``CaseOrder`` per link found (today: at most one of each).
        """
        if not ctype:
            return []
        out: list[CaseOrder] = []
        for m in pattern.finditer(ctype):
            url = m.group("url").strip().rstrip("'\"")
            if not url:
                continue
            title = (
                "Click here for Orders" if kind == "details"
                else "Click here for Judgments"
            )
            out.append(
                CaseOrder(
                    order_date="",  # not available at the ctype-link level
                    title=title,
                    url=url,
                    kind=kind,
                )
            )
        return out

    @staticmethod
    def _compute_confidence_json(
        *,
        status: Optional[str],
        last_hearing: Optional[str],
        next_hearing: Optional[str],
        court_no: Optional[str],
        parties: list[CaseParty],
        has_orders: bool,
    ) -> float:
        """JSON-mode confidence rubric.

        Mirrors the HTML rubric structure so the PARSER_CONFIDENCE_FLOOR
        constant stays meaningful across both modes:

          * 0.40 base if any parties extracted (identity proxy).
          * +0.10 status
          * +0.05 last_hearing
          * +0.05 next_hearing
          * +0.05 court_no
          * +0.25 orders/judgments link extracted
          * +0.10 small bonus if BOTH petitioner + respondent present
            (the JSON envelope reliably carries both; weight slightly
            higher than the HTML rubric to compensate for "no judge_bench"
            in this shape).
        """
        score = 0.0
        if parties:
            score += 0.40
            if (
                any(p.role == "petitioner" for p in parties)
                and any(p.role == "respondent" for p in parties)
            ):
                score += 0.10
        if status:
            score += 0.10
        if last_hearing:
            score += 0.05
        if next_hearing:
            score += 0.05
        if court_no:
            score += 0.05
        if has_orders:
            score += 0.25
        return round(min(score, 1.0), 2)

    # ────────────────────────────────────────────────────────────────────
    # HTML path (legacy / fallback)
    # ────────────────────────────────────────────────────────────────────

    def _parse_html_legacy(
        self,
        *,
        raw_html: str,
        source_url: str,
        case_type: str,
        case_number: str,
        year: int,
    ) -> ParseOutcome:
        """HTML-shaped responses. Targets the synthetic fixture schema.

        Kept intact from v1 so the existing golden-fixture regression suite
        + any HTML error pages the court might still serve (5xx with an
        Apache/Laravel page) parse correctly.
        """
        soup = BeautifulSoup(raw_html, "lxml")

        sentinel = self._classify_html_sentinel(soup, raw_html)
        if sentinel is not None:
            return ParseOutcome(outcome=sentinel, case=None)

        try:
            case = self._extract_case_from_html(
                soup,
                raw_html=raw_html,
                source_url=source_url,
                case_type=case_type,
                case_number=case_number,
                year=year,
            )
        except _ParserHardFailure:
            degraded = empty_parse(
                case_type, case_number, year, raw_html, source_url
            )
            degraded.parser_version = self.parser_version
            return ParseOutcome(
                outcome=PARSE_OUTCOME_SUCCESS,
                case=degraded,
                parser_degraded=True,
            )

        degraded_by_confidence = case.parse_confidence < PARSER_CONFIDENCE_FLOOR
        return ParseOutcome(
            outcome=PARSE_OUTCOME_SUCCESS,
            case=case,
            parser_degraded=degraded_by_confidence,
        )

    def _classify_html_sentinel(
        self, soup: BeautifulSoup, raw_html: str
    ) -> Optional[str]:
        """Identify HTML sentinel pages. Returns the outcome string or None."""
        for sel in self._NOT_FOUND_SELECTORS:
            node = soup.select_one(sel)
            if node and "no records found" in node.get_text(" ", strip=True).lower():
                return PARSE_OUTCOME_NOT_FOUND

        body_text = soup.get_text(" ", strip=True).lower()
        if self._CAPTCHA_FAILED_PHRASE in body_text:
            return PARSE_OUTCOME_CAPTCHA_FAILED

        for sel in self._COURT_ERROR_SELECTORS:
            if soup.select_one(sel):
                heading = soup.find(["h1", "h2"])
                heading_text = heading.get_text(strip=True).lower() if heading else ""
                if any(m in heading_text for m in self._COURT_ERROR_HEADINGS):
                    return PARSE_OUTCOME_COURT_ERROR
                return PARSE_OUTCOME_COURT_ERROR

        return None

    def _extract_case_from_html(
        self,
        soup: BeautifulSoup,
        *,
        raw_html: str,
        source_url: str,
        case_type: str,
        case_number: str,
        year: int,
    ) -> ParsedCase:
        details = soup.select_one("table.case-details")
        if details is None:
            raise _ParserHardFailure("no case-details table")

        parties = self._extract_html_parties(soup)
        if not parties:
            raise _ParserHardFailure("no parties found")

        status = self._cell_text(details, "td.case-status", "Status")
        last_hearing = self._cell_text(
            details, "td.last-hearing-date", "Last Hearing"
        )
        next_hearing = self._cell_text(
            details, "td.next-hearing-date", "Next Hearing"
        )
        court_no = self._cell_text(details, "td.court-no", "Court No.")
        judge_bench = self._cell_text(details, "td.judge-bench", "Bench")
        orders = self._extract_html_orders(soup)
        judgments = self._extract_html_judgments(soup)

        confidence = self._compute_confidence_html(
            status=status, last_hearing=last_hearing, next_hearing=next_hearing,
            court_no=court_no, judge_bench=judge_bench,
            has_orders=bool(orders or judgments),
        )

        return ParsedCase(
            case_id=f"{case_type}|{case_number}|{year}",
            case_type=case_type, case_number=case_number, year=year,
            status=status,
            last_hearing_date=last_hearing, next_hearing_date=next_hearing,
            court_no=court_no, judge_bench=judge_bench,
            parties=parties, orders=orders, judgments=judgments,
            raw_html_hash=html_fingerprint(raw_html),
            source_url=source_url,
            parsed_at=datetime.now(timezone.utc).isoformat(),
            parser_version=self.parser_version,
            parse_confidence=confidence,
        )

    @staticmethod
    def _compute_confidence_html(
        *,
        status: Optional[str],
        last_hearing: Optional[str],
        next_hearing: Optional[str],
        court_no: Optional[str],
        judge_bench: Optional[str],
        has_orders: bool,
    ) -> float:
        """0.40 base for parties+identity; the rest is optional-field coverage.

        See SPIKE-REPORT §C.2 for the floor-tuning rationale.
        """
        score = 0.40  # parties + identity already present at call time
        if status:
            score += 0.10
        if last_hearing:
            score += 0.05
        if next_hearing:
            score += 0.05
        if court_no:
            score += 0.05
        if judge_bench:
            score += 0.05
        if has_orders:
            score += 0.25
        return round(min(score, 1.0), 2)

    def _cell_text(
        self, scope: Tag, primary_css: str, label: str
    ) -> Optional[str]:
        """Layered extraction:
        1. Primary CSS class selector inside `scope`.
        2. Fallback: <tr> whose <th> text matches `label`, take its <td>.
        Empty string is normalized to None.
        """
        node = scope.select_one(primary_css)
        if node is not None:
            value = node.get_text(strip=True)
            return value or None

        for tr in scope.select("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if (
                isinstance(th, Tag)
                and isinstance(td, Tag)
                and th.get_text(strip=True).lower() == label.lower()
            ):
                value = td.get_text(strip=True)
                return value or None
        return None

    def _extract_html_parties(self, soup: BeautifulSoup) -> list[CaseParty]:
        out: list[CaseParty] = []
        for tr in soup.select("table.parties tr.party"):
            name_node = tr.select_one("td.name")
            if name_node is None:
                continue
            name = name_node.get_text(strip=True)
            if not name:
                continue
            role = self._infer_party_role(tr)
            if role is None:
                continue
            out.append(CaseParty(name=name, role=role))
        return out

    def _infer_party_role(self, tr: Tag) -> Optional[str]:
        classes = {c.lower() for c in tr.get("class", [])}
        if "petitioner" in classes:
            return "petitioner"
        if "respondent" in classes:
            return "respondent"

        role_node = tr.select_one("td.role")
        role_text = role_node.get_text(strip=True).lower() if role_node else ""
        if role_text in {"petitioner", "appellant", "applicant"}:
            return "petitioner"
        if role_text in {"respondent", "opp. party", "opposite party"}:
            return "respondent"
        return None

    def _extract_html_orders(self, soup: BeautifulSoup) -> list[CaseOrder]:
        out: list[CaseOrder] = []
        for tr in soup.select("table.orders tr.order"):
            title_node = tr.select_one("td.order-title")
            date_node = tr.select_one("td.order-date")
            link_node = tr.select_one("td.order-link a[href]")
            title = title_node.get_text(strip=True) if title_node else ""
            if not title:
                continue
            order_date = date_node.get_text(strip=True) if date_node else ""
            url = link_node.get("href") if link_node else None
            out.append(
                CaseOrder(
                    order_date=order_date or "",
                    title=title,
                    url=(url.strip() if isinstance(url, str) else None),
                    kind="order",
                )
            )
        return out

    def _extract_html_judgments(self, soup: BeautifulSoup) -> list[CaseOrder]:
        out: list[CaseOrder] = []
        for tr in soup.select("table.judgments tr.judgment"):
            title_node = tr.select_one("td.judgment-title")
            date_node = tr.select_one("td.judgment-date")
            link_node = tr.select_one("td.judgment-link a[href]")
            title = title_node.get_text(strip=True) if title_node else ""
            if not title:
                continue
            order_date = date_node.get_text(strip=True) if date_node else ""
            url = link_node.get("href") if link_node else None
            out.append(
                CaseOrder(
                    order_date=order_date or "",
                    title=title,
                    url=(url.strip() if isinstance(url, str) else None),
                    kind="judgment",
                )
            )
        return out


class _ParserHardFailure(Exception):
    """Internal: required field couldn't be extracted. Triggers degraded mode."""
