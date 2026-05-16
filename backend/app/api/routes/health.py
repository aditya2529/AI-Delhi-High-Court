"""Health + readiness endpoints. Used by container orchestrator + uptime check."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app import __version__

router = APIRouter()


@router.get("/health", summary="Liveness probe")
async def health() -> dict:
    """Liveness — process is responsive. Always 200 unless the app is on fire."""
    return {
        "status": "ok",
        "version": __version__,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready", summary="Readiness probe")
async def ready() -> dict:
    """Readiness — dependent systems (DB, session store) reachable.

    TODO (Arjun's sprint): poke DB + Redis + outbound DHC base URL with HEAD.
    For now: 200 unconditionally so the dev server doesn't fail container probes.
    """
    return {"status": "ok"}
