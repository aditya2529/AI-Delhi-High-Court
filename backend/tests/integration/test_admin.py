"""Integration tests for /admin/* endpoints.

Maps to:
  * docs/api/API-CONTRACT.md §6 (admin endpoints + X-Admin-Secret)
  * docs/prd/user-stories.md US-08 (admin log view)
  * docs/EXECUTIVE-SUMMARY.md gate G3 — kill-switch behaviour
  * docs/architecture/STRATEGIES.md §4 — error envelope on admin failures

Adversarial coverage (Maya):
  * No header -> 401, not 404 (US-08 AC-2 says 404 — flag the conflict).
  * Wrong secret -> 401.
  * Cross-tenant secret leak: only the canonical env-var value works.
  * Kill-switch flips OUTBOUND_FETCH_ENABLED; subsequent /init returns 503.
  * Pagination clamp: limit beyond max should clamp, not 500.
"""
from __future__ import annotations

import pytest


def _stub_response(resp) -> bool:
    return resp.status_code == 501


# ── Auth boundary ─────────────────────────────────────────────────────────

class TestAdminAuth:
    async def test_sessions_endpoint_rejects_missing_secret(self, async_client):
        """API-CONTRACT §6: missing X-Admin-Secret -> 401 unauthorized."""
        resp = await async_client.get("/api/v1/admin/sessions")
        # NOTE: US-08 AC-2 contradicts API-CONTRACT — story says 404 (to hide
        # the endpoint's existence), contract says 401. Flagging conflict.
        # We accept either, but the response code MUST NOT be 200.
        assert resp.status_code in (401, 404), (
            "Missing admin secret should NOT be 200. "
            "Contract drift: API-CONTRACT says 401, US-08 AC-2 says 404 (Priya/Arnav)."
        )

    async def test_sessions_endpoint_rejects_wrong_secret(self, async_client):
        """Adversarial: a guess at the secret must not authenticate."""
        resp = await async_client.get(
            "/api/v1/admin/sessions",
            headers={"X-Admin-Secret": "not-the-right-one"},
        )
        assert resp.status_code in (401, 404)

    async def test_sessions_endpoint_accepts_valid_secret(
        self, async_client, admin_headers
    ):
        """Happy path: correct secret passes the gate (whatever the impl returns)."""
        resp = await async_client.get(
            "/api/v1/admin/sessions", headers=admin_headers,
        )
        # Anything except 401/403 — could be 200 (impl) or 501 (skeleton)
        assert resp.status_code not in (401, 403)

    async def test_failures_endpoint_rejects_missing_secret(self, async_client):
        """API-CONTRACT §6.2: same auth gate applies."""
        resp = await async_client.get("/api/v1/admin/failures")
        assert resp.status_code in (401, 404)


# ── /admin/sessions ───────────────────────────────────────────────────────

class TestAdminSessions:
    async def test_sessions_endpoint_lists_active_count_after_init(
        self, async_client, admin_headers, valid_init_body
    ):
        """US-08 AC-1: admin sees recent search attempts; count > 0 after init."""
        init = await async_client.post("/api/v1/search/init", json=valid_init_body)
        if _stub_response(init):
            pytest.xfail("search.init is a skeleton (501)")

        resp = await async_client.get(
            "/api/v1/admin/sessions", headers=admin_headers,
        )
        if _stub_response(resp):
            pytest.xfail("admin.sessions is a skeleton (501)")
        assert resp.status_code == 200
        body = resp.json()
        assert "sessions" in body
        assert "count" in body
        assert body["count"] >= 1

    async def test_sessions_endpoint_never_returns_cookies_or_csrf(
        self, async_client, admin_headers, valid_init_body
    ):
        """SECURITY (STRATEGIES §1): cookies + CSRF tokens MUST NOT leak to admin.

        This is a LOAD-BEARING invariant — if it breaks, we're shipping a
        token-leak vulnerability. Pin it now even though impl is pending.
        """
        init = await async_client.post("/api/v1/search/init", json=valid_init_body)
        if _stub_response(init):
            pytest.xfail("search.init is a skeleton (501)")

        resp = await async_client.get(
            "/api/v1/admin/sessions", headers=admin_headers,
        )
        if _stub_response(resp):
            pytest.xfail("admin.sessions is a skeleton (501)")
        body_str = resp.text.lower()
        # No raw cookies. No CSRF. No CAPTCHA bytes.
        for forbidden in ("cookie", "csrf", "captcha_image_b64", "set-cookie"):
            assert forbidden not in body_str, (
                f"admin/sessions response leaked '{forbidden}' — SECURITY BUG. "
                f"Flag to Sneha + Arjun immediately."
            )

    async def test_sessions_endpoint_filters_by_status(
        self, async_client, admin_headers
    ):
        """API-CONTRACT §6.1: ?status filter is supported."""
        resp = await async_client.get(
            "/api/v1/admin/sessions?status=pending_captcha",
            headers=admin_headers,
        )
        if _stub_response(resp):
            pytest.xfail("admin.sessions is a skeleton (501)")
        assert resp.status_code == 200

    async def test_sessions_endpoint_clamps_limit_at_max(
        self, async_client, admin_headers
    ):
        """API-CONTRACT §6.1: limit default 50, max 500. Adversarial: 99999
        must NOT 500 — should clamp or reject gracefully."""
        resp = await async_client.get(
            "/api/v1/admin/sessions?limit=99999",
            headers=admin_headers,
        )
        if _stub_response(resp):
            pytest.xfail("admin.sessions is a skeleton (501)")
        # Either clamp (200) or reject (400/422). Never 500.
        assert resp.status_code in (200, 400, 422)


