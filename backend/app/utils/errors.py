"""Error envelope helpers — every non-2xx response shaped per API-CONTRACT §1.4.

The contract is strict: `{error: {code, message, retryable, hint, request_id}}`.
We funnel every error through `api_error()` so the shape is invariant.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Domain error carrying the envelope fields.

    Raise from anywhere in request scope; the middleware in `main.py`
    translates it to the JSON envelope. Never use `HTTPException` for
    domain errors — its shape differs from our contract.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        http_status: int,
        retryable: bool,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.hint = hint


def api_error_response(
    *,
    code: str,
    message: str,
    http_status: int,
    retryable: bool,
    hint: str | None,
    request_id: str,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the canonical error JSONResponse."""
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": request_id,
        }
    }
    if hint is not None:
        body["error"]["hint"] = hint

    headers = {"X-Request-Id": request_id}
    if extra_headers:
        headers.update(extra_headers)
    return JSONResponse(status_code=http_status, content=body, headers=headers)


def get_or_mint_request_id(request: Request) -> str:
    """Echo client `X-Request-Id` if present and valid, else mint one."""
    raw = request.headers.get("X-Request-Id")
    if raw:
        # Trim defensively; we trust nothing from the wire.
        candidate = raw.strip()[:64]
        if candidate:
            return candidate
    return uuid.uuid4().hex
