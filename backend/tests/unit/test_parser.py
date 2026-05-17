"""Unit tests for the case-result HTML parser.

Pins down the invariants in STRATEGIES.md §3 (Parsing Strategy) and the
tuned floor from SPIKE-REPORT §C.2:
  * Each golden fixture under `parsers/fixtures/sample_responses/` parses
    without raising — graceful degradation is mandatory.
  * `parse_confidence` falls in the right band per fixture
    (high-quality ≥ 0.70; at-or-above floor ≥ PARSER_CONFIDENCE_FLOOR;
    sentinels ≤ 0.20; total failure ≤ 0.10).
  * Results at-or-above PARSER_CONFIDENCE_FLOOR (0.55, post-spike) do NOT
    set parser_degraded; results below it DO. This is the load-bearing
    quality contract the UI keys its fallback view on.
  * `raw_html_hash` and `source_url` are ALWAYS populated, even on failure.
  * Sentinel detection: NOTFOUND.html and CAPTCHA_FAILED.html return
    distinct, parser-identifiable states (so the route layer can branch
    cleanly without re-parsing).
  * `empty_parse` is correctly shaped — frontend never crashes on it.

NOTE on what's testable today:
  The production `DHCParserV1` is Arjun's sprint deliverable; the skeleton
  ships `empty_parse` + `html_fingerprint` only. Tests here assert:
    (a) the helper functions behave (always testable),
    (b) the parser contract — once a `DHCParserV1` class lands, the
        fixture suite below runs against it. The fixture-driven tests are
        marked ``parser_impl_required`` so they ``skip`` cleanly until the
        implementation exists; once Arjun lands ``DHCParserV1`` they go
        green automatically with no test edits.
"""
from __future__ import annotations

import hashlib

import pytest

from app.parsers.case_parser import (
    PARSER_CONFIDENCE_FLOOR,
    ParsedCase,
    empty_parse,
    html_fingerprint,
)


# Try-import the real parser; skip the fixture suite cleanly if absent.
try:
    from app.parsers.case_parser import DHCParserV1  # type: ignore[attr-defined]

    HAS_PARSER_IMPL = True
except Exception:  # pragma: no cover - tested via the skip path
    HAS_PARSER_IMPL = False


parser_impl_required = pytest.mark.skipif(
    not HAS_PARSER_IMPL,
    reason="DHCParserV1 not implemented yet (Arjun's sprint). Once available, "
           "these fixture tests gate every parser change.",
)


# ── Helper functions ──────────────────────────────────────────────────────

class TestHtmlFingerprint:
    def test_fingerprint_is_sha256_hex(self):
        """raw_html_hash must be stable, deterministic, and the right shape."""
        h = html_fingerprint("<html></html>")
        assert len(h) == 64
        int(h, 16)  # parses as hex -> no ValueError

    def test_fingerprint_matches_stdlib_sha256(self):
        """Algorithm must be sha256 (so external tools can verify)."""
        body = "<html><body>x</body></html>"
        expected = hashlib.sha256(body.encode("utf-8")).hexdigest()
        assert html_fingerprint(body) == expected

    def test_fingerprint_handles_non_utf8_bytes_gracefully(self):
        """Adversarial: court HTML might have malformed bytes. Must not crash."""
        # invalid surrogate in source — the fn uses errors="replace"
        body = "\udce2\udc98 broken bytes"
        h = html_fingerprint(body)
        assert len(h) == 64

    def test_fingerprint_is_deterministic_across_calls(self):
        """Same input => same hash. Always."""
        assert html_fingerprint("x") == html_fingerprint("x")
        assert html_fingerprint("x") != html_fingerprint("y")


class TestEmptyParse:
    def test_empty_parse_populates_required_fields(self):
        """S7.1 / AC-1: even total parser failure must give the user a clickable
        source_url + a stable case_id. NEVER raise."""
        pc = empty_parse(
            "W.P.(C)", "12345", 2024,
            raw_html="<html>bad</html>",
            source_url="https://delhihighcourt.nic.in/?id=xyz",
        )
        assert pc.case_type == "W.P.(C)"
        assert pc.case_number == "12345"
        assert pc.year == 2024
        assert pc.source_url.startswith("https://")
        assert len(pc.raw_html_hash) == 64
        assert pc.parse_confidence == 0.0
        assert pc.parties == []
        assert pc.orders == []
        assert pc.judgments == []

    def test_empty_parse_uses_canonical_case_id(self):
        """ParsedCase.case_id format per API-CONTRACT §7.1."""
        pc = empty_parse("FAO", "99999", 2099, "", "https://x/y")
        # The skeleton uses dashes; the contract uses '|'. Either way, the
        # *components* are present and unambiguous. We pin both pieces so a
        # contract drift is caught.
        assert "FAO" in pc.case_id
        assert "99999" in pc.case_id
        assert "2099" in pc.case_id

    def test_empty_parse_parsed_at_is_iso_format(self):
        """parsed_at must be an ISO-8601 string, not a datetime object."""
        pc = empty_parse("LPA", "1", 2024, "x", "https://y")
        assert isinstance(pc.parsed_at, str)
        assert "T" in pc.parsed_at  # ISO format includes the date/time separator


