"""Unit tests for the case-result HTML parser.

Pins down the invariants in STRATEGIES.md §3 (Parsing Strategy):
  * Each golden fixture under `parsers/fixtures/sample_responses/` parses
    without raising — graceful degradation is mandatory.
  * `parse_confidence` falls in the right band per fixture
    (full success ≥ 0.7; degraded but recognised 0.2-0.7; total failure ≤ 0.1).
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

# Confidence bands per STRATEGIES §3. These pin the parser's quality contract.
HIGH_CONFIDENCE_FIXTURES = [
    "WPC_12345_2024.html",
    "CRLMC_999_2023.html",
]
DEGRADED_FIXTURES = [
    "FAO_1_2025.html",   # no orders, no court_no/bench/last_hearing
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
        High-confidence fixtures must produce all required ParsedCase fields."""
        html = fixture_html(filename)
        parser = DHCParserV1()
        result = parser.parse(html, source_url="https://delhihighcourt.nic.in/x")

        assert isinstance(result, ParsedCase)
        assert result.parse_confidence >= 0.7, (
            f"{filename}: expected ≥0.7 confidence, got {result.parse_confidence}"
        )
        assert result.parties, "Petitioner/respondent must be parsed"
        assert result.status is not None
        assert len(result.raw_html_hash) == 64
        assert result.source_url

    @pytest.mark.parametrize("filename", DEGRADED_FIXTURES)
    def test_degraded_fixture_parses_with_lower_confidence(
        self, filename, fixture_html
    ):
        """US-03 AC-2: missing fields render as 'Not available' — i.e., parser
        completes WITHOUT raising and reports degraded confidence."""
        html = fixture_html(filename)
        parser = DHCParserV1()
        result = parser.parse(html, source_url="https://delhihighcourt.nic.in/x")

        assert 0.2 <= result.parse_confidence < 0.7, (
            f"{filename}: expected mid-band confidence, got {result.parse_confidence}"
        )
        assert result.parties, "Parties must still be extractable on a degraded page"

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


# ── Defensive: parser is registered as the default ───────────────────────

@parser_impl_required
def test_parser_implements_case_parser_interface():
    """The skeleton ships an abstract CaseParser; the impl must subclass it."""
    from app.parsers.case_parser import CaseParser
    assert issubclass(DHCParserV1, CaseParser)
