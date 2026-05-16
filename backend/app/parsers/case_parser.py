"""Case-result HTML parser — converts the court site's response into ParsedCase JSON.

Design (see docs/architecture/STRATEGIES.md):
  * Layered selectors — CSS preferred over XPath, with at least 2 fallback
    selectors per field. The court HTML *will* change; we need graceful degradation.
  * Golden fixtures under `parsers/fixtures/sample_responses/` — every parser
    version freezes 5+ real-response HTML files. Parser tests run against them
    on every CI build. If a fixture stops matching, we bump parser_version and
    mark the regression in the DB.
  * On total parse failure: return ParsedCase with raw_html_hash + source_url
    populated, all other fields None. Frontend renders "We couldn't read the
    court's response — open it on the court site directly: [link]".

`DHCParserV1` targets the synthetic fixture schema documented at the top of
that class. The real Delhi HC parser will follow the same shape with adapted
selectors after the Phase-0 spike.
"""
from __future__ import annotations

import abc
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup, Tag


@dataclass
class CaseParty:
    name: str
    role: str  # "petitioner" | "respondent" | "intervenor" | "amicus"


@dataclass
class CaseOrder:
    order_date: str   # ISO-8601 date
    title: str
    url: Optional[str]
    kind: str         # "order" | "judgment" | "daily-order"


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
    site-layout change. Default impl: ``DHCParserV1`` (Arjun's sprint)."""

    @abc.abstractmethod
    def parse(self, raw_html: str, *, source_url: str) -> ParsedCase: ...


def html_fingerprint(raw_html: str) -> str:
    """SHA-256 of the raw HTML — used to detect upstream layout changes by
    grouping failures around recurring hashes."""
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
# DHCParserV1 — synthetic-fixture targeting parser
# ─────────────────────────────────────────────────────────────────────────────

class DHCParserV1(CaseParser):
    """First-cut Delhi HC parser. Targets the synthetic fixture schema in
    `parsers/fixtures/sample_responses/`:

        <div class="container">
          <table class="case-details">
            <tr><th>Case Type</th><td class="case-type">...</td></tr>
            <tr><th>Status</th><td class="case-status">...</td></tr>
            <tr><th>Last Hearing</th><td class="last-hearing-date">YYYY-MM-DD</td></tr>
            <tr><th>Next Hearing</th><td class="next-hearing-date">YYYY-MM-DD</td></tr>
            <tr><th>Court No.</th><td class="court-no">12</td></tr>
            <tr><th>Bench</th><td class="judge-bench">...</td></tr>
          </table>
          <table class="parties">
            <tr class="party petitioner"><td class="role">Petitioner</td><td class="name">...</td></tr>
            <tr class="party respondent">...</tr>
          </table>
          <table class="orders">
            <tr class="order">
              <td class="order-date">YYYY-MM-DD</td>
              <td class="order-title">...</td>
              <td class="order-link"><a href="...">View Order</a></td>
            </tr>
          </table>
          <table class="judgments">
            <tr class="judgment">
              <td class="judgment-date">...</td>
              <td class="judgment-title">...</td>
              <td class="judgment-link"><a href="...">View Judgment</a></td>
            </tr>
          </table>
        </div>

    Sentinel pages (not-found, captcha-failed, court 500, broken) are
    classified by class-name marker or content-text. Each field has a
    primary selector + a text-label fallback inside `case-details`.
    """

    parser_version: str = "v1.0.0"

    # Sentinel selectors / phrases. Order matters: more specific first.
    _NOT_FOUND_SELECTORS = (".no-records-found", ".alert-info")
    _CAPTCHA_FAILED_PHRASE = "invalid captcha"
    _COURT_ERROR_SELECTORS = (".error-page",)
    _COURT_ERROR_HEADINGS = ("500", "502", "503", "internal server error")

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
        """Parse the upstream result HTML, classify into one of:
        success / not_found / court_error / captcha_failed.

        We pass `case_type/number/year` so the user's input is the
        canonical identity, not whatever the page echoes back (which
        we should not trust over user input).
        """
        soup = BeautifulSoup(raw_html, "lxml")

        sentinel = self._classify_sentinel(soup, raw_html)
        if sentinel is not None:
            return ParseOutcome(outcome=sentinel, case=None)

        try:
            case = self._extract_case(
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
        return ParseOutcome(outcome=PARSE_OUTCOME_SUCCESS, case=case)

    # ─── classifiers ──────────────────────────────────────────────────

    def _classify_sentinel(
        self, soup: BeautifulSoup, raw_html: str
    ) -> Optional[str]:
        """Identify sentinel pages. Returns the outcome string or None
        if this looks like a real case page."""
        # "Not found" — most common upstream outcome.
        for sel in self._NOT_FOUND_SELECTORS:
            node = soup.select_one(sel)
            if node and "no records found" in node.get_text(" ", strip=True).lower():
                return PARSE_OUTCOME_NOT_FOUND

        # "Invalid Captcha".
        body_text = soup.get_text(" ", strip=True).lower()
        if self._CAPTCHA_FAILED_PHRASE in body_text:
            return PARSE_OUTCOME_CAPTCHA_FAILED

        # Court 5xx / generic error page.
        for sel in self._COURT_ERROR_SELECTORS:
            if soup.select_one(sel):
                heading = soup.find(["h1", "h2"])
                heading_text = heading.get_text(strip=True).lower() if heading else ""
                if any(m in heading_text for m in self._COURT_ERROR_HEADINGS):
                    return PARSE_OUTCOME_COURT_ERROR
                return PARSE_OUTCOME_COURT_ERROR

        return None

    # ─── extraction ───────────────────────────────────────────────────

    def _extract_case(
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
            # No case-details table at all → likely the BROKEN fixture.
            raise _ParserHardFailure("no case-details table")

        parties = self._extract_parties(soup)
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
        orders = self._extract_orders(soup)
        judgments = self._extract_judgments(soup)

        confidence = self._compute_confidence(
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
    def _compute_confidence(
        *,
        status: Optional[str],
        last_hearing: Optional[str],
        next_hearing: Optional[str],
        court_no: Optional[str],
        judge_bench: Optional[str],
        has_orders: bool,
    ) -> float:
        """0.5 base for parties+identity; the rest is optional-field coverage.

        A case page with status + (last|next) hearing + bench + orders lands
        at ≥0.7 (the band our golden-fixture tests demand for high quality).
        A fresh case with only parties + maybe a status + next-hearing lands
        in the 0.4-0.6 mid-band (degraded).
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

    def _extract_parties(self, soup: BeautifulSoup) -> list[CaseParty]:
        """Read <table.parties> rows.

        Class-based row selectors (`tr.party.petitioner|.respondent`) are
        primary; we also accept the `role` cell text as a fallback so
        appellant/respondent variants don't break us.
        """
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
        """Map CSS class or role-cell text to one of (petitioner, respondent)."""
        classes = {c.lower() for c in tr.get("class", [])}
        if "petitioner" in classes:
            return "petitioner"
        if "respondent" in classes:
            return "respondent"

        role_node = tr.select_one("td.role")
        role_text = role_node.get_text(strip=True).lower() if role_node else ""
        # Synonyms — Appellants are petitioners in our normalised vocab.
        if role_text in {"petitioner", "appellant", "applicant"}:
            return "petitioner"
        if role_text in {"respondent", "opp. party", "opposite party"}:
            return "respondent"
        return None

    def _extract_orders(self, soup: BeautifulSoup) -> list[CaseOrder]:
        """Parse <table.orders tr.order>. Empty rows / 'No orders' rows
        are filtered out by the class selector itself."""
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

    def _extract_judgments(self, soup: BeautifulSoup) -> list[CaseOrder]:
        """Same shape as orders, different selectors."""
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
