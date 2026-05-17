"""Admin observability endpoints — gated by a shared secret header (`X-Admin-Secret`).

This is a deliberately lightweight admin surface for MVP — no user accounts,
no RBAC. Real auth lands in v2 (OIDC/SAML — see Sneha's notes).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, Path as PathParam, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.search_request import SearchRequest
from app.runtime_flags import RuntimeFlags, get_flags
from app.services.dependencies import get_session_store
from app.sessions.store import InMemorySessionStore, SessionStore
from app.utils.errors import ApiError

router = APIRouter()

# Max matching lines we'll return from /audit/by-request — protects against
# pathological log files where the same id appears thousands of times.
_AUDIT_MAX_LINES = 500

# request_id values are minted as `uuid4().hex` (32 hex chars) or echoed
# verbatim from `X-Request-Id` (trimmed to 64 chars in
# ``app.utils.errors.get_or_mint_request_id``). We allow a generous safe
# alphabet: alnum + hyphen + underscore + dot. Anything else is rejected
# at the route boundary so we never grep with attacker-controlled regex
# metacharacters or path-separator chars.
_REQUEST_ID_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _require_admin(
    x_admin_secret: Optional[str] = Header(default=None, alias="X-Admin-Secret"),
    settings: Settings = Depends(get_settings),
) -> None:
    """Constant-time-ish secret check. Returns nothing; raises on mismatch."""
    if not x_admin_secret or x_admin_secret != settings.admin_shared_secret:
        raise ApiError(
            code="unauthorized",
            message="missing or invalid X-Admin-Secret header",
            http_status=401,
            retryable=False,
        )


# ─── Response shapes ──────────────────────────────────────────────────────


class ActiveSessionOut(BaseModel):
    session_id: str
    case_type: str
    case_number: str
    year: int
    created_at: datetime
    last_seen_at: datetime
    ttl_remaining_seconds: int


class ActiveSessionsResponse(BaseModel):
    sessions: list[ActiveSessionOut]
    count: int


class FailureOut(BaseModel):
    request_id: int
    occurred_at: datetime
    endpoint: str
    code: str
    case_type: str
    case_number: str
    year: int
    error_message: Optional[str]


class FailuresResponse(BaseModel):
    failures: list[FailureOut]
    count: int


class KillSwitchRequest(BaseModel):
    """Accepts either `outbound_fetch_enabled` (verbose) or `enabled` (short).

    Both spellings are honoured because the API contract didn't fix the
    name — Sneha owns this surface and we'd rather be permissive on input.
    """
    outbound_fetch_enabled: Optional[bool] = None
    enabled: Optional[bool] = None

    @property
    def effective(self) -> Optional[bool]:
        """Pick whichever field the caller supplied."""
        return (
            self.outbound_fetch_enabled
            if self.outbound_fetch_enabled is not None
            else self.enabled
        )


class KillSwitchResponse(BaseModel):
    outbound_fetch_enabled: bool
    note: str


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get(
    "/sessions",
    response_model=ActiveSessionsResponse,
    summary="List active sessions in the SessionStore",
    dependencies=[Depends(_require_admin)],
)
async def list_sessions(
    store: SessionStore = Depends(get_session_store),
    settings: Settings = Depends(get_settings),
) -> ActiveSessionsResponse:
    """Read-only dump of the in-memory session store.

    Sneha-mandated: NEVER returns upstream cookies or CSRF tokens.
    Only public-shape session metadata.
    """
    if not isinstance(store, InMemorySessionStore):
        raise ApiError(
            code="internal_error",
            message="session store is not introspectable in this build",
            http_status=500,
            retryable=False,
        )
    return _build_sessions_response(store, settings.session_ttl_seconds)


def _build_sessions_response(
    store: InMemorySessionStore, ttl_seconds: int
) -> ActiveSessionsResponse:
    """Pure-helper: walk the store dict, build the wire view."""
    now = time.time()
    sessions: list[ActiveSessionOut] = []
    # Read the private dict directly — same module-package as the store.
    for s in list(store._data.values()):  # noqa: SLF001
        ttl_remaining = max(0, int(ttl_seconds - (now - s.last_seen_at)))
        sessions.append(
            ActiveSessionOut(
                session_id=s.session_id,
                case_type=s.case_type,
                case_number=s.case_number,
                year=s.year,
                created_at=datetime.fromtimestamp(s.created_at, tz=timezone.utc),
                last_seen_at=datetime.fromtimestamp(
                    s.last_seen_at, tz=timezone.utc
                ),
                ttl_remaining_seconds=ttl_remaining,
            )
        )
    return ActiveSessionsResponse(sessions=sessions, count=len(sessions))


@router.get(
    "/failures",
    response_model=FailuresResponse,
    summary="Recent failed search_request rows (paginated)",
    dependencies=[Depends(_require_admin)],
)
async def list_failures(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    status_filter: Literal["failed", "expired"] = Query(
        default="failed", alias="status"
    ),
) -> FailuresResponse:
    """Paginated read of `search_request` rows where status indicates failure."""
    stmt = (
        select(SearchRequest)
        .where(SearchRequest.status == status_filter)
        .order_by(desc(SearchRequest.completed_at), desc(SearchRequest.id))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    failures = [_to_failure_out(row) for row in rows]
    return FailuresResponse(failures=failures, count=len(failures))


def _to_failure_out(row: SearchRequest) -> FailureOut:
    """SQLAlchemy row → wire shape. Inferred code from the error_message head."""
    code = "failed"
    if row.error_message:
        code = row.error_message.split(":", 1)[0].strip() or "failed"
    return FailureOut(
        request_id=row.id,
        occurred_at=row.completed_at or row.created_at,
        endpoint="/api/v1/search/submit",
        code=code,
        case_type=row.case_type,
        case_number=row.case_number,
        year=row.year,
        error_message=row.error_message,
    )


@router.post(
    "/kill-switch",
    response_model=KillSwitchResponse,
    summary="Flip OUTBOUND_FETCH_ENABLED at runtime",
    dependencies=[Depends(_require_admin)],
)
async def set_kill_switch(
    body: KillSwitchRequest,
    flags: RuntimeFlags = Depends(get_flags),
) -> KillSwitchResponse:
    """Toggle Sneha's outbound kill-switch. Effective immediately for any
    new outbound call. In-flight calls are NOT cancelled — the flag is
    checked at the start of each outbound op."""
    new_value = body.effective
    if new_value is None:
        raise ApiError(
            code="invalid_request",
            message="provide outbound_fetch_enabled or enabled as a boolean",
            http_status=400,
            retryable=False,
        )
    previous = flags.outbound_fetch_enabled
    flags.outbound_fetch_enabled = new_value
    return KillSwitchResponse(
        outbound_fetch_enabled=flags.outbound_fetch_enabled,
        note=f"outbound_fetch_enabled: {previous} -> {new_value}",
    )


# Make sure Any is imported even if unused — keeps mypy happy if we extend.
_ = Any


# ─── /admin/audit/by-request/{request_id} ─────────────────────────────────


class AuditByRequestResponse(BaseModel):
    """Lines from the rotating backend log file that mention a request id.

    Each entry is the raw log line as written to disk (JSON envelope from
    ``app.utils.logging._JsonOrPassthroughFormatter``). The endpoint does
    NOT parse the JSON — it greps and streams matching lines back. The
    caller can decode if they want; we keep it raw so a corrupt line
    (mid-rotation tear, partial write) never breaks the endpoint.
    """

    request_id: str
    log_file: str
    line_count: int
    truncated: bool
    lines: list[str]


@router.get(
    "/audit/by-request/{request_id}",
    response_model=AuditByRequestResponse,
    summary="Return backend log lines matching a request_id (grep over LOG_FILE_BACKEND).",
    dependencies=[Depends(_require_admin)],
)
async def audit_by_request_id(
    request_id: str = PathParam(
        ...,
        description=(
            "Request id minted by the backend (32-hex uuid4) or echoed "
            "from a client `X-Request-Id` header. Restricted to "
            "[A-Za-z0-9._-]{1,128} so we never grep with attacker-"
            "controlled regex metacharacters."
        ),
    ),
    settings: Settings = Depends(get_settings),
) -> AuditByRequestResponse:
    """Stream the backend log file, return lines containing ``request_id``.

    Why a grep over a file (and not a DB query):
      The file IS the audit log — see the rationale in ``app/utils/logging.py``.
      Adding a parallel DB table would just create a second source of
      truth that drifts. The endpoint is a convenience grep, capped at
      ``_AUDIT_MAX_LINES`` lines so a pathological match (a long-running
      request that emitted thousands of structured rows) can't blow up
      the response.

    503 if ``LOG_FILE_BACKEND`` is unset — we want the operator to know
    that file logging isn't even enabled, rather than silently returning
    an empty list.

    400 if the supplied ``request_id`` contains characters outside the
    safe alphabet. This is a defence-in-depth check; FastAPI's path
    converter already rejects ``/`` in path params.
    """
    log_file = settings.log_file_backend
    if not log_file:
        raise ApiError(
            code="service_unavailable",
            message=(
                "backend file logging is disabled (LOG_FILE_BACKEND empty). "
                "Cannot grep audit log."
            ),
            http_status=503,
            retryable=False,
            hint="set LOG_FILE_BACKEND in the backend env and restart.",
        )

    if not _REQUEST_ID_SAFE.match(request_id):
        raise ApiError(
            code="invalid_request",
            message="request_id contains unsupported characters.",
            http_status=400,
            retryable=False,
            hint="expected [A-Za-z0-9._-]{1,128}.",
        )

    matches, truncated = _grep_log_file(
        log_path=Path(log_file),
        needle=request_id,
        cap=_AUDIT_MAX_LINES,
    )
    return AuditByRequestResponse(
        request_id=request_id,
        log_file=log_file,
        line_count=len(matches),
        truncated=truncated,
        lines=matches,
    )


def _grep_log_file(
    *, log_path: Path, needle: str, cap: int
) -> tuple[list[str], bool]:
    """Stream-read ``log_path`` line by line, return up to ``cap`` matches.

    Returns ``(matches, truncated)`` where ``truncated`` is True iff we
    stopped because we hit the cap (more matches may exist on disk).

    A missing log file is treated as zero matches — the file may not
    exist yet on a freshly-booted backend that hasn't served a request.
    Permission errors propagate as a 503 ApiError so the operator sees
    them rather than getting a misleading empty list.
    """
    if not log_path.exists():
        return [], False

    matches: list[str] = []
    truncated = False
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as fp:
            for line in fp:
                if needle in line:
                    matches.append(line.rstrip("\n"))
                    if len(matches) >= cap:
                        # Peek one more byte to know whether we truncated.
                        truncated = bool(fp.read(1))
                        break
    except OSError as exc:
        raise ApiError(
            code="service_unavailable",
            message=f"could not read log file: {exc}",
            http_status=503,
            retryable=True,
            hint=str(log_path),
        ) from exc
    return matches, truncated
