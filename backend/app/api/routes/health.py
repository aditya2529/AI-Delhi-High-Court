"""Health + readiness endpoints. Used by container orchestrator + uptime check."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db.session import get_db
from app.runtime_flags import get_flags
from app.services.dependencies import get_session_store
from app.sessions.store import SessionStore
from app.utils.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checked_at: str


class ReadyChecks(BaseModel):
    db: Literal["ok", "fail"]
    session_store: Literal["ok", "fail"]
    outbound_fetch_enabled: bool


class ReadyResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: ReadyChecks


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Liveness — process is responsive. Always 200 unless the app is on fire."""
    return HealthResponse(
        status="ok",
        version=__version__,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/ready", response_model=ReadyResponse, summary="Readiness probe")
async def ready(
    db: AsyncSession = Depends(get_db),
    store: SessionStore = Depends(get_session_store),
) -> ReadyResponse:
    """Readiness — dependent systems reachable.

    Always 200; the body reports per-dependency status so the load
    balancer can decide what to do. 503 only if the app cannot serve
    a response at all (which means the process is gone, not degraded).
    """
    db_ok = await _check_db(db)
    store_ok = await _check_store(store)
    overall: Literal["ok", "degraded"] = (
        "ok" if (db_ok and store_ok) else "degraded"
    )
    return ReadyResponse(
        status=overall,
        checks=ReadyChecks(
            db="ok" if db_ok else "fail",
            session_store="ok" if store_ok else "fail",
            outbound_fetch_enabled=get_flags().outbound_fetch_enabled,
        ),
    )


async def _check_db(db: AsyncSession) -> bool:
    """Round-trip `SELECT 1` against the engine."""
    try:
        await db.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        log.warning("ready.db_check.fail", error=str(exc))
        return False


async def _check_store(store: SessionStore) -> bool:
    """Lightweight: any non-raising call to the store is enough."""
    try:
        # Calling get() on a sentinel key is the cheapest valid op.
        await store.get("__readiness_probe__")
        return True
    except Exception as exc:  # noqa: BLE001 — surface any store fault
        log.warning("ready.session_store.fail", error=str(exc))
        return False
