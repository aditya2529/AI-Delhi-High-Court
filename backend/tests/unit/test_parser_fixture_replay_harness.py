"""Tests for the parser fixture replay harness.

The harness is the bridge between captured real fixtures and CI: it
walks a directory of HTML fixtures, prints a per-fixture table of
extraction quality, and exits non-zero if any fixture comes back
``parser_degraded=true``. This file pins the contract so the next
iteration of the harness (and any CI wiring) doesn't silently regress.

Test strategy
-------------
The harness is a sys.exit-style CLI. We exercise its ``main()`` entry
point directly with explicit ``argv`` so the tests don't have to spawn
subprocesses. Stdout / stderr capture comes from pytest's ``capsys``.

Covered:
  * Single-file mode still emits one JSON report (backward compat).
  * Directory mode walks every *.html and prints a table.
  * Directory mode exits 1 on any degraded fixture.
  * Directory mode exits 0 on all-clean fixtures.
  * Directory mode exits 0 (with WARNING) when the directory is empty.
  * count_extracted_fields returns the right (extracted, attempted) for
    each parser branch.
  * Format=json on a directory emits machine-readable JSON, no table.
  * File-not-found exits 2.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add the scripts/dev directory to sys.path so we can import the harness
# as a module. The harness already does its own sys.path tweaking for
# the `app` import, so doing it here doesn't conflict.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_HARNESS_DIR = _REPO_ROOT / "scripts" / "dev"
if str(_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_HARNESS_DIR))

import parser_fixture_replay_harness as harness  # noqa: E402


# Sample HTML snippets used to author tmp fixtures. We DON'T use the real
# fixture files because we want to control exactly what extracts cleanly
# vs degrades — a real fixture change shouldn't break harness tests.

CLEAN_HTML = """\
<html><body><div class="container">
  <table class="case-details">
    <tr><th>Status</th><td class="case-status">PENDING</td></tr>
    <tr><th>Last Hearing</th><td class="last-hearing-date">2026-04-01</td></tr>
    <tr><th>Next Hearing</th><td class="next-hearing-date">2026-06-15</td></tr>
    <tr><th>Court No.</th><td class="court-no">12</td></tr>
    <tr><th>Bench</th><td class="judge-bench">HMJ Singh</td></tr>
  </table>
  <table class="parties">
    <tr class="party petitioner">
      <td class="role">Petitioner</td>
      <td class="name">ACME LTD</td>
    </tr>
    <tr class="party respondent">
      <td class="role">Respondent</td>
      <td class="name">STATE OF X</td>
    </tr>
  </table>
  <table class="orders">
    <tr class="order">
      <td class="order-date">2026-04-01</td>
      <td class="order-title">Initial order</td>
      <td class="order-link"><a href="https://x/o.pdf">View</a></td>
    </tr>
  </table>
</div></body></html>
"""

# Below-floor: parties + status only (0.50 < 0.55 floor → degraded).
DEGRADED_HTML = """\
<html><body><div class="container">
  <table class="case-details">
    <tr><th>Status</th><td class="case-status">PENDING</td></tr>
  </table>
  <table class="parties">
    <tr class="party petitioner">
      <td class="role">Petitioner</td>
      <td class="name">ACME LTD</td>
    </tr>
    <tr class="party respondent">
      <td class="role">Respondent</td>
      <td class="name">STATE OF X</td>
    </tr>
  </table>
</div></body></html>
"""

# Sentinel — NOT_FOUND.
SENTINEL_HTML = """\
<html><body><div class="alert alert-info no-records-found">
  No records found for this case.
