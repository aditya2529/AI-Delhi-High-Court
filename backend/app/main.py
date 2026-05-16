"""FastAPI app entry point.

Wires settings, CORS, structured logging, the error envelope middleware,
request-id middleware, and routes. On startup, runs Alembic upgrade head
once so the SQLite file is always in sync with the latest migration —
this is acceptable for the MVP single-node deploy; multi-node deploys
should run migrations as a separate `alembic upgrade head` step ahead
of process start.
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.db.session import dispose_engine, get_engine
from app.utils.errors import ApiError, api_error_response, get_or_mint_request_id
from app.utils.logging import configure_logging, get_logger


def _run_alembic_upgrade() -> None:
    """Idempotently run `alembic upgrade head` against the current DATABASE_URL.

    SQLite-friendly: re-running is cheap because the version table is checked
    before any DDL. We pass DATABASE_URL via env var so alembic/env.py picks
    it up (already wired there).
    """
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_cfg = AlembicConfig(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location", str(backend_dir / "alembic")
    )

    settings = get_settings()
    # Ensure DATABASE_URL is in the env so env.py's override path fires.
    os.environ.setdefault("DATABASE_URL", settings.database_url)
    # SQLite needs the parent dir to exist for file creation.
    if settings.database_url.startswith("sqlite"):
        db_path = settings.database_url.split("///", 1)[-1].lstrip("./")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    command.upgrade(alembic_cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: migrate + warm engine. Shutdown: dispose engine."""
    settings = get_settings()
    configure_logging(
        log_level=settings.app_log_level, log_file=settings.log_file_backend
    )
    log = get_logger("app.startup")
    try:
        _run_alembic_upgrade()
        log.info("startup.migration.ok")
    except Exception as exc:  # noqa: BLE001 — startup failures are fatal
        log.error("startup.migration.fail", error=str(exc))
        raise
    # Build the engine eagerly so /ready works immediately.
    get_engine()
    log.info("startup.ready", version=app.version)
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    """Build and return the FastAPI app. Pure function — no side effects
    until the app actually serves requests."""
    settings = get_settings()
    app = FastAPI(
        title="Delhi HC Case Tracker",
        version="0.1.0",
        description=(
            "Workflow-simplification web app that wraps the public Delhi High "
            "Court case-status search. NOT a court-operated site. The court's "
            "own page is authoritative. We never bypass CAPTCHA."
        ),
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    _install_request_id_middleware(app)
    _install_error_handlers(app)
    _register_routes(app)
    return app


def _install_request_id_middleware(app: FastAPI) -> None:
    """Stamp every request with a request_id; echo it on the response."""
    @app.middleware("http")
    async def _request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = get_or_mint_request_id(request)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


def _install_error_handlers(app: FastAPI) -> None:
    """Translate every error path into the canonical envelope."""
    app.add_exception_handler(ApiError, _api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exc_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_handler)


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return api_error_response(
        code=exc.code, message=exc.message, http_status=exc.http_status,
        retryable=exc.retryable, hint=exc.hint,
        request_id=_rid(request),
    )


async def _validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return api_error_response(
        code="invalid_request",
        message="request body validation failed",
        http_status=422,
        retryable=False,
        hint=str(exc.errors()[:3]),
        request_id=_rid(request),
    )


_HTTP_CODE_MAP = {401: "unauthorized", 404: "not_found", 405: "invalid_request"}


async def _http_exc_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return api_error_response(
        code=_HTTP_CODE_MAP.get(exc.status_code, "internal_error"),
        message=str(exc.detail) if exc.detail else "request failed",
        http_status=exc.status_code,
        retryable=exc.status_code in (502, 503, 504),
        hint=None,
        request_id=_rid(request),
    )


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    log = get_logger("app.error")
    log.error("unhandled_exception", error=str(exc), kind=type(exc).__name__)
    return api_error_response(
        code="internal_error",
        message="an unexpected error occurred",
        http_status=500,
        retryable=False,
        hint=None,
        request_id=_rid(request),
    )


def _rid(request: Request) -> str:
    """Pull the request id stamped by the middleware; mint one if missing."""
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) and rid else uuid.uuid4().hex


def _register_routes(app: FastAPI) -> None:
    """Routes are imported lazily so tests can import `create_app` without
    pulling the entire dependency graph during fixture collection."""
    from app.api.routes import admin, health, search

    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(search.router, prefix="/api/v1/search", tags=["search"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])


app = create_app()
