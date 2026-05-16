"""Integration tests for `/health` and `/ready` endpoints.

Maps to PRD §11 ("MVP success criteria") implicitly — uptime probes are
how the orchestrator (and on-call) know the app is alive.

These work against the current skeleton (the routes are implemented).
"""
from __future__ import annotations

import pytest


class TestHealth:
    async def test_health_returns_200(self, async_client):
        """Liveness probe must always return 200 while the process is up.

        Maps to: API-CONTRACT §5.
        """
        resp = await async_client.get("/api/v1/health")
        assert resp.status_code == 200

    async def test_health_returns_status_ok_and_version(self, async_client):
        """API-CONTRACT §5: body must include `status` and `version`."""
        resp = await async_client.get("/api/v1/health")
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert isinstance(body["version"], str)

    async def test_health_does_not_require_auth(self, async_client):
        """Probe is public — no admin secret needed."""
        resp = await async_client.get("/api/v1/health")
        assert resp.status_code != 401


class TestReady:
    async def test_ready_returns_200_when_dependencies_up(self, async_client):
        """Readiness probe — DB + session store reachable."""
        resp = await async_client.get("/api/v1/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") in {"ok", "ready"}

    async def test_ready_returns_503_when_db_unreachable(
        self, async_client, monkeypatch
    ):
        """API-CONTRACT §5: 503 only when app cannot serve at all.

        The readiness route is a skeleton today — once Arjun wires real DB
        checks, this test asserts the failure surface. Marked xfail (not
        skip) so the test SHOWS UP in the report as a known gap until the
        readiness check is wired.
        """
        # When the readiness route polls the DB, we'll inject a failing
        # connection here. For now we assert the contract intent so the gap
        # is visible in CI output.
        resp = await async_client.get("/api/v1/ready")
        if resp.status_code == 200:
            pytest.xfail(
                "Readiness route is a stub (Arjun's sprint). "
                "Real DB poke + 503 path pending — flagged to Arjun."
            )
        assert resp.status_code == 503
