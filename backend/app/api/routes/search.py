"""Search endpoints — public API for the case-status flow.

These are STUBS until Arjun's sprint. Each returns 501 so frontend can wire
against the contract without depending on real parsing yet. The shape of
request/response matches `docs/api/API-CONTRACT.md` (Arnav).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter()


# ── Request / response schemas ─────────────────────────────────────────────

class SearchInitRequest(BaseModel):
    case_type: str = Field(..., examples=["W.P.(C)", "CRL.M.C.", "FAO"])
    case_number: str = Field(..., examples=["12345"])
    year: int = Field(..., ge=1950, le=2100, examples=[2024])


class SearchInitResponse(BaseModel):
    session_id: str
    captcha_image_b64: str
    captcha_expires_at: str  # ISO-8601


class SearchSubmitRequest(BaseModel):
    session_id: str
    captcha_text: str = Field(..., min_length=3, max_length=20)


# ── Routes ────────────────────────────────────────────────────────────────

@router.post(
    "/init",
    summary="Initiate a case search (opens session, fetches CAPTCHA)",
    response_model=SearchInitResponse,
    responses={
        501: {"description": "Not yet implemented (skeleton)"},
        503: {"description": "Court site unreachable"},
    },
)
async def search_init(body: SearchInitRequest) -> SearchInitResponse:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="search.init pending implementation — see docs/architecture/STRATEGIES.md",
    )


@router.post(
    "/submit",
    summary="Submit user-typed CAPTCHA + return parsed case result",
    responses={
        501: {"description": "Not yet implemented (skeleton)"},
        410: {"description": "Session/CAPTCHA expired — call /init again"},
        422: {"description": "CAPTCHA was wrong — refresh and retry"},
    },
)
async def search_submit(body: SearchSubmitRequest) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="search.submit pending implementation",
    )


@router.get(
    "/{session_id}/refresh-captcha",
    summary="Refresh CAPTCHA without losing form state (session still valid)",
    responses={501: {"description": "Not yet implemented (skeleton)"}},
)
async def refresh_captcha(session_id: str) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="search.refresh-captcha pending implementation",
    )
