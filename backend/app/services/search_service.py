"""Search service — orchestrates the CAPTCHA round-trip.

Pulls together: SessionStore (cookies + form state), CourtClient (outbound
to court site or fake), DHCParserV1 (HTML -> ParsedCase), and the
SQLAlchemy models (audit trail + result cache).

Keep route handlers thin — all the business logic lives here.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.court_client import (
    CaptchaFetchResult,
    CaptchaIncorrectError,
    CaseSearchResult,
    CourtClient,
    CourtClientError,
    OutboundDisabledError,
)
from app.clients.fake_court_client import b64_image
from app.models.case_order import CaseOrder
from app.models.case_party import CaseParty
from app.models.outbound_request_log import OutboundRequestLog
from app.models.parsed_case import ParsedCase as ParsedCaseRow
from app.models.parser_version import ParserVersion
from app.models.search_request import SearchRequest
from app.parsers.case_parser import (
    PARSE_OUTCOME_CAPTCHA_FAILED,
    PARSE_OUTCOME_COURT_ERROR,
    PARSE_OUTCOME_NOT_FOUND,
    PARSE_OUTCOME_SUCCESS,
    DHCParserV1,
    ParsedCase,
    ParseOutcome,
)
from app.schemas.search import (
    CaptchaPayload,
    ParsedCaseOut,
    ParsedCaseParties,
    ParsedOrderOut,
    SearchInitResponse,
    SearchSubmitResponse,
)
from app.sessions.store import CourtSession, SessionStore
from app.utils.logging import get_logger

log = get_logger(__name__)

# How many CAPTCHA attempts a session may make before we force a refresh.
MAX_CAPTCHA_ATTEMPTS = 3


def _hash_ip(client_ip: str) -> str:
    """Privacy-preserving IP hash. We don't have a rotated secret in
    MVP — `change-me-before-deploy` placeholder is acceptable for the
    fake-only path; Sneha to swap to HMAC w/ rotated key before launch."""
    return hashlib.sha256(client_ip.encode("utf-8")).hexdigest()


# ─── /search/init ──────────────────────────────────────────────────────────


async def start_search_session(
    *,
    db: AsyncSession,
    store: SessionStore,
    client: CourtClient,
    case_type: str,
    case_number: str,
    year: int,
    client_ip: str,
    captcha_ttl_seconds: int,
    session_ttl_seconds: int,
) -> SearchInitResponse:
    """Open an upstream session, fetch CAPTCHA, persist audit row."""
    search_req = await _new_search_request(
        db, case_type, case_number, year, client_ip
    )
    captcha = await _open_upstream_session(
        db=db, client=client, search_req_id=search_req.id,
        case_type=case_type, case_number=case_number, year=year,
    )
    session = await _persist_session_state(
        store=store, captcha=captcha,
        case_type=case_type, case_number=case_number, year=year,
    )

    now = datetime.now(timezone.utc)
    search_req.status = "captcha_displayed"
    search_req.captcha_displayed_at = now
    search_req.captcha_token = captcha.upstream_token[:64]

    log.info(
        "search.init.ok",
        search_request_id=search_req.id,
        session_id=session.session_id,
        case_type=case_type, case_number=case_number, year=year,
    )
    return SearchInitResponse(
        session_id=session.session_id,
        captcha_image_b64=b64_image(captcha.image_bytes),
        captcha_mime=captcha.image_mime,
        captcha_expires_at=now + timedelta(seconds=captcha_ttl_seconds),
        session_expires_at=now + timedelta(seconds=session_ttl_seconds),
    )


async def _new_search_request(
    db: AsyncSession,
    case_type: str,
    case_number: str,
    year: int,
    client_ip: str,
) -> SearchRequest:
    """Insert the initial audit row and return it (flushed; id assigned)."""
    row = SearchRequest(
        case_type=case_type,
        case_number=case_number,
        year=year,
        user_ip_hash=_hash_ip(client_ip),
        status="initialized",
    )
    db.add(row)
    await db.flush()
    assert row.id is not None
    return row


async def _open_upstream_session(
    *,
    db: AsyncSession,
    client: CourtClient,
    search_req_id: int,
    case_type: str,
    case_number: str,
    year: int,
) -> CaptchaFetchResult:
    """Two upstream calls + their outbound-log rows."""
    await client.init_session(
        case_type=case_type, case_number=case_number, year=year
    )
    await _log_outbound(
        db, search_req_id, method="GET",
        url="(fake)/case-status", status_code=200,
    )
    captcha = await client.fetch_captcha(
        session=_blank_session(case_type, case_number, year)
    )
    await _log_outbound(
        db, search_req_id, method="GET",
        url="(fake)/captcha.png", status_code=200,
        size=len(captcha.image_bytes),
    )
    return captcha


async def _persist_session_state(
    *,
    store: SessionStore,
    case_type: str,
    case_number: str,
    year: int,
    captcha: CaptchaFetchResult,
) -> CourtSession:
    """Create + populate + put the SessionStore entry."""
    session = await store.create(case_type, case_number, year)
    session.csrf_tokens["upstream_token"] = captcha.upstream_token
    session.captcha_image_bytes = captcha.image_bytes
    session.captcha_fetched_at = captcha.fetched_at_unix
    await store.put(session)
    return session


def _blank_session(case_type: str, case_number: str, year: int) -> CourtSession:
    """Pre-store stub so we can call fetch_captcha before the store entry
    exists. The fake client only reads case fields off it."""
    from app.sessions.store import CourtSession as _CS  # avoid circular
    s = _CS(session_id="pre-init")
    s.case_type = case_type
    s.case_number = case_number
    s.year = year
    return s


# ─── /search/refresh-captcha ───────────────────────────────────────────────


async def refresh_session_captcha(
    *,
    db: AsyncSession,
    store: SessionStore,
    client: CourtClient,
    session_id: str,
    captcha_ttl_seconds: int,
    session_ttl_seconds: int,
) -> Optional[CaptchaPayload]:
    """Re-fetch CAPTCHA bytes on an existing session. Returns None if the
    session is unknown — caller maps to 404."""
    session = await store.get(session_id)
    if session is None:
        return None

    captcha = await client.fetch_captcha(session=session)
    await _log_outbound(
        db, None, method="GET", url="(fake)/captcha.png",
        status_code=200, size=len(captcha.image_bytes),
    )

    session.captcha_image_bytes = captcha.image_bytes
    session.captcha_fetched_at = captcha.fetched_at_unix
    session.csrf_tokens["upstream_token"] = captcha.upstream_token
    await store.put(session)

    now = datetime.now(timezone.utc)
    return CaptchaPayload(
        captcha_image_b64=b64_image(captcha.image_bytes),
        captcha_mime=captcha.image_mime,
        captcha_expires_at=now + timedelta(seconds=captcha_ttl_seconds),
        session_expires_at=now + timedelta(seconds=session_ttl_seconds),
    )


# ─── /search/submit ────────────────────────────────────────────────────────


async def submit_search(
    *,
    db: AsyncSession,
    store: SessionStore,
    client: CourtClient,
    parser: DHCParserV1,
    session_id: str,
    captcha_text: str,
) -> Optional[SearchSubmitResponse]:
    """Submit upstream + parse + persist.

    Returns None if the session is unknown (route maps to 404).
    Otherwise returns a fully-formed SearchSubmitResponse with the
    body-level `status` set.
    """
    session = await store.get(session_id)
    if session is None:
        return None

    search_req = await _latest_search_request_for(
        db, session.case_type, session.case_number, session.year
    )
    if search_req is None:
        # Should not happen — we always create one in /init. Be defensive.
        log.warning("search.submit.no_audit_row", session_id=session_id)
        return None

    search_req.status = "submitted"
    search_req.submitted_at = datetime.now(timezone.utc)

    outcome = await _call_upstream_submit(
        db=db, client=client, session=session,
        search_req=search_req, captcha_text=captcha_text,
    )
    if isinstance(outcome, SearchSubmitResponse):
        return outcome  # early-exit on captcha/court/outbound failure

    return await _parse_and_persist(
        db=db, store=store, parser=parser,
        session=session, search_req=search_req, result=outcome,
    )


async def _call_upstream_submit(
    *,
    db: AsyncSession,
    client: CourtClient,
    session: CourtSession,
    search_req: SearchRequest,
    captcha_text: str,
) -> CaseSearchResult | SearchSubmitResponse:
    """Wraps the client.submit_search call + maps errors to envelopes.

    Returns a CaseSearchResult on the happy path; a SearchSubmitResponse
    when we need to short-circuit (captcha_failed / court_error).
    """
    try:
        result = await client.submit_search(
            session=session, captcha_text=captcha_text
        )
    except CaptchaIncorrectError:
        await _log_outbound(
            db, search_req.id, method="POST",
            url="(fake)/submit", status_code=200, error="captcha_failed",
        )
        return _handle_captcha_failed(search_req=search_req)
    except (OutboundDisabledError, CourtClientError) as exc:
        code = (
            "outbound_disabled" if isinstance(exc, OutboundDisabledError)
            else "court_error"
        )
        await _finalise_failure(db, search_req, code, str(exc))
        await _log_outbound(
            db, search_req.id, method="POST",
            url="(fake)/submit", status_code=None, error=code,
        )
        return SearchSubmitResponse(status="court_error")

    await _log_outbound(
        db, search_req.id, method="POST",
        url="(fake)/submit", status_code=200, size=len(result.raw_html),
    )
    return result


async def _parse_and_persist(
    *,
    db: AsyncSession,
    store: SessionStore,
    parser: DHCParserV1,
    session: CourtSession,
    search_req: SearchRequest,
    result: CaseSearchResult,
) -> SearchSubmitResponse:
    """Parse upstream HTML, branch on outcome, persist rows."""
    outcome: ParseOutcome = parser.parse_with_outcome(
        result.raw_html,
        source_url=result.source_url,
        case_type=session.case_type,
        case_number=session.case_number,
        year=session.year,
    )

    if outcome.outcome in (PARSE_OUTCOME_NOT_FOUND, PARSE_OUTCOME_COURT_ERROR):
        await _finalise_failure(db, search_req, outcome.outcome, None)
        await store.delete(session.session_id)
        return SearchSubmitResponse(status=outcome.outcome)  # type: ignore[arg-type]

    if outcome.outcome == PARSE_OUTCOME_CAPTCHA_FAILED:
        return _handle_captcha_failed(search_req=search_req)

    assert outcome.outcome == PARSE_OUTCOME_SUCCESS and outcome.case is not None
    return await _finalise_success(
        db=db, store=store,
        session=session, search_req=search_req, outcome=outcome,
    )


async def _finalise_success(
    *,
    db: AsyncSession,
    store: SessionStore,
    session: CourtSession,
    search_req: SearchRequest,
    outcome: ParseOutcome,
) -> SearchSubmitResponse:
    """Success terminal: persist parsed_case, mark audit row, drop session."""
    assert outcome.case is not None
    parsed_row = await _persist_parsed_case(db, outcome.case)
    search_req.status = "success"
    search_req.parsed_case_id = parsed_row.id
    search_req.completed_at = datetime.now(timezone.utc)
    await store.delete(session.session_id)
    return SearchSubmitResponse(
        status="success",
        result=_to_wire(
            outcome.case, parser_version_id=parsed_row.parser_version_id
        ),
        parser_degraded=outcome.parser_degraded,
    )


def _handle_captcha_failed(*, search_req: SearchRequest) -> SearchSubmitResponse:
    """Centralised captcha-failed handling. Does NOT delete the session —
    the user may retry."""
    # We don't store attempts on SearchRequest (no column) — keep on the
    # in-memory session if we want it. For MVP, just return a constant.
    search_req.status = "failed"
    search_req.error_message = "captcha_failed"
    search_req.completed_at = datetime.now(timezone.utc)
    return SearchSubmitResponse(
        status="captcha_failed",
        attempts_remaining=MAX_CAPTCHA_ATTEMPTS - 1,
    )


async def _finalise_failure(
    db: AsyncSession,
    search_req: SearchRequest,
    code: str,
    message: Optional[str],
) -> None:
    """Mark the audit row as failed. Single mutation point so the FSM
    stays consistent."""
    _ = db  # included for callers that may need it later
    search_req.status = "failed"
    search_req.completed_at = datetime.now(timezone.utc)
    search_req.error_message = f"{code}: {message}" if message else code


async def _latest_search_request_for(
    db: AsyncSession, case_type: str, case_number: str, year: int
) -> Optional[SearchRequest]:
    """Fetch the most-recent search_request matching this case tuple
    that is still in `captcha_displayed` or `submitted` state."""
    stmt = (
        select(SearchRequest)
        .where(
            SearchRequest.case_type == case_type,
            SearchRequest.case_number == case_number,
            SearchRequest.year == year,
            SearchRequest.status.in_(("captcha_displayed", "initialized")),
        )
        .order_by(SearchRequest.id.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def _persist_parsed_case(
    db: AsyncSession, case: ParsedCase
) -> ParsedCaseRow:
    """Upsert parsed_case + parties + orders. Cache TTL 24h."""
    parser_row = await _ensure_parser_version_row(db, case.parser_version)
    await _evict_existing_parsed_case(db, case)

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=86_400)
    row = ParsedCaseRow(
        case_type=case.case_type,
        case_number=case.case_number,
        year=case.year,
        court_case_id=None,
        status=case.status,
        filing_date=None,
        next_hearing_date=case.next_hearing_date,
        raw_html_ref=case.raw_html_hash,
        parser_version_id=parser_row.id,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()  # need row.id for child FKs

    _add_party_rows(db, row.id, case.parties)
    _add_order_rows(db, row.id, case.orders, case.judgments)

    await db.flush()
    return row


async def _evict_existing_parsed_case(
    db: AsyncSession, case: ParsedCase
) -> None:
    """Delete-and-insert: the natural-key unique constraint forbids
    a second row for the same case tuple. Cascades remove parties/orders."""
    existing = await db.execute(
        select(ParsedCaseRow).where(
            ParsedCaseRow.case_type == case.case_type,
            ParsedCaseRow.case_number == case.case_number,
            ParsedCaseRow.year == case.year,
        )
    )
    old_row = existing.scalar_one_or_none()
    if old_row is not None:
        await db.delete(old_row)
        await db.flush()


def _add_party_rows(
    db: AsyncSession, parsed_case_id: int, parties: list
) -> None:
    """Skip roles outside the (petitioner, respondent) check constraint."""
    for idx, p in enumerate(parties):
        if p.role not in ("petitioner", "respondent"):
            continue
        db.add(
            CaseParty(
                parsed_case_id=parsed_case_id,
                role=p.role,
                name=p.name,
                advocate=None,
                display_order=idx,
            )
        )


def _add_order_rows(
    db: AsyncSession, parsed_case_id: int, orders: list, judgments: list
) -> None:
    """Both orders and judgments land in `case_order` — `case_order` doesn't
    distinguish; we collapse for v1."""
    for o in (*orders, *judgments):
        db.add(
            CaseOrder(
                parsed_case_id=parsed_case_id,
                title=o.title[:512],
                order_date=o.order_date or None,
                pdf_url=(o.url or "")[:1024] or "(none)",
            )
        )


async def _ensure_parser_version_row(
    db: AsyncSession, version_string: str
) -> ParserVersion:
    """Find-or-create the parser_version row for the parser revision."""
    res = await db.execute(
        select(ParserVersion).where(ParserVersion.version == version_string)
    )
    existing = res.scalar_one_or_none()
    if existing is not None:
        return existing

    pv = ParserVersion(
        version=version_string,
        git_sha="local-dev",
        is_current=True,
        notes="auto-created by search_service on first parse",
    )
    db.add(pv)
    await db.flush()
    return pv


async def _log_outbound(
    db: AsyncSession,
    search_request_id: Optional[int],
    *,
    method: str,
    url: str,
    status_code: Optional[int] = None,
    size: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """Append a row to `outbound_request_log`. Even fake calls log here so
    when we go live the observability is already in place."""
    db.add(
        OutboundRequestLog(
            search_request_id=search_request_id,
            method=method,
            url=url[:1024],
            response_status=status_code,
            response_size_bytes=size,
            latency_ms=None,
            error_message=error,
        )
    )


def _to_wire(case: ParsedCase, *, parser_version_id: int) -> ParsedCaseOut:
    """Translate the internal ParsedCase dataclass to the wire schema."""
    petitioners = [p.name for p in case.parties if p.role == "petitioner"]
    respondents = [p.name for p in case.parties if p.role == "respondent"]
    return ParsedCaseOut(
        case_id=case.case_id,
        case_type=case.case_type,
        case_number=case.case_number,
        year=case.year,
        parties=ParsedCaseParties(
            petitioner=petitioners, respondent=respondents
        ),
        status=case.status or None,
        last_hearing_date=case.last_hearing_date or None,
        next_hearing_date=case.next_hearing_date or None,
        court_no=case.court_no or None,
        judge_bench=case.judge_bench or None,
        orders=[
            ParsedOrderOut(date=o.order_date or None, title=o.title, url=o.url)
            for o in case.orders
        ],
        judgments=[
            ParsedOrderOut(date=j.order_date or None, title=j.title, url=j.url)
            for j in case.judgments
        ],
        raw_html_hash=case.raw_html_hash,
        parsed_at=case.parsed_at,
        source_url=case.source_url,
        parser_version=parser_version_id,
    )
