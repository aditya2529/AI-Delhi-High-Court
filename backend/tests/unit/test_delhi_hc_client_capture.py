"""Integration tests: DelhiHCClient.submit_search → real-response capture.

What this suite locks in
------------------------
The 2026-05-17 demo bug was that the parser failed on real HTML AND we
had nothing on disk to debug from. The capture path (Step 1 of the
"founder's parser-broken-in-real-mode" sprint) is what closes the second
half of that gap — every successful real-client search now leaves a
redacted fixture in ``parsers/fixtures/real_responses/`` automatically.

This file proves the WIRING — that ``DelhiHCClient.submit_search``
actually calls into ``response_capture`` with the right inputs, honours
the ``DHC_CAPTURE_REAL_RESPONSES`` feature flag, and never lets a
capture failure break the user's search. The capture function's own
behaviour (redaction, filename safety) is in
``test_response_capture.py``.

Why separate from ``test_delhi_hc_client_contract.py``: contract tests
are pure (no filesystem). Capture is an FS side-effect. Keeping them
in different files makes it impossible for a contract test to leak a
file onto disk and confuse the next test's assertions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import httpx
import pytest

from app.clients.delhi_hc_client import (
    COOKIE_SESSION,
    COOKIE_XSRF,
    ENDPOINT_FORM_PAGE,
    ENDPOINT_GET_CAPTCHA,
    ENDPOINT_SUBMIT,
    ENDPOINT_VALIDATE_CAPTCHA,
    DelhiHCClient,
)
from app.config import get_settings
from app.runtime_flags import get_flags
from app.sessions.store import CourtSession


# Reuse the realistic XSRF / session cookie shapes from the contract suite.
RAW_XSRF = (
    "eyJpdiI6Imh5akh2blNPRjBSN2xuYWZyVHpvMkE9PSIsInZhbHVlIjoicGViNnFjMjYwa0tYSk"
    "QybUtNS1FXTVVmZWQzdGR0Ky9qaUczNFBaYU1icFFhWnlYNHdxWi83d2lMTGN4TnZaQ3N3THZN"
    "T3RZTlNOUStYYzdacXBydUtmOHcrRnEzMFgvVGRINHNoSTRqd2JKRE9GQkFsNU91ZjJZeThiL3"
    "VobnkiLCJtYWMiOiJmZDhlNGJjZDE3OTQ1NDM4Nzk4NTNjZDVmMjMyMGQ1ODg4OTM1MmYzNjA0"
    "MzBmYjZlYzQwMDE2MWQ4ZjNmZmIxIiwidGFnIjoiIn0%3D"
)
RAW_SESSION = (
    "eyJpdiI6IkxqdThpeXo1eW1hUG5qcTJ5TWE4Qnc9PSIsInZhbHVlIjoiUFJPdnkya2IxdHdTbk"
    "tuWU5qUFI0dkxTRElGSTFHZXFmbGlaOHNvVjhUYUswQnk5dWVTQ3VKcEQwc2Q5dk9ySk9LZVRW"
    "UDZQVVBNOUtUOUFzK3k5L2dZSHRmK0k1dnhxVWlMZ2dKdldQS0t5MGFHOHZtT04va0d3WTZFYl"
    "k5VFIiLCJtYWMiOiJhYzkxMjA2NTYwNmFhYjU1NDY1YzkxOTcwZTYwMWM1NzFkMjZhNzNkYTUz"
    "ZTlhOTY2ZjIyNmQzYmE3MTY4YjNlIiwidGFnIjoiIn0%3D"
)

# A realistic upstream success body — looks like a thin court result page.
# Includes a "Source IP" line + an embedded cookie token to prove the
# redaction runs end-to-end.
REALISTIC_SUCCESS_HTML = (
    "<html><body>"
    "<!-- Source IP: 203.0.113.42 -->"
    "<div class='container'>"
    "<table class='case-details'>"
    "<tr><th>Status</th><td class='case-status'>PENDING</td></tr>"
    "</table>"
    "<table class='parties'>"
    "<tr class='party petitioner'>"
    "<td class='role'>Petitioner</td>"
    "<td class='name'>Shruti Katiyar</td>"
    "</tr>"
    "</table>"
    "</div>"
    "<script>var t = 'eyJivACTUALLYVERYLONGTOKENBLOBABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890_abc';</script>"
    "</body></html>"
)


@pytest.fixture(autouse=True)
def _reset_caches_and_flags():
    """Same hygiene as the contract suite — settings + kill-switch reset."""
    def _reset() -> None:
        get_settings.cache_clear()
        get_flags().outbound_fetch_enabled = True
    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def _disable_pacing(monkeypatch):
    """The 3s pacing between requests would slow this suite to a crawl."""
    from app.clients import delhi_hc_client as mod
    monkeypatch.setattr(mod, "MIN_REQUEST_SPACING_SECONDS", 0.0)


@pytest.fixture
def isolated_capture_dir(monkeypatch, tmp_path):
    """Redirect the capture default dir to a tmp path so tests can't pollute
    the real ``parsers/fixtures/real_responses/`` bucket.

    We patch ``DEFAULT_CAPTURE_DIR`` AND the bound name inside
    ``response_capture`` so any subsequent reference resolves to the tmp.
    The submit code path uses the default, not an injected dir.
    """
    from app.clients import response_capture as mod
    monkeypatch.setattr(mod, "DEFAULT_CAPTURE_DIR", tmp_path)
    return tmp_path


def _make_handler(captured: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        if request.method == "GET" and path == ENDPOINT_FORM_PAGE:
            return httpx.Response(
                200,
                text="<html>form page</html>",
                headers=[
                    ("set-cookie", f"{COOKIE_XSRF}={RAW_XSRF}; path=/; secure"),
                    ("set-cookie", f"{COOKIE_SESSION}={RAW_SESSION}; path=/; secure; httponly"),
                ],
            )
        if request.method == "GET" and path == ENDPOINT_GET_CAPTCHA:
            return httpx.Response(
                200,
                content=b"\x89PNG_FAKE",
                headers={"content-type": "image/png"},
            )
        if request.method == "POST" and path == ENDPOINT_VALIDATE_CAPTCHA:
            return httpx.Response(200, json={"status": True})
        if request.method == "POST" and path == ENDPOINT_SUBMIT:
            return httpx.Response(200, text=REALISTIC_SUCCESS_HTML)
        raise AssertionError(f"unexpected request: {request.method} {path}")
    return handler


def _mk_client(*, validate_before_submit: bool = False):
    """Build a DelhiHCClient with a MockTransport. Defaults to 2-step flow
    so the simpler tests don't need to thread validate behaviour through."""
    recorded: list[httpx.Request] = []
    transport = httpx.MockTransport(_make_handler(recorded))
    get_settings.cache_clear()
    client = DelhiHCClient(
        transport=transport,
        validate_before_submit=validate_before_submit,
    )
    return client, recorded