# ── Golden-fixture tests — gated on DHCParserV1 existing ─────────────────

# Confidence bands per STRATEGIES §3 + SPIKE-REPORT §C.2.
# "High-quality" still pins to ≥0.70 because the WPC/CRLMC fixtures load
# every optional field; the *display floor* is lower (0.55) so fresh-filing
# pages with only status + next-hearing still surface to the user.
HIGH_CONFIDENCE_FIXTURES = [
    "WPC_12345_2024.html",
    "CRLMC_999_2023.html",
]
# Fixtures that land at-or-above the floor but below the strict-quality
# band. Sit in the "rendered, NOT degraded" zone the spike lowered for.
AT_FLOOR_FIXTURES = [
    "FAO_1_2025.html",   # no orders, no court_no/bench/last_hearing → ~0.55
]
NO_RESULT_FIXTURES = [
    "NOTFOUND.html",
    "CAPTCHA_FAILED.html",
]
TOTAL_FAILURE_FIXTURES = [
    "BROKEN.html",
    "COURT_ERROR.html",
]


@parser_impl_required
class TestParserAgainstGoldenFixtures:
    @pytest.mark.parametrize("filename", HIGH_CONFIDENCE_FIXTURES)
    def test_high_confidence_fixture_parses_required_fields(
        self, filename, fixture_html
    ):
        """G4 (Exec-Summary): parser hits ≥80% of representative pages.
        High-confidence fixtures must produce all required ParsedCase fields
        AND land safely above the (post-spike-lowered) display floor."""
        html = fixture_html(filename)
        parser = DHCParserV1()
        result = parser.parse(html, source_url="https://delhihighcourt.nic.in/x")

        assert isinstance(result, ParsedCase)
        assert result.parse_confidence >= 0.7, (
            f"{filename}: expected ≥0.7 confidence, got {result.parse_confidence}"
        )
        # Defence-in-depth — high-confidence is by definition well above the
        # floor; if this assert ever inverts, either the fixture has been
        # neutered or the floor logic regressed.
        assert result.parse_confidence >= PARSER_CONFIDENCE_FLOOR
        assert result.parties, "Petitioner/respondent must be parsed"
        assert result.status is not None
        assert len(result.raw_html_hash) == 64
        assert result.source_url

    @pytest.mark.parametrize("filename", AT_FLOOR_FIXTURES)
    def test_fresh_case_fixture_lands_at_or_above_floor(
        self, filename, fixture_html
    ):
        """US-03 AC-2: missing fields render as 'Not available' — fresh
        cases (no orders yet) must still surface to the user.

        Per SPIKE-REPORT §C.2 the floor was lowered 0.70 → 0.55 precisely
        so this fixture (a fresh filing with parties + status + next-hearing)
        renders structured rather than falling back to the source-URL view.
        """
        html = fixture_html(filename)
        parser = DHCParserV1()
        result = parser.parse(html, source_url="https://delhihighcourt.nic.in/x")

        # The headline invariant: at-or-above the floor.
        assert result.parse_confidence >= PARSER_CONFIDENCE_FLOOR, (
            f"{filename}: expected ≥{PARSER_CONFIDENCE_FLOOR} confidence "
            f"(post-spike floor), got {result.parse_confidence}"
        )
        # And below the strict high-quality band — otherwise the fixture
        # has been "improved" to a full case and no longer exercises the
        # at-floor path.
        assert result.parse_confidence < 0.7, (
            f"{filename}: this fixture should sit in the [floor, 0.7) band "
            f"— if it now scores ≥0.7, move it to HIGH_CONFIDENCE_FIXTURES"
        )
        assert result.parties, "Parties must still be extractable on a thin page"

    @pytest.mark.parametrize("filename", NO_RESULT_FIXTURES)
    def test_sentinel_pages_are_detected_distinctly(self, filename, fixture_html):
        """US-04 + US-06: not_found and captcha_failed sentinels must be
        distinguishable so the route layer can map them to body.status correctly."""
        html = fixture_html(filename)
        parser = DHCParserV1()
        result = parser.parse(html, source_url="https://delhihighcourt.nic.in/x")

        # Sentinel pages have no extractable parties; confidence is low but
        # raw_html_hash + source_url are still populated.
        assert result.parse_confidence <= 0.2
        # And sentinels are decisively *below* the display floor so the UI
        # never tries to render them as a structured case.
        assert result.parse_confidence < PARSER_CONFIDENCE_FLOOR
        assert result.raw_html_hash
        assert result.source_url

    @pytest.mark.parametrize("filename", TOTAL_FAILURE_FIXTURES)
    def test_broken_or_error_html_does_not_raise(self, filename, fixture_html):
        """US-07 AC-1: parsing failure must surface gracefully, never raise.
        This is the LOAD-BEARING contract — without it, the user sees a 500."""
        html = fixture_html(filename)
        parser = DHCParserV1()

        # Must NOT raise.
        result = parser.parse(html, source_url="https://delhihighcourt.nic.in/x")

        assert result is not None
        assert result.parse_confidence <= 0.1
        assert len(result.raw_html_hash) == 64
        assert result.source_url

    def test_parser_version_is_emitted(self, fixture_html):
        """STRATEGIES §3: every parsed result carries parser_version for
        cache invalidation + regression triage."""
        html = fixture_html("WPC_12345_2024.html")
        parser = DHCParserV1()
        result = parser.parse(html, source_url="https://delhihighcourt.nic.in/x")
        assert result.parser_version  # truthy; format owned by parser module


