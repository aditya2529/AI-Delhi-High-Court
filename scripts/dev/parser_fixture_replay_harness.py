"""Parser fixture replay harness.

Replays the production parser (`DHCParserV1`) against an HTML file OR a
directory of HTML files on disk and emits a structured report. Built for
the post-B.6 / post-2026-05-17-demo real-fixture validation pass — when
the founder runs CLIENT_MODE=real and the capture path drops files under
`parsers/fixtures/real_responses/`, this harness runs against every one
of them and reports per-fixture extraction quality.

Two modes, picked automatically by what you pass:

  * **Single file** — emits one JSON object on stdout (legacy behaviour;
    pipe-friendly with `jq`).
  * **Directory** — walks every `*.html` under the directory and prints
    a per-fixture table to stdout (case_id | confidence | degraded |
    fields_extracted/fields_attempted). Exits non-zero if ANY real
    fixture comes back with ``parser_degraded=true`` so this can wire
    into CI as a quality gate.

What gets reported (per file):
  * All parsed fields (case_type, parties, status, hearings, orders, ...)
  * Confidence score (`parse_confidence`)
  * `parser_degraded` flag (post-spike-tuned: see PARSER_CONFIDENCE_FLOOR)
  * Which parser branch was taken (sentinel classifier vs full extraction
    vs hard-failure / empty_parse fallback)
  * Any warnings / unparsed sections (currently: any field that came back
    None when the cell was present-but-empty in the source HTML)
  * For directory mode: a `fields_extracted/fields_attempted` ratio that
    reflects the 8 target fields (status, last_hearing, next_hearing,
    court_no, judge_bench, parties, orders, judgments). Used as the
    extraction-quality score the sprint DoD ties to ≥80%.

Usage::

    # Single file (JSON output, exits 0 even on degraded — legacy).
    python scripts/dev/parser_fixture_replay_harness.py \\
        parsers/fixtures/sample_responses/WPC_12345_2024.html

    # Directory walk (table output, exits non-zero on any degraded — CI).
    python scripts/dev/parser_fixture_replay_harness.py \\
        parsers/fixtures/real_responses/

    # Pipe-friendly — JSON object on stdout, logs on stderr:
    python scripts/dev/parser_fixture_replay_harness.py FIXTURE.html | jq .

    # Override the synthetic identity (defaults are parsed from filename):
    python scripts/dev/parser_fixture_replay_harness.py FIXTURE.html \\
        --case-type 'W.P.(C)' --case-number 12345 --year 2024

    # Force the directory-mode JSON output (machine-readable, no table).
    python scripts/dev/parser_fixture_replay_harness.py \\
        --format json parsers/fixtures/real_responses/

Exit codes:
    0  — success (or single-file degraded; legacy behaviour preserved)
    1  — at least one fixture in directory mode came back parser_degraded=true
    2  — file/dir not found, read error, or other I/O failure
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


# ─── Field-coverage counting (directory-mode table) ──────────────────────

# The 8 target fields that ground the "≥80% clean extraction" sprint DoD.
# Order matches docs/SPIKE-REPORT.md §C.1 + the parser scoring rubric.
# parties/orders/judgments are list-valued — "extracted" means at least one.
TARGET_FIELDS: tuple[str, ...] = (
    "status",
    "last_hearing_date",
    "next_hearing_date",
    "court_no",
    "judge_bench",
    "parties",
    "orders",
    "judgments",
)


def count_extracted_fields(outcome: ParseOutcome) -> tuple[int, int]:
    """Return (extracted, attempted) over TARGET_FIELDS.

    A sentinel page (NOT_FOUND etc.) has nothing to extract — returns (0, 0)
    rather than (0, 8) to avoid making "not found" look like a parser
    failure when it's actually correct upstream behaviour.

    A hard failure (`empty_parse` shape — confidence 0.0, no parties)
    returns (0, len(TARGET_FIELDS)) because the parser TRIED to extract
    and got nothing.
    """
    case = outcome.case
    if case is None:
        # Sentinel — not an extraction attempt.
        return (0, 0)

    extracted = 0
    for field in TARGET_FIELDS:
        value = getattr(case, field, None)
        if isinstance(value, list):
            if value:
                extracted += 1
        elif value not in (None, ""):
            extracted += 1
    return (extracted, len(TARGET_FIELDS))


# ─── Per-fixture report → table row ──────────────────────────────────────


def _table_row_for(report: dict[str, Any], outcome: ParseOutcome) -> dict[str, str]:
    """Distill the JSON report into the 5 columns the table cares about."""
    case = outcome.case
    # ASCII-only placeholders so Windows PowerShell consoles render correctly
    # (the demo punch list flagged Unicode em-dashes as a real Windows bug).
    case_id = case.case_id if case else "(sentinel)"
    confidence = (
        f"{case.parse_confidence:.2f}" if case is not None else "n/a "
    )
    degraded = "yes" if report["parser_degraded"] else "no"
    extracted, attempted = count_extracted_fields(outcome)
    ratio = f"{extracted}/{attempted}" if attempted else "n/a"
    return {
        "fixture": report["fixture"]["name"],
        "case_id": case_id,
        "confidence": confidence,
        "degraded": degraded,
        "fields": ratio,
    }


def _format_table(rows: list[dict[str, str]]) -> str:
    """Render the per-fixture rows as a fixed-width table for the console.

    Stable column ordering: fixture | case_id | confidence | degraded |
    fields_extracted/fields_attempted. Width auto-sizes per column.
    """
    if not rows:
        return "(no fixtures)"

    headers = {
        "fixture": "fixture",
        "case_id": "case_id",
        "confidence": "confidence",
        "degraded": "degraded",
        "fields": "fields_extracted/fields_attempted",
    }
    cols = list(headers.keys())
    widths = {c: max(len(headers[c]), max(len(r[c]) for r in rows)) for c in cols}

    sep = "  "
    out: list[str] = []
    out.append(sep.join(headers[c].ljust(widths[c]) for c in cols))
    out.append(sep.join("-" * widths[c] for c in cols))
    for r in rows:
        out.append(sep.join(r[c].ljust(widths[c]) for c in cols))
    return "\n".join(out)


# ─── Mode dispatch ────────────────────────────────────────────────────────


def _replay_one(
    *,
    fixture_path: Path,
    case_type_override: Optional[str],
    case_number_override: Optional[str],
    year_override: Optional[int],
    source_url: str,
) -> tuple[dict[str, Any], ParseOutcome]:
    """Run the parser on one fixture; return (report, outcome).

    Filename-inferred identity is the default for batch mode (CLI overrides
    are single-file only — a single override couldn't apply sanely to a
    directory of mixed cases anyway).
    """
    raw_html = fixture_path.read_text(encoding="utf-8", errors="replace")
    inferred_type, inferred_num, inferred_year = (
        infer_identity_from_filename(fixture_path)
    )
    case_type = case_type_override if case_type_override is not None else inferred_type
    case_number = (
        case_number_override if case_number_override is not None else inferred_num
    )
    year = year_override if year_override is not None else inferred_year

    parser = DHCParserV1()
    outcome = parser.parse_with_outcome(
        raw_html,
        source_url=source_url,
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
    return report, outcome


def _run_single(args: argparse.Namespace, fixture_path: Path) -> int:
    """Legacy single-file mode — JSON to stdout, exit 0 on degraded."""
    try:
        report, _ = _replay_one(
            fixture_path=fixture_path,
            case_type_override=args.case_type,
            case_number_override=args.case_number,
            year_override=args.year,
            source_url=args.source_url,
        )
    except OSError as e:
        print(f"ERROR: could not read {fixture_path}: {e}", file=sys.stderr)
        return 2

    indent = 2 if args.pretty else None
    json.dump(report, sys.stdout, indent=indent, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    return 0


def _run_directory(args: argparse.Namespace, dir_path: Path) -> int:
    """Walk *.html under dir_path; print table; exit 1 if any degraded.

    Hidden files (.DS_Store etc.) and the README.md are ignored. Sort
    order is alphabetical for stable diff output across runs.
    """
    html_files = sorted(
        p for p in dir_path.rglob("*.html")
        if not p.name.startswith(".") and p.is_file()
    )
    if not html_files:
        print(
            f"WARNING: no .html fixtures under {dir_path} -- "
            "harness has nothing to validate.",
            file=sys.stderr,
        )
        return 0

    rows: list[dict[str, str]] = []
    reports: list[dict[str, Any]] = []
    any_degraded = False
    for f in html_files:
        try:
            report, outcome = _replay_one(
                fixture_path=f,
                case_type_override=None,
                case_number_override=None,
                year_override=None,
                source_url=args.source_url,
            )
        except OSError as e:
            print(f"ERROR: could not read {f}: {e}", file=sys.stderr)
            return 2
        reports.append(report)
        rows.append(_table_row_for(report, outcome))
        if report["parser_degraded"]:
            any_degraded = True

    if args.format == "json":
        json.dump(
            {"fixtures": reports, "any_degraded": any_degraded},
            sys.stdout, indent=2, ensure_ascii=False, default=str,
        )
        sys.stdout.write("\n")
    else:
        print(_format_table(rows))
        print()
        total = len(rows)
        degraded_count = sum(1 for r in rows if r["degraded"] == "yes")
        print(
            f"summary: {total} fixtures, {degraded_count} degraded, "
            f"floor={PARSER_CONFIDENCE_FLOOR}"
        )

    # Non-zero exit on any degraded fixture so this gates a CI step.
    return 1 if any_degraded else 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="parser_fixture_replay_harness.py",
        description=(
            "Run DHCParserV1 against an HTML file OR a directory of HTML "
            "files. File mode → JSON report to stdout. Directory mode → "
            "per-fixture table, non-zero exit on any parser_degraded."
        ),
    )
    p.add_argument(
        "fixture",
        help=(
            "Path to an HTML file OR a directory of HTML files (absolute "
            "or relative to cwd)."
        ),
    )
    p.add_argument(
        "--case-type",
        default=None,
        help=(
            "Override the case_type fed to the parser. SINGLE-FILE only. "
            "Default: inferred from filename (e.g. WPC_12345_2024.html → "
            "'WPC')."
        ),
    )
    p.add_argument(
        "--case-number",
        default=None,
        help="Override the case_number. SINGLE-FILE only. Default: from filename.",
    )
    p.add_argument(
        "--year",
        type=int,
        default=None,
        help="Override the year. SINGLE-FILE only. Default: from filename.",
    )
    p.add_argument(
        "--source-url",
        default="https://delhihighcourt.nic.in/app/get-case-type-status",
        help="source_url to echo back into the ParsedCase. Default: form URL.",
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON in single-file mode (indent=2).",
    )
    p.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help=(
            "Directory-mode output format: 'table' (default; human-readable) "
            "or 'json' (machine-readable). Ignored in single-file mode."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    target = Path(args.fixture).resolve()

    if not target.exists():
        print(f"ERROR: not found: {target}", file=sys.stderr)
        return 2

    if target.is_dir():
        return _run_directory(args, target)
    if target.is_file():
        return _run_single(args, target)
    print(f"ERROR: not a file or directory: {target}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