async def _drive_full_flow(client: DelhiHCClient, captcha_text: str = "22") -> None:
    """End-to-end: init → captcha → submit. Returns nothing — caller asserts
    on capture side effects."""
    case_type, case_number, year = "W.P.(C)", "2344", 2024
    await client.init_session(
        case_type=case_type, case_number=case_number, year=year,
    )
    session = CourtSession(
        session_id="sid",
        case_type=case_type,
        case_number=case_number,
        year=year,
    )
    await client.fetch_captcha(session=session)
    await client.submit_search(session=session, captcha_text=captcha_text)


# ─── Wiring tests ──────────────────────────────────────────────────────────


class TestCapturePathHappy:
    """The capture file actually lands on disk after a successful submit."""

    async def test_submit_writes_capture_file_to_default_dir(
        self, isolated_capture_dir, monkeypatch
    ):
        """The exact reason this code exists — every successful real
        submit must leave a fixture for future parser tuning."""
        monkeypatch.setenv("DHC_CAPTURE_REAL_RESPONSES", "true")
        client, _ = _mk_client()
        try:
            await _drive_full_flow(client)
        finally:
            await client.aclose()

        captures = list(isolated_capture_dir.glob("*.html"))
        assert len(captures) == 1, (
            f"Expected exactly one capture file; got {[p.name for p in captures]}"
        )
        # Filename matches the safe-case-id pattern.
        assert captures[0].name.startswith("WPC_2344_2024_")
        assert captures[0].name.endswith(".html")

    async def test_capture_file_is_redacted(
        self, isolated_capture_dir, monkeypatch
    ):
        """The on-disk file must be the REDACTED form. Source IP gone,
        bearer blob gone — party name intact (public court data)."""
        monkeypatch.setenv("DHC_CAPTURE_REAL_RESPONSES", "true")
        client, _ = _mk_client()
        try:
            await _drive_full_flow(client)
        finally:
            await client.aclose()

        captures = list(isolated_capture_dir.glob("*.html"))
        assert len(captures) == 1
        on_disk = captures[0].read_text(encoding="utf-8")

        # Sensitive bits gone.
        assert "203.0.113.42" not in on_disk
        assert "eyJivACTUALLYVERY" not in on_disk
        # Public bits preserved.
        assert "Shruti Katiyar" in on_disk
        assert "PENDING" in on_disk
        # Structural markup preserved.
        assert "class='case-details'" in on_disk or 'class="case-details"' in on_disk


