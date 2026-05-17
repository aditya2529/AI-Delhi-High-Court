"""Parser fixture replay harness.

Replays the production parser (`DHCParserV1`) against any HTML file on
disk and emits a structured JSON report to stdout. Built for the post-B.6
real-fixture validation pass — when the 20 anonymised pages land under
`parsers/fixtures/real_responses/`, run this harness against each one
BEFORE any `DelhiHCClient` wiring goes live.

What gets reported (per file):
  * All parsed fields (case_type, parties, status, hearings, orders, ...)
  * Confidence score (`parse_confidence`)
  * `parser_degraded` flag (post-spike-tuned: see PARSER_CONFIDENCE_FLOOR)
  * Which parser branch was taken (sentinel classifier vs full extraction
    vs hard-failure / empty_parse fallback)
  * Any warnings / unparsed sections (currently: any field that came back
    None when the cell was present-but-empty in the source HTML)

Usage::

    python scripts/dev/parser_fixture_replay_harness.py \\
        parsers/fixtures/sample_responses/WPC_12345_2024.html

    # Pipe-friendly — one JSON object on stdout, logs on stderr:
    python scripts/dev/parser_fixture_replay_harness.py FIXTURE.html | jq .

    # Override the synthetic identity (defaults are parsed from filename):
    python scripts/dev/parser_fixture_replay_harness.py FIXTURE.html \\
        --case-type 'W.P.(C)' --case-number 12345 --year 2024

Exits non-zero on file-not-found / read errors. A parser hard-failure
(degraded empty_parse) is a NORMAL outcome and exits 0 — that's the whole
point of graceful degradation.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path
from typing import Any

# Make `from app...` resolve regardless of cwd. The harness is intended to
# be invokable from the repo root (`python scripts/dev/harness.py ...`) or
# from inside `scripts/dev/`.
_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[2]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.parsers.case_parser import (  # noqa: E402  -- after sys.path tweak
    PARSE_OUTCOME_CAPTCHA_FAILED,
    PARSE_OUTCOME_COURT_ERROR,
    PARSE_OUTCOME_NOT_FOUND,
    PARSE_OUTCOME_SUCCESS,
    PARSER_CONFIDENCE_FLOOR,
    DHCParserV1,
    ParseOutcome,
)


# Sentinel branch labels emitted in the report. Stable strings so downstream
# tooling can grep / group on them.
BRANCH_SENTINEL_NOT_FOUND = "sentinel:not_found"
BRANCH_SENTINEL_CAPTCHA_FAILED = "sentinel:captcha_failed"
BRANCH_SENTINEL_COURT_ERROR = "sentinel:court_error"
BRANCH_HARD_FAILURE = "extraction:hard_failure_empty_parse"
BRANCH_SUBFLOOR = "extraction:success_subfloor_degraded"
BRANCH_AT_FLOOR = "extraction:success_at_or_above_floor"


# Best-effort filename → identity parser. Matches names like
# `WPC_12345_2024.html`, `CRLMC_999_2023.html`, `FAO_1_2025.html`. Falls back
# to safe placeholders if the file is named anything else.
_FILENAME_RE = re.compile(
    r"^(?P<type>[A-Z]+)_(?P<num>\d+)_(?P<year>\d{4})\.html$",
    re.IGNORECASE,
)


def infer_identity_from_filename(path: Path) -> tuple[str, str, int]:
    """Cheap heuristic so the harness has *something* to populate the
    parser's identity args. Real fixtures should pass `--case-type` etc.
    explicitly — this is a fallback for synthetic naming conventions."""
    m = _FILENAME_RE.match(path.name)
    if m is None:
        return ("UNKNOWN", "0", 0)
    return (m.group("type").upper(), m.group("num"), int(m.group("year")))


def classify_branch(outcome: ParseOutcome) -> str:
    """Map a ParseOutcome onto a stable branch label so the harness output
    groups cleanly across many fixtures."""
    if outcome.outcome == PARSE_OUTCOME_NOT_FOUND:
        return BRANCH_SENTINEL_NOT_FOUND
    if outcome.outcome == PARSE_OUTCOME_CAPTCHA_FAILED:
        return BRANCH_SENTINEL_CAPTCHA_FAILED
    if outcome.outcome == PARSE_OUTCOME_COURT_ERROR:
        return BRANCH_SENTINEL_COURT_ERROR

    assert outcome.outcome == PARSE_OUTCOME_SUCCESS
    case = outcome.case
    if case is None:
        # Should never happen for success — but report defensively.
        return BRANCH_HARD_FAILURE
    if case.parse_confidence == 0.0 and not case.parties:
        # `empty_parse` shape — extraction blew up and fell back.
        return BRANCH_HARD_FAILURE
    if outcome.parser_degraded:
        return BRANCH_SUBFLOOR
    return BRANCH_AT_FLOOR


def collect_warnings(outcome: ParseOutcome, raw_html: str) -> list[str]:
    """Surface parser-internal smells the JSON report should make visible.

    Today: just confidence-floor + hard-failure flags. Add more as real
    fixtures expose new failure modes (e.g. partial parties, missing
    judgments). Keep these strictly *observational* — the harness must
    not fail because of them.
    """
    warns: list[str] = []
    case = outcome.case
    if case is None:
        warns.append("parser returned no ParsedCase (sentinel outcome)")
        return warns

    if outcome.parser_degraded and case.parse_confidence == 0.0:
        warns.append(
            "parser hard-failure: empty_parse fallback "
            "(no case-details table OR no parties extractable)"
        )
    elif outcome.parser_degraded:
        warns.append(
            f"parse_confidence {case.parse_confidence} < "
            f"PARSER_CONFIDENCE_FLOOR {PARSER_CONFIDENCE_FLOOR} "
            "— UI will fall back to source-URL view"
        )

    # Cell-present-but-empty hints. The parser normalises empty strings
    # to None already, so a missing field doesn't tell us *why*. We can
    # still scan the raw HTML cheaply for the canonical empty-cell
    # markers so the report points at the right diagnostic step.
    cell_markers = {
        "status": 'class="case-status"',
        "last_hearing_date": 'class="last-hearing-date"',
        "next_hearing_date": 'class="next-hearing-date"',
        "court_no": 'class="court-no"',
        "judge_bench": 'class="judge-bench"',
    }
    for field, marker in cell_markers.items():
        value = getattr(case, field, None)
        if value is None and marker in raw_html:
            warns.append(
                f"field {field!r}: HTML cell present but extracted value "
                "is None (cell was empty or normalised to None)"
            )

    if not case.orders and "<table class=\"orders\"" in raw_html:
        warns.append("orders table present in HTML but no rows extracted")
    if not case.judgments and "<table class=\"judgments\"" in raw_html:
        warns.append(
            "judgments table present in HTML but no rows extracted"
        )

    return warns


def parsed_case_to_dict(outcome: ParseOutcome) -> dict[str, Any] | None:
    """Convert the dataclass tree to plain JSON-serialisable dicts."""
    case = outcome.case
    if case is None:
        return None
    out = dataclasses.asdict(case)
    return out


def build_report(
    *,
    fixture_path: Path,
    raw_html: str,
    outcome: ParseOutcome,
    case_type: str,
    case_number: str,
    year: int,
) -> dict[str, Any]:
    """Assemble the full JSON report for one fixture."""
    branch = classify_branch(outcome)
    warnings = collect_warnings(outcome, raw_html)

    return {
        "harness_version": "1",
        "fixture": {
            "path": str(fixture_path),
            "name": fixture_path.name,
            "size_bytes": len(raw_html.encode("utf-8", errors="replace")),
        },
        "identity_input": {
            "case_type": case_type,
            "case_number": case_number,
            "year": year,
        },
        "parser_outcome": outcome.outcome,
        "parser_branch": branch,
        "parser_degraded": outcome.parser_degraded,
        "parse_confidence": (
            outcome.case.parse_confidence if outcome.case else None
        ),
        "confidence_floor": PARSER_CONFIDENCE_FLOOR,
        "above_floor": (
            outcome.case.parse_confidence >= PARSER_CONFIDENCE_FLOOR
            if outcome.case
            else False
        ),
        "warnings": warnings,
        "parsed_case": parsed_case_to_dict(outcome),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="parser_fixture_replay_harness.py",
        description=(
            "Run DHCParserV1 against any HTML file and print a structured "
            "JSON report to stdout. See module docstring for the full output "
            "schema."
        ),
    )
    p.add_argument(
        "fixture",
        help="Path to an HTML file (absolute or relative to cwd).",
    )
    p.add_argument(
        "--case-type",
        default=None,
        help=(
            "Override the case_type fed to the parser. Default: inferred "
            "from filename (e.g. WPC_12345_2024.html → 'WPC')."
        ),
    )
    p.add_argument(
        "--case-number",
        default=None,
        help="Override the case_number. Default: inferred from filename.",
    )
    p.add_argument(
        "--year",
        type=int,
        default=None,
        help="Override the year. Default: inferred from filename.",
    )
    p.add_argument(
        "--source-url",
        default="https://delhihighcourt.nic.in/app/get-case-type-status",
        help="source_url to echo back into the ParsedCase. Default: form URL.",
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON report (indent=2). Default: compact.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    fixture_path = Path(args.fixture).resolve()

    if not fixture_path.exists():
        print(f"ERROR: fixture not found: {fixture_path}", file=sys.stderr)
        return 2
    if not fixture_path.is_file():
        print(f"ERROR: not a file: {fixture_path}", file=sys.stderr)
        return 2

    try:
        raw_html = fixture_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"ERROR: could not read {fixture_path}: {e}", file=sys.stderr)
        return 2

    # Identity defaults — best-effort from filename, overrideable on CLI.
    inferred_type, inferred_num, inferred_year = (
        infer_identity_from_filename(fixture_path)
    )
    case_type = args.case_type if args.case_type is not None else inferred_type
    case_number = (
        args.case_number if args.case_number is not None else inferred_num
    )
    year = args.year if args.year is not None else inferred_year

    parser = DHCParserV1()
    outcome = parser.parse_with_outcome(
        raw_html,
        source_url=args.source_url,
        case_type=case_type,
        case_number=case_number,
        year=year,
    )

    report = build_report(
        fixture_path=fixture_path,
        raw_html=raw_html,
        outcome=outcome,
        case_type=case_type,
        case_number=case_number,
        year=year,
    )

    indent = 2 if args.pretty else None
    json.dump(report, sys.stdout, indent=indent, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