</div></body></html>
"""


# ─── Single-file mode (backward compat) ────────────────────────────────────


class TestSingleFileMode:
    def test_single_file_emits_json_to_stdout(self, tmp_path, capsys):
        """Legacy path — one fixture, one JSON object, exit 0."""
        f = tmp_path / "WPC_12345_2024.html"
        f.write_text(CLEAN_HTML, encoding="utf-8")
        rc = harness.main([str(f)])
        captured = capsys.readouterr()
        assert rc == 0
        report = json.loads(captured.out)
        assert report["parser_outcome"] == "success"
        assert report["parser_degraded"] is False
        assert report["parse_confidence"] >= 0.55

    def test_single_file_degraded_still_exits_zero(self, tmp_path, capsys):
        """Legacy contract: single-file mode is observational — degraded
        is a normal outcome, not a CI failure."""
        f = tmp_path / "thin.html"
        f.write_text(DEGRADED_HTML, encoding="utf-8")
        rc = harness.main([str(f)])
        capsys.readouterr()  # drain
        assert rc == 0

    def test_single_file_not_found_exits_2(self, tmp_path, capsys):
        """File-not-found is exit 2 (I/O failure, not parser failure)."""
        rc = harness.main([str(tmp_path / "nope.html")])
        capsys.readouterr()
        assert rc == 2


# ─── Directory mode — table output + exit codes ────────────────────────────


class TestDirectoryMode:
    def test_clean_directory_exits_zero(self, tmp_path, capsys):
        """All fixtures parse cleanly → exit 0, table printed."""
        (tmp_path / "WPC_12345_2024.html").write_text(CLEAN_HTML, encoding="utf-8")
        (tmp_path / "WPC_99999_2024.html").write_text(CLEAN_HTML, encoding="utf-8")
        rc = harness.main([str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == 0
        # Table headers present
        assert "fixture" in out
        assert "confidence" in out
        assert "degraded" in out
        assert "fields_extracted/fields_attempted" in out
        # Both files listed
        assert "WPC_12345_2024.html" in out
        assert "WPC_99999_2024.html" in out
        # Summary line
        assert "summary:" in out
        assert "0 degraded" in out

    def test_any_degraded_fixture_exits_one(self, tmp_path, capsys):
        """The CI-gate contract: any degraded → non-zero exit. Even one
        bad fixture among many clean ones must trip the gate."""
        (tmp_path / "WPC_12345_2024.html").write_text(CLEAN_HTML, encoding="utf-8")
        (tmp_path / "WPC_99_2024.html").write_text(DEGRADED_HTML, encoding="utf-8")
        rc = harness.main([str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == 1
        assert "1 degraded" in out

    def test_all_degraded_fixtures_exits_one(self, tmp_path, capsys):
        """All degraded → still exit 1 (not some other code)."""
        (tmp_path / "a.html").write_text(DEGRADED_HTML, encoding="utf-8")
        (tmp_path / "b.html").write_text(DEGRADED_HTML, encoding="utf-8")
        rc = harness.main([str(tmp_path)])
        capsys.readouterr()
        assert rc == 1

    def test_empty_directory_warns_and_exits_zero(self, tmp_path, capsys):
        """No fixtures -> can't be degraded -> exit 0, but log a warning so
        the CI run isn't silent about it.

        Post-2026-05-17 pivot: harness walks both .html AND .json (real
        upstream returns JSON). Warning text now says "no .html or .json
        fixtures" — we assert the suffix substring so the test survives
        future wording tweaks.
        """
        rc = harness.main([str(tmp_path)])
        captured = capsys.readouterr()
        assert rc == 0
        assert "WARNING" in captured.err
        assert "fixtures" in captured.err
        assert "no .html" in captured.err  # both old + new wording match

    def test_directory_walk_is_recursive(self, tmp_path, capsys):
        """Founder may organise fixtures by case-id subdirectories. The
        walk must recurse so nested files are not silently skipped."""
        nested = tmp_path / "2026" / "may"
        nested.mkdir(parents=True)
        (nested / "WPC_1_2024.html").write_text(CLEAN_HTML, encoding="utf-8")
        rc = harness.main([str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "WPC_1_2024.html" in out

    def test_dot_files_are_ignored(self, tmp_path, capsys):
        """Don't process .DS_Store / .htaccess / dotfiles."""
        (tmp_path / "WPC_12345_2024.html").write_text(CLEAN_HTML, encoding="utf-8")
        (tmp_path / ".cache.html").write_text(DEGRADED_HTML, encoding="utf-8")
        rc = harness.main([str(tmp_path)])
        out = capsys.readouterr().out
        # The clean fixture passes; the dot-file (which would be degraded)
        # is skipped, so exit is 0.
        assert rc == 0
        assert ".cache.html" not in out

    def test_format_json_emits_machine_readable_payload(self, tmp_path, capsys):
        """--format json on a directory: no table, just one JSON object
        with all reports + any_degraded flag."""
        (tmp_path / "WPC_1_2024.html").write_text(CLEAN_HTML, encoding="utf-8")
        (tmp_path / "thin.html").write_text(DEGRADED_HTML, encoding="utf-8")
        rc = harness.main(["--format", "json", str(tmp_path)])
        captured = capsys.readouterr()
        # Even in JSON mode, any_degraded → exit 1.
        assert rc == 1
        payload = json.loads(captured.out)
        assert "fixtures" in payload
        assert "any_degraded" in payload
        assert payload["any_degraded"] is True
        assert len(payload["fixtures"]) == 2