class TestCaptureFeatureFlag:
    """DHC_CAPTURE_REAL_RESPONSES is the on/off switch."""

    async def test_capture_disabled_writes_nothing(
        self, isolated_capture_dir, monkeypatch
    ):
        """Production sets this False; the capture code must be skipped
        entirely — no FS touches at all."""
        monkeypatch.setenv("DHC_CAPTURE_REAL_RESPONSES", "false")
        client, _ = _mk_client()
        try:
            await _drive_full_flow(client)
        finally:
            await client.aclose()

        captures = list(isolated_capture_dir.glob("*.html"))
        assert captures == [], (
            f"Capture should be disabled but found: {[p.name for p in captures]}"
        )

    async def test_capture_default_is_enabled(
        self, isolated_capture_dir, monkeypatch
    ):
        """Without explicit env var, dev defaults to capture-on so the next
        founder run leaves fixtures behind without re-configuration."""
        monkeypatch.delenv("DHC_CAPTURE_REAL_RESPONSES", raising=False)
        client, _ = _mk_client()
        try:
            await _drive_full_flow(client)
        finally:
            await client.aclose()

        captures = list(isolated_capture_dir.glob("*.html"))
        assert len(captures) == 1


class TestCaptureFailureNeverBreaksSubmit:
    """The whole point: a capture failure must NOT propagate to the user."""

    async def test_capture_write_failure_does_not_raise(
        self, isolated_capture_dir, monkeypatch
    ):
        """Simulate disk-full inside the capture write. The submit_search
        call must complete successfully and return a CaseSearchResult."""
        monkeypatch.setenv("DHC_CAPTURE_REAL_RESPONSES", "true")

        # Make Path.write_text raise OSError when called.
        def fake_write(self, *args, **kwargs):
            raise OSError("Simulated disk full")
        monkeypatch.setattr(Path, "write_text", fake_write)

        client, _ = _mk_client()
        try:
            # If capture leaks the OSError, this call raises and the
            # test fails. The whole point is that it doesn't.
            await _drive_full_flow(client)
        finally:
            await client.aclose()

        # Capture failed → no file. But the search still completed.
        assert list(isolated_capture_dir.glob("*.html")) == []