# ── PARSER_CONFIDENCE_FLOOR — the constant + the wiring it depends on ────

@parser_impl_required
class TestConfidenceFloorWiring:
    """The floor is the contract between the parser and the UI fallback.
    These tests pin both the constant and the `parser_degraded` flip
    around it.
    """

    def test_floor_is_55_per_spike_section_c2(self):
        """Documented value. If this changes, SPIKE-REPORT §C.2 + the
        constant docstring in case_parser.py must change with it."""
        assert PARSER_CONFIDENCE_FLOOR == 0.55

    def test_high_confidence_fixture_is_not_flagged_degraded(self, fixture_html):
        """A full case page MUST NOT come back degraded. If it does, either
        the floor moved up or the parser scoring regressed."""
        html = fixture_html("WPC_12345_2024.html")
        parser = DHCParserV1()
        outcome = parser.parse_with_outcome(
            html,
            source_url="https://delhihighcourt.nic.in/x",
            case_type="W.P.(C)", case_number="12345", year=2024,
        )
        assert outcome.case is not None
        assert outcome.case.parse_confidence >= PARSER_CONFIDENCE_FLOOR
        assert outcome.parser_degraded is False

    def test_at_floor_fixture_is_not_flagged_degraded(self, fixture_html):
        """The whole point of lowering the floor: FAO_1_2025 (fresh filing,
        ~0.55) must render as a structured case, NOT degraded."""
        html = fixture_html("FAO_1_2025.html")
        parser = DHCParserV1()
        outcome = parser.parse_with_outcome(
            html,
            source_url="https://delhihighcourt.nic.in/x",
            case_type="FAO", case_number="1", year=2025,
        )
        assert outcome.case is not None
        assert outcome.case.parse_confidence >= PARSER_CONFIDENCE_FLOOR
        assert outcome.parser_degraded is False, (
            "FAO_1_2025 is the canonical at-floor fixture — if it now "
            "comes back degraded, either the floor crept up past 0.55 or "
            "the scoring regressed and fresh cases are being hidden."
        )

    def test_confidence_exactly_at_floor_is_not_degraded(self):
        """BOUNDARY: synthetic page that scores EXACTLY 0.55. parser_degraded
        must be False — this proves the comparison in `parse_with_outcome`
        is strict ``<`` and not ``<=``. If someone flips it to ``<=``, this
        test fails and the regression is caught before merge.

        Shape: parties (base 0.40) + status (+0.10) + last_hearing (+0.05)
        = 0.55 exactly. Scoring is exact (not floating-point approximate)
        because the rubric only emits {0.05, 0.10, 0.25} increments and
        the result is rounded to 2 dp in ``_compute_confidence``.
        """
        at_floor_html = """
        <html><body><div class="container">
          <table class="case-details">
            <tr><th>Status</th><td class="case-status">PENDING</td></tr>
            <tr><th>Last Hearing</th><td class="last-hearing-date">2026-04-01</td></tr>
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
        parser = DHCParserV1()
        outcome = parser.parse_with_outcome(
            at_floor_html,
            source_url="https://delhihighcourt.nic.in/x",
            case_type="W.P.(C)", case_number="1", year=2024,
        )
        assert outcome.case is not None
        # The score must land EXACTLY at the floor — proves we're testing
        # the boundary, not just a value above it.
        assert outcome.case.parse_confidence == PARSER_CONFIDENCE_FLOOR, (
            f"Expected exactly {PARSER_CONFIDENCE_FLOOR} (rubric quantises "
            f"to 0.05 steps); got {outcome.case.parse_confidence}. If the "
            f"scoring rubric in _compute_confidence has been retuned, "
            f"reconstruct the at-floor synthetic page to hit the new floor."
        )
        # And the comparison must be strict ``<`` so that *at* the floor is
        # treated as NOT degraded.
        assert outcome.parser_degraded is False, (
            "At PARSER_CONFIDENCE_FLOOR exactly, parser_degraded MUST be False. "
            "If this fails, the floor comparison in parse_with_outcome likely "
            "regressed from ``<`` to ``<=`` — that would hide every fresh "
            "filing that sits precisely at the floor."
        )

    def test_confidence_just_below_floor_is_degraded(self):
        """BOUNDARY: the smallest representable step below the floor. Given
        the rubric quantises to 0.05 increments ({0.05, 0.10, 0.25}) and
        rounds to 2 dp, the nearest representable value below 0.55 is 0.50
        — there is no representable score in (0.50, 0.55). We assert at
        0.50 with a comment so future readers know why we don't probe
        0.5499 directly.

        Shape: parties (base 0.40) + status (+0.10) = 0.50. 0.50 < 0.55
        → degraded. Pair with the exactly-at-floor test above to pin both
        sides of the strict-``<`` inequality.
        """
        below_floor_html = """
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
        parser = DHCParserV1()
        outcome = parser.parse_with_outcome(
            below_floor_html,
            source_url="https://delhihighcourt.nic.in/x",
            case_type="W.P.(C)", case_number="1", year=2024,
        )
        assert outcome.case is not None
        # Exact value: 0.50 is the smallest representable score below 0.55
        # under the current 0.05-step rubric. If the rubric is retuned to
        # finer granularity (e.g. 0.01), tighten this to 0.5499.
        assert outcome.case.parse_confidence == 0.50
        assert outcome.case.parse_confidence < PARSER_CONFIDENCE_FLOOR
        assert outcome.parser_degraded is True, (
            "0.50 is below the 0.55 floor; parser_degraded MUST be True. "
            "If this fails, either the floor was lowered or the comparison "
            "direction inverted — both would silently render unreliable data."
        )

    def test_subfloor_synthetic_page_flips_parser_degraded(self):
        """Adversarial: build a synthetic page that extracts cleanly but
        scores BELOW the floor. parser_degraded must be True so the UI
        falls back to the source-URL link instead of rendering thin data.

        Shape: parties present (base 0.40) + status only (+0.10) = 0.50.
        Nothing else. 0.50 < 0.55 → degraded.
        """
        thin_html = """
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
        parser = DHCParserV1()
        outcome = parser.parse_with_outcome(
            thin_html,
            source_url="https://delhihighcourt.nic.in/x",
            case_type="W.P.(C)", case_number="1", year=2024,
        )
        assert outcome.case is not None
        # The synthetic page is intentionally just below the floor.
        assert outcome.case.parse_confidence < PARSER_CONFIDENCE_FLOOR
        assert outcome.parser_degraded is True

    def test_hard_failure_still_flips_parser_degraded(self, fixture_html):
        """Pre-existing contract: when no parties / no case-details table
        can be extracted at all, parser_degraded MUST be True regardless
        of the score (which will be 0.0 from empty_parse)."""
        html = fixture_html("BROKEN.html")
        parser = DHCParserV1()
        outcome = parser.parse_with_outcome(
            html,
            source_url="https://delhihighcourt.nic.in/x",
            case_type="W.P.(C)", case_number="1", year=2024,
        )
        assert outcome.parser_degraded is True


# ── Defensive: parser is registered as the default ───────────────────────

@parser_impl_required
def test_parser_implements_case_parser_interface():
    """The skeleton ships an abstract CaseParser; the impl must subclass it."""
    from app.parsers.case_parser import CaseParser
    assert issubclass(DHCParserV1, CaseParser)