# ── /admin/failures ───────────────────────────────────────────────────────

class TestAdminFailures:
    async def test_failures_endpoint_returns_list_shape(
        self, async_client, admin_headers
    ):
        """API-CONTRACT §6.2: response has {failures: [], count: int}."""
        resp = await async_client.get(
            "/api/v1/admin/failures", headers=admin_headers,
        )
        if _stub_response(resp):
            pytest.xfail("admin.failures is a skeleton (501)")
        assert resp.status_code == 200
        body = resp.json()
        assert "failures" in body
        assert "count" in body
        assert isinstance(body["failures"], list)

    async def test_failures_endpoint_filters_by_code(
        self, async_client, admin_headers
    ):
        """API-CONTRACT §6.2: ?code filter for triage."""
        resp = await async_client.get(
            "/api/v1/admin/failures?code=court_error",
            headers=admin_headers,
        )
        if _stub_response(resp):
            pytest.xfail("admin.failures is a skeleton (501)")
        assert resp.status_code == 200
        # When filter is applied, every result MUST match the filter.
        for row in resp.json().get("failures", []):
            assert row.get("code") == "court_error"

    async def test_failures_endpoint_never_includes_pii(
        self, async_client, admin_headers
    ):
        """STRATEGIES §4: failures log MUST NOT include raw case_id, only
        case_id_hash. Pin the privacy invariant."""
        resp = await async_client.get(
            "/api/v1/admin/failures", headers=admin_headers,
        )
        if _stub_response(resp):
            pytest.xfail("admin.failures is a skeleton (501)")
        body = resp.json()
        for row in body.get("failures", []):
            assert "case_id" not in row, (
                "failures row leaked raw case_id. Per STRATEGIES §4 only "
                "case_id_hash is permitted at INFO+. Flag to Sneha + Arjun."
            )
            # raw cookies + tokens never appear
            for forbidden in ("cookies", "csrf_token", "captcha_image_b64"):
                assert forbidden not in row


# ── Kill-switch ───────────────────────────────────────────────────────────

class TestKillSwitch:
    async def test_kill_switch_flips_outbound_fetch_enabled_to_false(
        self, async_client, admin_headers, monkeypatch
    ):
        """G3-adjacent: a runtime kill-switch must halt outbound calls in <5min.

        The exact endpoint shape isn't in the API contract yet — it's
        owned by Sneha + Arjun. Two reasonable shapes:
          (a) POST /admin/kill-switch {enabled: false}
          (b) Env-var only (OUTBOUND_FETCH_ENABLED=false), reloaded via /admin/reload

        We probe (a) first, then fall back to env-var injection to verify
        the BEHAVIOUR (subsequent /init returns 503 with upstream_blocked or
        court_error) regardless of the trigger mechanism.
        """
        # Try the endpoint first
        kill = await async_client.post(
            "/api/v1/admin/kill-switch",
            json={"enabled": False},
            headers=admin_headers,
        )

        if kill.status_code in (404, 405):
            # Endpoint not implemented — exercise the env-var path instead.
            monkeypatch.setenv("OUTBOUND_FETCH_ENABLED", "false")
            from app.config import get_settings
            get_settings.cache_clear()
        elif _stub_response(kill):
            pytest.xfail(
                "admin.kill-switch endpoint pending (Sneha + Arjun's sprint)."
            )
        else:
            assert kill.status_code in (200, 204), (
                "Kill-switch endpoint must return 200/204 on success."
            )

        # After kill-switch is engaged, /init should refuse to call upstream.
        resp = await async_client.post("/api/v1/search/init", json={
            "case_type": "W.P.(C)", "case_number": "1", "year": 2024,
        })
        if _stub_response(resp):
            pytest.xfail(
                "search.init is a skeleton — kill-switch behaviour not "
                "observable until Arjun wires the outbound gate."
            )
        assert resp.status_code in (503,), (
            "When OUTBOUND_FETCH_ENABLED=false, /init MUST return 503 "
            "(upstream_blocked or service_unavailable). Got "
            f"{resp.status_code}: {resp.text[:200]}"
        )
