"""Pydantic models for the public search API. Shape from API-CONTRACT.md §2-§3.

We DO NOT match the SQLAlchemy column names verbatim — the wire shape is
the contract, persistence is an implementation detail.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ─── Request bodies ────────────────────────────────────────────────────────


class SearchInitRequest(BaseModel):
    case_type: str = Field(
        ..., min_length=1, max_length=32, examples=["W.P.(C)", "CRL.M.C.", "FAO"]
    )
    case_number: str = Field(
        ...,
        min_length=1,
        max_length=7,
        pattern=r"^\d{1,7}$",
        examples=["12345"],
    )
    year: int = Field(..., ge=1900, le=2100, examples=[2024])


class SearchSubmitRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)
    captcha_text: str = Field(..., min_length=1, max_length=10)


# ─── Response payloads ─────────────────────────────────────────────────────


class CaptchaPayload(BaseModel):
    """Common chunk used by /init and /refresh-captcha."""

    captcha_image_b64: str
    captcha_mime: str = "image/png"
    captcha_expires_at: dt.datetime
    session_expires_at: dt.datetime


class SearchInitResponse(CaptchaPayload):
    session_id: str


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
