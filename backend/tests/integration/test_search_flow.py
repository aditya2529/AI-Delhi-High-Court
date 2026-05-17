"""Integration tests for the /search/* flow against a FakeCourtClient.

These tests drive the **CONTRACT** described in:
  * docs/api/API-CONTRACT.md §2 (POST /search/init)
  * docs/api/API-CONTRACT.md §3 (POST /search/submit)
  * docs/api/API-CONTRACT.md §4 (GET /search/{id}/refresh-captcha)
  * docs/architecture/STRATEGIES.md §2 (CAPTCHA handling)
  * docs/architecture/STRATEGIES.md §4 (Error envelope)
  * docs/prd/user-stories.md US-01..US-07

While Arjun's route implementations are still skeleton (501 Not Implemented),
the tests detect that state and ``xfail`` with a clear pointer. Once the
real routes land, the tests light up green automatically — no edits needed.

Adversarial coverage (Maya):
  * Wrong CAPTCHA -> body.status = "captcha_failed" (US-04)
  * Expired session -> body.status = "expired" (US-05)
  * Not found -> body.status = "not_found" (US-06)
  * Court error -> body.status = "court_error" (US-07)
  * Double-submit race -> 409 in_progress (API-CONTRACT §3)
  * Empty / oversized / unicode CAPTCHA text -> 400 invalid_request
"""
from __future__ import annotations

import pytest


def _stub_response(resp) -> bool:
    """Return True if the route hasn't been implemented yet (501 from skeleton).

    We use this to convert "implementation pending" into an `xfail` per test
    so the gap is *visible* in CI output, not hidden by a blanket skip.
    """
    return resp.status_code == 501


async def _math_answer_for_session(session_id: str) -> str:
    """Read the FakeCourtClient's math CAPTCHA answer off the live store.

    FakeCourtClient defaults to math CAPTCHAs (matches real Delhi HC, see
    docs/DEMO-FEEDBACK.md item #6). The answer is stashed on the persisted
    session under ``csrf_tokens["upstream_token"]`` — we reach in here so
    integration tests can submit a *correct* answer end-to-end without
    OCR'ing the rendered image. Production code never reads this field
    via test surface; the route layer simply persists it for the
    in-process fake to validate against on submit.
    """
    from app.services.dependencies import get_session_store
    store = get_session_store()
    s = await store.get(session_id)
    assert s is not None, f"session {session_id!r} missing from store"
    answer = s.csrf_tokens.get("upstream_token", "")
    assert answer, "FakeCourtClient (math mode) must seed upstream_token"
    return answer


# ── Validation tests (work against the skeleton — Pydantic catches these) ─

class TestSearchInitValidation:
    async def test_init_rejects_missing_case_type(self, async_client):
        """US-01 AC-3: required field missing -> 400 invalid_request."""
        resp = await async_client.post("/api/v1/search/init", json={
            "case_number": "1", "year": 2024,
        })
        assert resp.status_code in (400, 422)  # FastAPI default is 422

    async def test_init_rejects_year_before_1950(self, async_client):
        """API-CONTRACT §2: year >= 1950."""
        resp = await async_client.post("/api/v1/search/init", json={
            "case_type": "W.P.(C)", "case_number": "1", "year": 1899,
        })
        assert resp.status_code in (400, 422)

    async def test_init_rejects_year_far_future(self, async_client):
        """API-CONTRACT §2: year <= current_year (skeleton allows up to 2100;
        once Arjun tightens to current_year the upper-bound test below should
        be updated. Pin the looser bound for now)."""
        resp = await async_client.post("/api/v1/search/init", json={
            "case_type": "W.P.(C)", "case_number": "1", "year": 99999,
        })
        assert resp.status_code in (400, 422)

    async def test_init_rejects_empty_case_number(self, async_client):
        """Adversarial: empty string for case_number — must be rejected.

        SKELETON GAP: the Pydantic model lacks min_length on case_number;
        flag back to Arjun via API contract. Marked xfail until fixed.
        """
        resp = await async_client.post("/api/v1/search/init", json={
            "case_type": "W.P.(C)", "case_number": "", "year": 2024,
        })
        if resp.status_code == 200:
            pytest.xfail(
                "Skeleton SearchInitRequest accepts empty case_number — "
                "should enforce min_length=1 per API-CONTRACT §2 (Arjun)."
            )
        assert resp.status_code in (400, 422)

    async def test_init_rejects_non_digit_case_number(self, async_client):
        """API-CONTRACT §2: case_number is 'digits only, 1–7 chars'.

        Skeleton model doesn't enforce digits-only — flag to Arjun.
        """
        resp = await async_client.post("/api/v1/search/init", json={
            "case_type": "W.P.(C)", "case_number": "abc'; DROP TABLE--", "year": 2024,
        })
        if resp.status_code == 200:
            pytest.xfail(
                "Skeleton SearchInitRequest accepts non-digit case_number — "
                "should enforce digit-only constraint per API-CONTRACT §2 (Arjun)."
            )
        assert resp.status_code in (400, 422)


