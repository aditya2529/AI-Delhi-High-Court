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

from pathlib import Path

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


# ── /admin/audit/by-request/{request_id} ───────────────────────────────────


class TestAuditByRequestId:
    """Contract for the post-incident audit-by-request-id endpoint.

    Background (founder, 2026-05-17): the first CLIENT_MODE=real run was
    impossible to debug because logs/backend/app.log was 0 bytes. The
    file handler now writes, request_id propagates, and this endpoint
    is the convenience grep tied to it.
    """

    def _wire_log_file(self, monkeypatch, tmp_path) -> Path:
        """Point LOG_FILE_BACKEND at a tmp file and clear the settings cache."""
        log_file = tmp_path / "app.log"
        monkeypatch.setenv("LOG_FILE_BACKEND", str(log_file))
        from app.config import get_settings
        get_settings.cache_clear()
        return log_file

    async def test_audit_endpoint_rejects_missing_secret(
        self, async_client, monkeypatch, tmp_path
    ):
        """Auth gate parity with the other admin endpoints."""
        self._wire_log_file(monkeypatch, tmp_path)
        resp = await async_client.get(
            "/api/v1/admin/audit/by-request/deadbeef"
        )
        assert resp.status_code in (401, 403, 404), (
            f"missing admin secret must NOT be 200; got {resp.status_code}"
        )

    async def test_audit_endpoint_rejects_wrong_secret(
        self, async_client, monkeypatch, tmp_path
    ):
        self._wire_log_file(monkeypatch, tmp_path)
        resp = await async_client.get(
            "/api/v1/admin/audit/by-request/deadbeef",
            headers={"X-Admin-Secret": "nope"},
        )
        assert resp.status_code in (401, 403)

    async def test_audit_endpoint_returns_matching_lines(
        self, async_client, admin_headers, monkeypatch, tmp_path
    ):
        """Grep behaviour: only lines containing the request_id come back."""
        log_file = self._wire_log_file(monkeypatch, tmp_path)
        rid = "b1704a5cfeedface0000000000000001"
        other = "0000000000000000000000000000aaaa"
        log_file.write_text(
            "\n".join([
                f'{{"ts":"2026-05-17T10:00:00Z","level":"INFO","logger":"app.startup","request_id":"-","message":"startup.ready"}}',
                f'{{"ts":"2026-05-17T10:00:01Z","level":"INFO","logger":"app.api","request_id":"{rid}","message":"search.init.ok"}}',
                f'{{"ts":"2026-05-17T10:00:02Z","level":"INFO","logger":"app.api","request_id":"{other}","message":"search.init.ok"}}',
                f'{{"ts":"2026-05-17T10:00:03Z","level":"WARNING","logger":"app.svc","request_id":"{rid}","message":"search.submit.no_audit_row"}}',
                "",
            ]),
            encoding="utf-8",
        )

        resp = await async_client.get(
            f"/api/v1/admin/audit/by-request/{rid}",
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["request_id"] == rid
        assert body["line_count"] == 2
        assert body["truncated"] is False
        # The two matching lines come back verbatim, no parsing.
        joined = "\n".join(body["lines"])
        assert "search.init.ok" in joined
        assert "search.submit.no_audit_row" in joined
        # The non-matching lines do NOT come back.
        assert other not in joined

    async def test_audit_endpoint_503_when_log_file_unset(
        self, async_client, admin_headers, monkeypatch
    ):
        """Operator-visible failure mode when file logging is disabled."""
        monkeypatch.setenv("LOG_FILE_BACKEND", "")
        from app.config import get_settings
        get_settings.cache_clear()

        resp = await async_client.get(
            "/api/v1/admin/audit/by-request/deadbeef",
            headers=admin_headers,
        )
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == "service_unavailable"
        assert "LOG_FILE_BACKEND" in body["error"]["message"]

    async def test_audit_endpoint_caps_at_500_lines(
        self, async_client, admin_headers, monkeypatch, tmp_path
    ):
        """Pathological grep: 1000 matching lines → 500 returned, truncated=True."""
        log_file = self._wire_log_file(monkeypatch, tmp_path)
        rid = "f" * 32
        # 1000 matching lines + a few non-matchers as noise.
        lines = []
        for i in range(1000):
            lines.append(
                f'{{"ts":"2026-05-17T10:00:00Z","level":"INFO","logger":"app.x","request_id":"{rid}","message":"event-{i}"}}'
            )
        log_file.write_text("\n".join(lines), encoding="utf-8")

        resp = await async_client.get(
            f"/api/v1/admin/audit/by-request/{rid}",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["line_count"] == 500
        assert body["truncated"] is True

    async def test_audit_endpoint_rejects_unsafe_request_id(
        self, async_client, admin_headers, monkeypatch, tmp_path
    ):
        """Defence-in-depth: regex metacharacters / path traversal rejected."""
        self._wire_log_file(monkeypatch, tmp_path)
        # FastAPI's path converter rejects `/` outright (404 from the
        # router), but `.*` would otherwise be a valid path segment and
        # we want our alphabet check to bounce it.
        resp = await async_client.get(
            "/api/v1/admin/audit/by-request/.*",
            headers=admin_headers,
        )
        # 400 from our validator. Some routers may 404 before reaching us
        # for very hostile inputs — either is acceptable as long as we
        # don't 200 with the entire log file.
        assert resp.status_code in (400, 404, 422)
        if resp.status_code == 400:
            assert resp.json()["error"]["code"] == "invalid_request"

    async def test_audit_endpoint_empty_when_log_file_missing(
        self, async_client, admin_headers, monkeypatch, tmp_path
    ):
        """Freshly-booted backend: log file not yet created → empty result, not 500."""
        log_file = tmp_path / "subdir" / "app.log"  # parent doesn't exist either
        monkeypatch.setenv("LOG_FILE_BACKEND", str(log_file))
        from app.config import get_settings
        get_settings.cache_clear()

        resp = await async_client.get(
            "/api/v1/admin/audit/by-request/anything",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["line_count"] == 0
        assert body["lines"] == []


# ── File-logging smoke (DoD #1): hit any endpoint, assert file is non-empty ──


class TestFileLoggingDoD:
    """The founder's gate: after the test client hits an endpoint, the
    rotating file at LOG_FILE_BACKEND must exist and have content.

    This is the regression test for the 0-byte ``logs/backend/app.log``
    incident on 2026-05-17. If this ever fails again, debugging the next
    CLIENT_MODE=real run becomes impossible.
    """

    async def _rewire_log_file(self, monkeypatch, tmp_path) -> Path:
        """Set LOG_FILE_BACKEND to a fresh tmp file and re-run
        ``configure_logging`` so the rotating handler points at it.

        The ``async_client`` fixture already called ``configure_logging``
        during setup, but it used whatever ``LOG_FILE_BACKEND`` was on
        ``_test_env`` (some other tmp file). Tests that want to assert
        ON a specific file must re-wire after changing the env.
        """
        log_file = tmp_path / "app.log"
        monkeypatch.setenv("LOG_FILE_BACKEND", str(log_file))
        from app.config import get_settings
        from app.utils.logging import configure_logging
        get_settings.cache_clear()
        s = get_settings()
        configure_logging(
            log_level=s.app_log_level,
            log_file=s.log_file_backend,
            log_file_outbound=s.log_file_outbound,
        )
        return log_file

    async def test_log_file_written_after_request(
        self, async_client, monkeypatch, tmp_path
    ):
        log_file = await self._rewire_log_file(monkeypatch, tmp_path)

        # /search/init emits a structured ``search.init.ok`` log line via
        # ``app.services.search_service`` once a request lands. That's the
        # log row the founder needs in the file.
        init = await async_client.post(
            "/api/v1/search/init",
            json={"case_type": "W.P.(C)", "case_number": "12345", "year": 2024},
        )
        # We don't care whether init succeeds end-to-end; we only need it
        # to fire at least one log line through the configured handlers.
        assert init.status_code in (200, 422, 500, 503)

        # Force handler flush — the rotating file handler buffers in
        # Python's io layer; on Windows the read below sees an empty file
        # if the handler hasn't flushed by the time we look.
        import logging as _logging
        for h in _logging.getLogger().handlers:
            try:
                h.flush()
            except Exception:  # noqa: BLE001
                pass

        assert log_file.exists(), (
            f"LOG_FILE_BACKEND={log_file} was not created. "
            "The rotating file handler is not wired."
        )
        size = log_file.stat().st_size
        assert size > 0, (
            f"LOG_FILE_BACKEND={log_file} is 0 bytes after a real request — "
            "the founder's incident is back."
        )

    async def test_request_id_propagated_into_log_lines(
        self, async_client, monkeypatch, tmp_path
    ):
        """Hand the backend an X-Request-Id; assert it lands in the file.

        Uses ``/api/v1/search/init`` because that route emits a
        ``search.init.ok`` structured log line via
        ``app.services.search_service.start_search_session`` — the
        canonical structured-log row the founder needed to trace the
        failed real-mode run by request id.
        """
        log_file = await self._rewire_log_file(monkeypatch, tmp_path)

        rid = "test-rid-" + "a" * 16
        resp = await async_client.post(
            "/api/v1/search/init",
            json={"case_type": "W.P.(C)", "case_number": "12345", "year": 2024},
            headers={"X-Request-Id": rid},
        )
        # Response header round-trips regardless of body status.
        assert resp.headers.get("X-Request-Id") == rid

        # Flush handlers before reading the file (rotating handler buffers
        # in Python's io layer; without an explicit flush a Windows read
        # can race the OS-level write).
        import logging as _logging
        for h in _logging.getLogger().handlers:
            try:
                h.flush()
            except Exception:  # noqa: BLE001
                pass

        contents = log_file.read_text(encoding="utf-8", errors="replace")
        assert rid in contents, (
            f"request_id={rid!r} was not propagated into log lines. "
            "_RequestIdFilter / structlog contextvars binding is broken. "
            f"Init responded {resp.status_code}: {resp.text[:200]!r}. "
            f"File contents (first 1000 chars): {contents[:1000]!r}"
        )
