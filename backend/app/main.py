"""FastAPI app entry point.

Skeleton only — wires settings, CORS, routes, and structured logging. Real
route implementations land in Arjun's backend sprint per the engineering
backlog. Until then routes return 501 Not Implemented.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.app_log_level)

    app = FastAPI(
        title="Delhi HC Case Tracker",
        version="0.1.0",
        description=(
            "Workflow-simplification web app that wraps the public Delhi High "
            "Court case-status search. NOT a court-operated site. The court's "
            "own page is authoritative. We never bypass CAPTCHA."
        ),
        # /docs and /redoc are on by default in dev; gate behind a flag for prod
        # when the API contract stabilises.
        openapi_url="/api/v1/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # Routes are imported lazily so test code can import `create_app` without
    # bringing the entire dependency graph (DB, httpx clients) into scope.
    from app.api.routes import admin, health, search

    app.include_router(health.router,  prefix="/api/v1",        tags=["health"])
    app.include_router(search.router,  prefix="/api/v1/search", tags=["search"])
    app.include_router(admin.router,   prefix="/api/v1/admin",  tags=["admin"])

    return app


app = create_app()
