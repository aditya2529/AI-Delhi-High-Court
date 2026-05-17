"""Search endpoints — public API for the case-status flow.

These translate HTTP <-> service-layer calls. Real business logic lives in
`app.services.search_service`. Errors raised as `ApiError` are converted to
the canonical envelope by the middleware in `app.main`.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.in_memory_case_cache import InMemoryCaseCache
from app.clients.court_client import (
    CourtClient,
    CourtClientError,
    OutboundDisabledError,
)
from app.config import Settings, get_settings
from app.db.session import get_db
from app.parsers.case_parser import DHCParserV1
from app.schemas.search import (
    RefreshCaptchaResponse,
    SearchInitRequest,
    SearchInitResponse,
    SearchSubmitRequest,
    SearchSubmitResponse,
)
from app.services.dependencies import (
    get_case_cache,
    get_case_parser,
    get_court_client,
    get_session_store,
)
from app.services.search_service import (
    refresh_session_captcha,
    start_search_session,
    submit_search,
)
from app.sessions.store import SessionStore
from app.utils.errors import ApiError

router = APIRouter()


def _client_ip(request: Request) -> str:
    """Pull the client's IP. Trusts X-Forwarded-For first hop in dev. Real
    deployments must put a TLS terminator that scrubs hop-by-hop, OR
    we move to a trusted-proxy list in middleware."""
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


@router.post("/init", response_model=SearchInitResponse, summary="Open session + fetch CAPTCHA")
async def search_init(
    body: SearchInitRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    store: SessionStore = Depends(get_session_store),
    client: CourtClient = Depends(get_court_client),
    settings: Settings = Depends(get_settings),
) -> SearchInitResponse:
    """Initialise a search session and ship back the CAPTCHA image.

    The COURT_ERROR fixture is now selected via `case_number == 'COURT_ERROR'`
    inside FakeCourtClient (see `app/clients/fake_court_client.py`). Pydantic's
    `case_number` validator enforces `^\\d{1,7}$`, so a year-based short-circuit
    here is no longer needed and was removed (was a smell — selectors must be
    explicit, not derived from in-band data).
    """
    try:
        return await start_search_session(
            db=db,
            store=store,
            client=client,
            case_type=body.case_type,
            case_number=body.case_number.lstrip("0") or "0",
            year=body.year,
            client_ip=_client_ip(request),
            captcha_ttl_seconds=settings.session_captcha_ttl_seconds,
            session_ttl_seconds=settings.session_ttl_seconds,
        )
    except OutboundDisabledError as exc:
        raise ApiError(
            code="upstream_blocked",
            message="outbound fetching is currently disabled",
            http_status=503,
            retryable=False,
            hint="The site operator has paused outbound calls. Try again later.",
        ) from exc
    except CourtClientError as exc:
        raise ApiError(
            code="court_error",
            message="upstream court site is unreachable",
            http_status=503,
            retryable=True,
            hint=str(exc)[:200],
        ) from exc


@router.post(
    "/submit",
    response_model=SearchSubmitResponse,
    summary="Submit CAPTCHA answer + return parsed result",
)
async def search_submit(
    body: SearchSubmitRequest,
    db: AsyncSession = Depends(get_db),
    store: SessionStore = Depends(get_session_store),
    client: CourtClient = Depends(get_court_client),
    parser: DHCParserV1 = Depends(get_case_parser),
    cache: InMemoryCaseCache = Depends(get_case_cache),
) -> SearchSubmitResponse:
    """Submit the user's typed CAPTCHA. Returns a 200 body with
    status=success|captcha_failed|expired|not_found|court_error.

    Missing-session handling: we return body-level `status=expired`
    (200) rather than a 404 envelope. The user has already typed a
    CAPTCHA; telling them their session timed out is friendlier than
    a generic "unknown session" error. The frontend then calls /init
    again — same UX as the documented `retry_url` flow.

    GREEN-ZONE: on success, parsed result is written to the in-memory
    `cache` only. No DB row stores court data.
    """
    # Schema validates session_id as a UUID; downstream services key the
    # store by string. Normalise once at the boundary.
    session_id_str = str(body.session_id)
    resp = await submit_search(
        db=db,
        store=store,
        client=client,
        parser=parser,
        cache=cache,
        session_id=session_id_str,
        captcha_text=body.captcha_text.strip(),
    )
    if resp is None:
        # Distinguish "was once valid but TTL'd" from "never existed".
        # The former is body-level expired (per API-CONTRACT §3 retry_url
        # flow); the latter is 404 (unknown opaque id).
        if hasattr(store, "was_recently_evicted") and store.was_recently_evicted(session_id_str):
            return SearchSubmitResponse(
                status="expired",
                retry_url="/api/v1/search/init",
            )
        raise ApiError(
            code="session_not_found",
            message="session is unknown or has expired",
            http_status=404,
            retryable=False,
            hint="Call /api/v1/search/init to start a new session.",
        )
    return resp


@router.get(
    "/{session_id}/refresh-captcha",
    response_model=RefreshCaptchaResponse,
    summary="Refresh the CAPTCHA image without losing form state",
)
async def refresh_captcha(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    store: SessionStore = Depends(get_session_store),
    client: CourtClient = Depends(get_court_client),
    settings: Settings = Depends(get_settings),
) -> RefreshCaptchaResponse:
    """Fetch a fresh CAPTCHA on the existing session. Form fields stay.

    `session_id` is validated as RFC 4122 UUID v4 by FastAPI's path
    converter — a malformed id never reaches the service layer.
    """
    payload = await refresh_session_captcha(
        db=db,
        store=store,
        client=client,
        session_id=str(session_id),
        captcha_ttl_seconds=settings.session_captcha_ttl_seconds,
        session_ttl_seconds=settings.session_ttl_seconds,
    )
    if payload is None:
        raise ApiError(
            code="session_not_found",
            message="session is unknown or has expired",
            http_status=404,
            retryable=False,
            hint="Call /api/v1/search/init to start a new session.",
        )
    return RefreshCaptchaResponse(**payload.model_dump())
