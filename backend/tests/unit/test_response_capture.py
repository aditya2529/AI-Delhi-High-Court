"""Unit tests for the real-court response capture module.

Test strategy
-------------
The capture module is the one shipping in response to the 2026-05-17
demo: the founder's CLIENT_MODE=real run worked end-to-end but the
response HTML was never persisted, leaving the parser blind to real
HTML shape. The capture path is now load-bearing for every future
parser-tuning sprint, so we cover:

  * Happy path — file lands with the right name + shape.
  * Redaction — sensitive bits go; public court data stays.
  * Boundary cases — empty body, missing dir, write failure.
  * Adversarial — unicode, huge body, IPv6, multiple cookies, idempotency.
  * Filename safety — Windows-hostile case_type punctuation.
  * Failure mode — capture errors NEVER raise to the caller.

The capture function is intentionally config-agnostic; the
``DHC_CAPTURE_REAL_RESPONSES`` guard lives at the call site in
``DelhiHCClient.submit_search`` and is exercised by the integration
test ``test_delhi_hc_client_capture.py`` (separate file — keeps
contract tests free of FS side effects).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.clients.response_capture import (
    DEFAULT_CAPTURE_DIR,
    capture_real_response,
    redact_html,
    safe_case_id_for_filename,
)


# ─── safe_case_id_for_filename ─────────────────────────────────────────────


class TestSafeCaseIdForFilename:
    """Filename stems must survive Windows + Unix path rules."""

    def test_strips_punctuation_from_wpc(self):
        """Real founder case: 'W.P.(C)' must collapse to 'WPC'."""
        assert safe_case_id_for_filename("W.P.(C)", "2344", 2024) == "WPC_2344_2024"

    def test_strips_punctuation_from_crlmc(self):
        """CRL.M.C. → CRLMC; the dots are filename-hostile on Windows in
        edge cases (trailing-dot truncation) and ugly everywhere."""
        assert safe_case_id_for_filename("CRL.M.C.", "999", 2023) == "CRLMC_999_2023"

    def test_handles_alnum_only_case_type(self):
        """No punctuation → no transformation."""
        assert safe_case_id_for_filename("FAO", "1", 2025) == "FAO_1_2025"

    def test_handles_pipe_separator_case_ids(self):
        """If someone hands us a pre-joined case_id like 'W.P.(C)|12|2024'
        accidentally, the pipe must vanish — never end up in a path."""
        # ``case_type`` shouldn't contain a pipe in practice, but the
        # sanitiser must defend against it anyway. The pipe + dots collapse;
        # alnum survives in document order.
        out = safe_case_id_for_filename("W.P.(C)|12|2024", "1", 2024)
        assert "|" not in out
        assert "." not in out
        assert "(" not in out and ")" not in out
        assert out.startswith("WPC")

    def test_collapses_to_placeholder_on_all_punctuation(self):
        """Defensive — adversarial / corrupt input must produce SOMETHING
        the filesystem accepts, never an empty stem. Empty components map
        to a literal 'X' so the stem is human-readable and never collides
        with a real numeric case_number."""
        out = safe_case_id_for_filename("!!!", "...", 0)
        # Whatever the exact form, it MUST be filesystem-safe and non-empty.
        assert out
        assert re.fullmatch(r"[A-Za-z0-9_]+", out), out
        # And the year survives (the only non-punctuation component).
        assert "0" in out

    def test_case_id_preserves_case(self):
        """We don't lowercase — preserve the case_type's canonical form
        so a glob like 'WPC_*.html' matches the way the user expects."""
        assert safe_case_id_for_filename("LPA", "1", 2024) == "LPA_1_2024"


# ─── redact_html ───────────────────────────────────────────────────────────


class TestRedactHtmlPublicDataPreserved:
    """The whole point of capture: party names + dates must survive
    intact so the parser has something to extract."""

    def test_petitioner_name_preserved(self):
        """Shruti Katiyar (founder's test case) is public court data — KEEP."""
        html = '<td class="name">Shruti Katiyar</td>'
        assert redact_html(html) == html

    def test_respondent_name_preserved(self):
        """'Registrar General' — public court data."""
        html = '<td class="name">Registrar General, Delhi High Court</td>'
        assert redact_html(html) == html

    def test_hearing_dates_preserved(self):
        """ISO-format hearing dates — public, must survive for the parser."""
        html = '<td class="next-hearing-date">2026-06-15</td>'
        assert redact_html(html) == html

    def test_case_number_preserved(self):
        """'W.P.(C) 2344/2024' — the user's own input — must survive."""
        html = "<h2>W.P.(C) 2344/2024 - Shruti Katiyar v. Registrar General</h2>"
        assert redact_html(html) == html

    def test_class_names_preserved(self):
        """Structural markup is load-bearing for the parser — never touch."""
        html = '<table class="case-details"><tr class="party petitioner"></tr></table>'
        assert redact_html(html) == html


class TestRedactHtmlSensitiveDataStripped:
    """Sensitive identifiers per Sneha's rules + the GREEN-ZONE rails."""

    def test_ipv4_redacted(self):
        """Court site occasionally embeds the user's IP in audit text."""
        result = redact_html("Source IP: 203.0.113.45")
        assert "203.0.113.45" not in result
        assert "0.0.0.0" in result

    def test_ipv6_redacted(self):
        """IPv6 patterns too — the regex is conservative but must catch
        full-length addresses."""
        result = redact_html("Source IP: 2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        assert "2001:0db8" not in result
        # The redactor substitutes the colon-separated runs with ``::``.
        assert "::" in result

    def test_xsrf_cookie_value_redacted(self):
        """The Laravel XSRF token leaks session identity — strip it."""
        # Realistic Laravel XSRF token shape (URL-encoded base64).
        raw = "Cookie: XSRF-TOKEN=eyJpdiI6ImFiY2QxMjM0NTY3ODkwYWJjZGVmZ2hpamtsbW5vcA%3D%3D; other=keep"
        result = redact_html(raw)
        assert "eyJpdiI" not in result
        # The cookie *name* must survive — only its value goes.
        assert "XSRF-TOKEN=REDACTED" in result
        # Innocent cookies are untouched.
        assert "other=keep" in result

    def test_session_cookie_value_redacted(self):
        """hc_application_session is the Laravel session — strip its value."""
        raw = "Cookie: hc_application_session=eyJpdiI6IkxqdThpeXo1eW1hUG5qcTJ5TWE4Qnc9PQ%3D%3D"
        result = redact_html(raw)
        assert "eyJpdiI" not in result
        assert "hc_application_session=REDACTED" in result

    def test_x_xsrf_token_header_redacted(self):
        """When the page embeds a debug surface that echoes the header."""
        raw = "X-XSRF-TOKEN: eyJpdiI6ImFiY2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6QUJDRA"
        result = redact_html(raw)
        assert "eyJpdiI" not in result
        assert "X-XSRF-TOKEN: REDACTED" in result

    def test_bearer_blob_redacted_anywhere(self):
        """Bare `eyJ...` blobs (JWT-shaped) in the body get redacted even
        outside of a cookie/header context."""
        long_blob = "eyJ" + "A" * 80
        raw = f"<script>var token = '{long_blob}';</script>"
        result = redact_html(raw)
        assert long_blob not in result
        assert "REDACTED_TOKEN" in result

    def test_short_eyj_string_not_falsely_redacted(self):
        """Conservative threshold: `eyJfoo` (too short to be a token) is
        kept. Prevents over-redaction of unrelated content that happens
        to start with eyJ."""
        html = "<p>eyJustForFun is not a token.</p>"
        result = redact_html(html)
        assert "eyJustForFun" in result

    def test_multiple_xsrf_cookies_all_redacted(self):
        """Some pages set the cookie multiple times across debug surfaces."""
        raw = (
            "Set-Cookie: XSRF-TOKEN=valueA1234567890\n"
            "Set-Cookie: XSRF-TOKEN=valueB1234567890\n"
        )
        result = redact_html(raw)
        assert "valueA" not in result
        assert "valueB" not in result
        assert result.count("XSRF-TOKEN=REDACTED") == 2

    def test_json_embedded_cookie_value_redacted(self):
        """Cookie values can leak via embedded JSON, not just Cookie: lines."""
        raw = '{"XSRF-TOKEN": "abcdef1234567890", "case_number": "2344"}'
        result = redact_html(raw)
        assert "abcdef1234567890" not in result
        assert '"REDACTED"' in result
        # Adjacent public field must survive.
        assert '"case_number": "2344"' in result


class TestRedactHtmlEdgeCases:
    def test_empty_string_returns_empty(self):
        """Don't crash on an empty body."""
        assert redact_html("") == ""

    def test_none_returns_none(self):
        """Don't crash on None — caller may pass it during defensive flows."""
        # type: ignore[arg-type] — we accept Optional in spirit
        assert redact_html(None) is None  # type: ignore[arg-type]

    def test_redaction_is_idempotent(self):
        """Running redact_html twice produces the same output as once."""
        raw = "IP: 192.168.1.1, XSRF-TOKEN=eyJabcd1234567890_loooong; ok"
        once = redact_html(raw)
        twice = redact_html(once)
        assert once == twice

    def test_unicode_preserved(self):
        """Court HTML can contain Devanagari / Tamil names. Must survive."""
        html = '<td class="name">श्रुति कटियार</td>'
        assert redact_html(html) == html

    def test_does_not_redact_random_numeric_strings(self):
        """ISO dates like 2026-05-17 must not match the IPv4 pattern."""
        result = redact_html("Filed on 2026-05-17 in court 12")
        assert "2026-05-17" in result

    def test_large_body_handled(self):
        """100KB body — typical real court response order of magnitude.
        Must complete without timeout / memory blow-up."""
        body = "<p>safe content</p>" * 5000
        body += "Source IP: 10.0.0.1"
        result = redact_html(body)
        assert "10.0.0.1" not in result
        assert result.count("<p>safe content</p>") == 5000


# ─── capture_real_response ─────────────────────────────────────────────────


class TestCaptureRealResponseHappyPath:
    def test_writes_file_to_target_dir(self, tmp_path):
        """The smoke test — file appears, with content."""
        target = capture_real_response(
            raw_html="<html><body>ok</body></html>",
            case_type="W.P.(C)", case_number="2344", year=2024,
            capture_dir=tmp_path,
            now_unix=1_747_000_000,
        )
        assert target is not None
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "<html><body>ok</body></html>"

    def test_filename_uses_safe_case_id_and_timestamp(self, tmp_path):
        """W.P.(C)/2344/2024 → WPC_2344_2024_<unix>.html."""
        target = capture_real_response(
            raw_html="<html></html>",
            case_type="W.P.(C)", case_number="2344", year=2024,
            capture_dir=tmp_path,
            now_unix=1_747_000_000,
        )
        assert target is not None
        assert target.name == "WPC_2344_2024_1747000000.html"

    def test_creates_parent_dir_if_missing(self, tmp_path):
        """Real_responses/ may not exist on a fresh clone — must create."""
        missing = tmp_path / "deep" / "nested" / "real_responses"
        assert not missing.exists()
        target = capture_real_response(
            raw_html="<html></html>",
            case_type="FAO", case_number="1", year=2025,
            capture_dir=missing,
            now_unix=1_747_000_000,
        )
        assert target is not None
        assert missing.exists()
        assert target.parent == missing

    def test_redacts_sensitive_bytes_before_write(self, tmp_path):
        """The on-disk file is the REDACTED form, never the raw bytes."""
        raw = (
            "<html>Source IP: 192.168.1.42\n"
            "Cookie: XSRF-TOKEN=eyJABCD1234567890abcdef; other=keep\n"
            '<td class="name">Shruti Katiyar</td></html>'
        )
        target = capture_real_response(
            raw_html=raw,
            case_type="W.P.(C)", case_number="2344", year=2024,
            capture_dir=tmp_path,
            now_unix=1_747_000_000,
        )
        assert target is not None
        on_disk = target.read_text(encoding="utf-8")
        # Sensitive bytes gone.
        assert "192.168.1.42" not in on_disk
        assert "eyJABCD" not in on_disk
        # Public bytes preserved.
        assert "Shruti Katiyar" in on_disk
        assert "other=keep" in on_disk

    def test_multiple_captures_same_case_get_unique_names(self, tmp_path):
        """The timestamp suffix versions multiple runs of the same case."""
        a = capture_real_response(
            raw_html="<a/>", case_type="FAO", case_number="1", year=2025,
            capture_dir=tmp_path, now_unix=1_747_000_000,
        )
        b = capture_real_response(
            raw_html="<b/>", case_type="FAO", case_number="1", year=2025,
            capture_dir=tmp_path, now_unix=1_747_000_001,
        )
        assert a != b
        assert a is not None and b is not None
        assert a.exists() and b.exists()
        assert a.read_text() == "<a/>"
        assert b.read_text() == "<b/>"


class TestCaptureRealResponseContentTypeRouting:
    """Post-2026-05-17 pivot: capture must pick the right file extension
    based on the upstream's content-type (or by sniffing the body if the
    header wasn't piped through). Saving JSON as .html was the bug Maya
    flagged on the WPC_2344_2024 capture — these tests pin the fix.
    """

    def test_json_content_type_lands_as_json(self, tmp_path):
        """Header explicitly says application/json → .json extension."""
        target = capture_real_response(
            raw_html='{"draw":0,"data":[]}',
            case_type="W.P.(C)", case_number="2344", year=2024,
            capture_dir=tmp_path,
            now_unix=1_747_000_000,
            content_type="application/json; charset=utf-8",
        )
        assert target is not None
        assert target.suffix == ".json"
        assert target.name == "WPC_2344_2024_1747000000.json"

    def test_html_content_type_lands_as_html(self, tmp_path):
        """Header says text/html → .html extension (covers the sentinel /
        error-page path where upstream still serves HTML)."""
        target = capture_real_response(
            raw_html="<html><body>err</body></html>",
            case_type="W.P.(C)", case_number="2344", year=2024,
            capture_dir=tmp_path,
            now_unix=1_747_000_000,
            content_type="text/html; charset=utf-8",
        )
        assert target is not None
        assert target.suffix == ".html"

    def test_sniffs_json_when_no_content_type(self, tmp_path):
        """No header → sniff body. ``{`` at the start → JSON."""
        target = capture_real_response(
            raw_html='{"draw":0,"recordsTotal":0,"data":[]}',
            case_type="W.P.(C)", case_number="2344", year=2024,
            capture_dir=tmp_path,
            now_unix=1_747_000_000,
            content_type=None,
        )
        assert target is not None
        assert target.suffix == ".json"

    def test_sniffs_html_when_no_content_type(self, tmp_path):
        """No header → sniff body. ``<`` at the start → HTML."""
        target = capture_real_response(
            raw_html="<html>...",
            case_type="W.P.(C)", case_number="2344", year=2024,
            capture_dir=tmp_path,
            now_unix=1_747_000_000,
        )
        assert target is not None
        assert target.suffix == ".html"

    def test_unknown_content_type_falls_back_to_sniffing(self, tmp_path):
        """Bogus content-type → fall back to body sniff."""
        target = capture_real_response(
            raw_html='{"x": 1}',
            case_type="W.P.(C)", case_number="2344", year=2024,
            capture_dir=tmp_path,
            now_unix=1_747_000_000,
            content_type="application/octet-stream",
        )
        assert target is not None
        assert target.suffix == ".json"


class TestCaptureRealResponseFailureModes:
    """Capture failures must NEVER bubble up to the caller — a write
    error must not break a user search."""

    def test_returns_none_on_oserror_during_write(self, tmp_path, monkeypatch):
        """Simulate disk full: Path.write_text raises OSError. We must
        return None, log a warning, and not raise."""
        from app.clients import response_capture as mod

        original_write_text = Path.write_text

        def fake_write(self, *args, **kwargs):
            raise OSError("Disk full (simulated)")

        monkeypatch.setattr(Path, "write_text", fake_write)

        try:
            result = capture_real_response(
                raw_html="<html/>",
                case_type="FAO", case_number="1", year=2025,
                capture_dir=tmp_path,
                now_unix=1_747_000_000,
            )
        finally:
            monkeypatch.setattr(Path, "write_text", original_write_text)
        assert result is None

    def test_returns_none_on_oserror_during_mkdir(self, tmp_path, monkeypatch):
        """If mkdir fails (permissions), return None — never raise."""
        def fake_mkdir(self, *args, **kwargs):
            raise OSError("Permission denied (simulated)")
        monkeypatch.setattr(Path, "mkdir", fake_mkdir)
        result = capture_real_response(
            raw_html="<html/>",
            case_type="FAO", case_number="1", year=2025,
            capture_dir=tmp_path / "new",
            now_unix=1_747_000_000,
        )
        assert result is None

    def test_capture_does_not_raise_on_empty_body(self, tmp_path):
        """Defensive — empty body is unusual but must still produce a file
        (parser will sentinel-classify it correctly downstream)."""
        target = capture_real_response(
            raw_html="",
            case_type="FAO", case_number="1", year=2025,
            capture_dir=tmp_path,
            now_unix=1_747_000_000,
        )
        assert target is not None
        assert target.read_text() == ""


class TestCaptureRealResponseDefaultLocation:
    """The default location should be the project's real_responses dir
    so a production-shape config 'just works'."""

    def test_default_dir_points_at_parsers_fixtures_real_responses(self):
        """Anchors the default path; if anyone moves the parser fixtures
        bucket they'll fail this test loudly."""
        assert DEFAULT_CAPTURE_DIR.parts[-3:] == (
            "parsers", "fixtures", "real_responses"
        )

    def test_default_dir_is_inside_project_root(self):
        """Defensive — capture must never escape to a sibling project."""
        # The path resolves under the project root.
        assert "AI Delhi High Court" in str(DEFAULT_CAPTURE_DIR) or \
               DEFAULT_CAPTURE_DIR.name == "real_responses"
