"""Pydantic models for the public search API. Shape from API-CONTRACT.md §2-§3.

We DO NOT match the SQLAlchemy column names verbatim — the wire shape is
the contract, persistence is an implementation detail.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ─── Request bodies ────────────────────────────────────────────────────────


class SearchInitRequest(BaseModel):
    case_type: str = Field(
        ..., min_length=1, max_length=32, examples=["W.P.(C)", "CRL.M.C.", "FAO"]
    )
    # Digits-only per API-CONTRACT §2, plus the reserved sentinel
    # "COURT_ERROR" which routes to the COURT_ERROR.html fixture when
    # CLIENT_MODE=fake (no-op selector under CLIENT_MODE=real). The
    # sentinel is documented in API-CONTRACT.md §2 (note block).
    case_number: str = Field(
        ...,
        min_length=1,
        max_length=16,
        pattern=r"^(?:\d{1,7}|COURT_ERROR)$",
        examples=["12345"],
    )
    # Lower bound 1950 mirrors the DB CHECK constraint on parsed_case.year.
    year: int = Field(..., ge=1950, le=2100, examples=[2024])


class SearchSubmitRequest(BaseModel):
    # session_id is canonical RFC 4122 dashed UUID v4 — see
    # API-CONTRACT §7.3. Pydantic's UUID type auto-validates the shape,
    # which kills the DRIFT-001 follow-on bug where a relaxed
    # min_length/max_length string silently accepted dashless hex
    # (see docs/DEMO-FEEDBACK.md item #4).
    session_id: UUID
    captcha_text: str = Field(..., min_length=1, max_length=10)


# ─── Response payloads ─────────────────────────────────────────────────────


class CaptchaPayload(BaseModel):
    """Common chunk used by /init and /refresh-captcha."""

    captcha_image_b64: str
    captcha_mime: str = "image/png"
    captcha_expires_at: dt.datetime
    session_expires_at: dt.datetime


class SearchInitResponse(CaptchaPayload):
    # Serializes as the canonical RFC 4122 dashed UUID v4 string.
    session_id: UUID


class RefreshCaptchaResponse(CaptchaPayload):
    pass


class ParsedCaseParties(BaseModel):
    petitioner: list[str]
    respondent: list[str]


class ParsedOrderOut(BaseModel):
    date: Optional[str]
    title: str
    url: Optional[str]


class ParsedCaseOut(BaseModel):
    """Wire shape per API-CONTRACT.md §7.1."""

    case_id: str
    case_type: str
    case_number: str
    year: int
    parties: ParsedCaseParties
    status: Optional[str]
    last_hearing_date: Optional[str]
    next_hearing_date: Optional[str]
    court_no: Optional[str]
    judge_bench: Optional[str]
    orders: list[ParsedOrderOut]
    judgments: list[ParsedOrderOut]
    raw_html_hash: str
    parsed_at: str
    source_url: str
    parser_version: int


# Body-level status enum.
SubmitStatus = Literal[
    "success", "captcha_failed", "expired", "not_found", "court_error"
]


class SearchSubmitResponse(BaseModel):
    status: SubmitStatus
    result: Optional[ParsedCaseOut] = None
    parser_degraded: bool = False
    retry_url: Optional[str] = None
    attempts_remaining: Optional[int] = None