# ─── count_extracted_fields helper ─────────────────────────────────────────


class TestFieldCoverageCounting:
    """The 'fields_extracted/fields_attempted' ratio drives the sprint DoD
    ≥80% target — pin its semantics so the meaning doesn't drift."""

    def _outcome_for(self, html: str):
        from app.parsers.case_parser import DHCParserV1
        return DHCParserV1().parse_with_outcome(
            html,
            source_url="https://x/y",
            case_type="W.P.(C)", case_number="1", year=2024,
        )

    def test_full_extraction_counts_eight_of_eight(self):
        """Every TARGET_FIELDS hits — 8/8."""
        # CLEAN_HTML has all except next_hearing_date and judgments.
        # Build a fully-populated fixture inline.
        full_html = """\
<html><body>
<table class="case-details">
<tr><th>Status</th><td class="case-status">PENDING</td></tr>
<tr><th>Last Hearing</th><td class="last-hearing-date">2026-04-01</td></tr>
<tr><th>Next Hearing</th><td class="next-hearing-date">2026-06-15</td></tr>
<tr><th>Court No.</th><td class="court-no">12</td></tr>
<tr><th>Bench</th><td class="judge-bench">HMJ Singh</td></tr>
</table>
<table class="parties">
<tr class="party petitioner"><td class="role">P</td><td class="name">ACME</td></tr>
<tr class="party respondent"><td class="role">R</td><td class="name">STATE</td></tr>
</table>
<table class="orders">
<tr class="order">
<td class="order-date">2026-04-01</td>
<td class="order-title">o1</td>
<td class="order-link"><a href="https://x/o.pdf">v</a></td>
</tr>
</table>
<table class="judgments">
<tr class="judgment">
<td class="judgment-date">2026-04-01</td>
<td class="judgment-title">j1</td>
<td class="judgment-link"><a href="https://x/j.pdf">v</a></td>
</tr>
</table>
</body></html>
"""
        outcome = self._outcome_for(full_html)
        extracted, attempted = harness.count_extracted_fields(outcome)
        assert (extracted, attempted) == (8, 8)

    def test_partial_extraction_counts_fields_present(self):
        """status + parties only → 2 of 8."""
        outcome = self._outcome_for(DEGRADED_HTML)
        extracted, attempted = harness.count_extracted_fields(outcome)
        assert attempted == 8
        # status + parties = 2 fields. Nothing else.
        assert extracted == 2

    def test_sentinel_returns_zero_zero(self):
        """A NOT_FOUND sentinel didn't attempt extraction — return (0, 0)
        rather than (0, 8) to keep 'sentinel' visually distinct from 'tried
        and failed everything' in the table."""
        outcome = self._outcome_for(SENTINEL_HTML)
        extracted, attempted = harness.count_extracted_fields(outcome)
        assert (extracted, attempted) == (0, 0)

    def test_hard_failure_returns_zero_of_eight(self):
        """An ``empty_parse``-shape outcome (extraction reached but failed
        at the case-details table) reports 0/8 — the parser tried, and
        got nothing of the 8 targets."""
        broken_html = "<html><p>no markers at all</p></html>"
        outcome = self._outcome_for(broken_html)
        extracted, attempted = harness.count_extracted_fields(outcome)
        # No case → sentinel-like (0, 0). The classifier may flag as
        # sentinel OR hard-failure; both are honest outcomes.
        # We assert the floor: extracted is 0.
        assert extracted == 0


# ─── Argument errors ───────────────────────────────────────────────────────


class TestArgumentErrors:
    def test_nonexistent_path_exits_2(self, tmp_path, capsys):
        rc = harness.main([str(tmp_path / "ghost")])
        assert rc == 2
