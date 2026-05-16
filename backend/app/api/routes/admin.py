"""Admin observability endpoints — gated by a shared secret header (`X-Admin-Secret`).

This is a deliberately lightweight admin surface for MVP — no user accounts,
no RBAC. Real auth lands in v2.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config import Settings, get_settings

router = APIRouter()


def _require_admin(
    x_admin_secret: str | None = Header(default=None, alias="X-Admin-Secret"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not x_admin_secret or x_admin_secret != settings.admin_shared_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid X-Admin-Secret header",
        )


@router.get("/sessions", summary="Active session list", dependencies=[Depends(_require_admin)])
async def list_sessions() -> dict:
    """TODO: list of active sessions with TTL + last-seen timestamp."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="admin.sessions pending implementation",
    )


@router.get("/failures", summary="Recent failed requests", dependencies=[Depends(_require_admin)])
async def list_failures() -> dict:
    """TODO: paginated list of failed searches with reason code + retry counts."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="admin.failures pending implementation",
    )