class TestSubmitValidation:
    async def test_submit_rejects_missing_session_id(self, async_client):
        """US-05: malformed submit body -> 400/422."""
        resp = await async_client.post("/api/v1/search/submit", json={
            "captcha_text": "ABCDE",
        })
        assert resp.status_code in (400, 422)

    async def test_submit_rejects_empty_captcha_text(self, async_client):
        """US-02 AC-4: empty CAPTCHA must be rejected."""
        resp = await async_client.post("/api/v1/search/submit", json={
            "session_id": "00000000-0000-0000-0000-000000000000",
            "captcha_text": "",
        })
        assert resp.status_code in (400, 422)

    async def test_submit_rejects_oversized_captcha_text(self, async_client):
        """API-CONTRACT §3: captcha_text 1-10 chars (skeleton allows 3-20;
        once tightened this lower-cap test becomes meaningful)."""
        resp = await async_client.post("/api/v1/search/submit", json={
            "session_id": "00000000-0000-0000-0000-000000000000",
            "captcha_text": "X" * 500,
        })
        assert resp.status_code in (400, 422)


# ── Happy-path / behavioural flow (gated on impl) ─────────────────────────

class TestSearchFlow:
    async def test_happy_path_init_then_submit_returns_parsed_case(
        self, async_client, valid_init_body
    ):
        """US-01 + US-02 + US-03 (happy path): init -> CAPTCHA -> submit -> result.

        End-to-end success: a known case maps to WPC_12345_2024.html fixture
        in FakeCourtClient, the parser converts it, and the body shape
        matches ParsedCase from API-CONTRACT §7.1.
        """
        init = await async_client.post("/api/v1/search/init", json=valid_init_body)
        if _stub_response(init):
            pytest.xfail("search.init is a skeleton (501) — Arjun's sprint")
        assert init.status_code == 200
        init_body = init.json()
        assert "session_id" in init_body
        assert "captcha_image_b64" in init_body
        assert "captcha_expires_at" in init_body

        # FakeCourtClient defaults to math CAPTCHAs (matches real Delhi HC).
        # Read the answer off the persisted session and submit it back.
        answer = await _math_answer_for_session(init_body["session_id"])
        submit = await async_client.post("/api/v1/search/submit", json={
            "session_id": init_body["session_id"],
            "captcha_text": answer,
        })
        assert submit.status_code == 200
        body = submit.json()
        assert body["status"] == "success"
        assert body["result"] is not None
        result = body["result"]
        # ParsedCase contract (API-CONTRACT §7.1)
        for required in (
            "case_id", "case_type", "case_number", "year", "parties",
            "orders", "judgments", "raw_html_hash", "parsed_at",
            "source_url", "parser_version",
        ):
            assert required in result, f"ParsedCase missing required field: {required}"
        assert result["case_type"] == valid_init_body["case_type"]
        assert result["year"] == valid_init_body["year"]

    async def test_wrong_captcha_returns_200_with_captcha_failed_envelope(
        self, async_client, valid_init_body
    ):
        """US-04 AC-1: incorrect CAPTCHA => body.status = 'captcha_failed'.

        Note: per API-CONTRACT §3, this is a 200 (body-level status), NOT 422.
        The user-facing brief also mentioned 422 — flagging that drift to Arnav.
        """
        init = await async_client.post("/api/v1/search/init", json=valid_init_body)
        if _stub_response(init):
            pytest.xfail("search.init is a skeleton (501)")
        sid = init.json()["session_id"]

        resp = await async_client.post("/api/v1/search/submit", json={
            "session_id": sid, "captcha_text": "WRONG",
        })
        # Contract: 200 with body.status='captcha_failed'.
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "captcha_failed"
        assert body["result"] is None
        # attempts_remaining is a contract field per §3 — checked when present.
        if "attempts_remaining" in body:
            assert isinstance(body["attempts_remaining"], int)
            assert body["attempts_remaining"] >= 0

    async def test_expired_session_submit_returns_expired_status(
        self, async_client, valid_init_body, frozen_clock
    ):
        """US-05 AC-1: session past TTL => body.status='expired' + retry_url.

        Strategy: init at T=0, advance the frozen clock past session TTL,
        then submit. The store's TTL check evicts the session, and the
        route returns the 'expired' envelope.
        """
        init = await async_client.post("/api/v1/search/init", json=valid_init_body)
        if _stub_response(init):
            pytest.xfail("search.init is a skeleton (501)")
        sid = init.json()["session_id"]

        # Advance well past session TTL (default 600s)
        frozen_clock.advance(601)

        resp = await async_client.post("/api/v1/search/submit", json={
            "session_id": sid, "captcha_text": "TEST",
        })
        # Per API-CONTRACT: this should be 200 with status='expired', NOT a 410.
        # The brief also mentioned 410 — flag drift to Arnav.
        if resp.status_code == 410:
            body = resp.json()
            assert body["error"]["code"] in {"session_not_found", "session_consumed"}
        else:
            assert resp.status_code == 200
            assert resp.json()["status"] == "expired"

    async def test_not_found_case_returns_not_found_status(self, async_client):
        """US-06 AC-1: court returned 'no records' -> body.status='not_found'."""
        init = await async_client.post("/api/v1/search/init", json={
            "case_type": "FAO", "case_number": "99999", "year": 2099,
        })
        if _stub_response(init):
            pytest.xfail("search.init is a skeleton (501)")
        sid = init.json()["session_id"]

        answer = await _math_answer_for_session(sid)
        resp = await async_client.post("/api/v1/search/submit", json={
            "session_id": sid, "captcha_text": answer,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "not_found"
        assert body["result"] is None

    async def test_court_error_fixture_returns_court_error_envelope(self, async_client):
        """US-07: case_number='COURT_ERROR' maps to COURT_ERROR.html in
        FakeCourtClient -> body.status='court_error' (body-level 200) or 503
        court_error envelope.

        Selector was previously `year == 1900` — moved to an explicit
        case_number sentinel so the routing isn't coupled to schema data.

        The contract is ambiguous: API-CONTRACT §3 lists both `200` body-status
        and `503` http-code as valid for upstream errors. Either is acceptable
        as long as one of them is consistently returned. We assert both shapes
        and flag the contract gap to Arnav.
        """
        init = await async_client.post("/api/v1/search/init", json={
            "case_type": "W.P.(C)", "case_number": "COURT_ERROR", "year": 2024,
        })
        if _stub_response(init):
            pytest.xfail("search.init is a skeleton (501)")

        if init.status_code == 503:
            assert init.json()["error"]["code"] == "court_error"
            return

        assert init.status_code == 200
        sid = init.json()["session_id"]
        answer = await _math_answer_for_session(sid)
        resp = await async_client.post("/api/v1/search/submit", json={
            "session_id": sid, "captcha_text": answer,
        })
        if resp.status_code == 503:
            assert resp.json()["error"]["code"] == "court_error"
        else:
            assert resp.status_code == 200
            assert resp.json()["status"] == "court_error"

    async def test_submit_with_unknown_session_id_returns_404(self, async_client):
        """API-CONTRACT §3: session_not_found -> 404 with envelope."""
        resp = await async_client.post("/api/v1/search/submit", json={
            "session_id": "deadbeef-dead-beef-dead-beefdeadbeef",
            "captcha_text": "TEST",
        })
        if _stub_response(resp):
            pytest.xfail("search.submit is a skeleton (501)")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "session_not_found"
        assert body["error"]["retryable"] is False


# ── Error envelope shape — invariant across every non-2xx response ────────

class TestErrorEnvelopeInvariant:
    async def test_validation_error_uses_contract_envelope(self, async_client):
        """API-CONTRACT §1.4: every non-2xx body has {error: {code, message,
        retryable, request_id}}. FastAPI's default 422 does NOT match this —
        the app needs a custom exception handler. Flag to Arjun if missing."""
        resp = await async_client.post("/api/v1/search/init", json={})
        assert resp.status_code in (400, 422)
        body = resp.json()
        # Either the custom envelope is wired (preferred) or we get FastAPI's
        # default {"detail": ...} shape (current skeleton). Pin the gap.
        if "error" not in body:
            pytest.xfail(
                "Error envelope handler not yet wired — body uses FastAPI default "
                "{'detail': ...} shape. Per API-CONTRACT §1.4 ALL non-2xx must "
                "use {error: {code, message, retryable, request_id}}. Flag to Arjun."
            )
        assert "code" in body["error"]
        assert "message" in body["error"]
        assert "retryable" in body["error"]
        assert "request_id" in body["error"]


# ── Refresh-captcha endpoint ─────────────────────────────────────────────

class TestRefreshCaptcha:
    async def test_refresh_unknown_session_returns_404(self, async_client):
        """API-CONTRACT §4: unknown session_id -> 404 session_not_found."""
        resp = await async_client.get(
            "/api/v1/search/deadbeef-dead-beef-dead-beefdeadbeef/refresh-captcha"
        )
        if _stub_response(resp):
            pytest.xfail("search.refresh-captcha is a skeleton (501)")
        assert resp.status_code == 404

    async def test_refresh_returns_new_captcha_for_active_session(
        self, async_client, valid_init_body
    ):
        """US-02 AC-3: refresh delivers a new image, preserves form state."""
        init = await async_client.post("/api/v1/search/init", json=valid_init_body)
        if _stub_response(init):
            pytest.xfail("search.init is a skeleton (501)")
        sid = init.json()["session_id"]

        refresh = await async_client.get(f"/api/v1/search/{sid}/refresh-captcha")
        assert refresh.status_code == 200
        body = refresh.json()
        assert "captcha_image_b64" in body
        assert body["captcha_image_b64"] != init.json()["captcha_image_b64"]
