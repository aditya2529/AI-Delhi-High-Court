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

This file is a SKELETON — real selectors require the Phase-0 spike output.
"""
from __future__ import annotations

import abc
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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
        case_id=f"{case_type}-{case_number}-{year}",
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
        parsed_at=datetime.utcnow().isoformat(),
        parse_confidence=0.0,
    )
