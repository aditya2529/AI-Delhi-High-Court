"""structlog wiring — JSON logs to file + console.

Single setup at app boot. Logger names are dotted paths
(`app.api.routes.search`, etc).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import structlog


def configure_logging(*, log_level: str, log_file: str) -> None:
    """Configure stdlib logging + structlog. Idempotent."""
    Path(os.path.dirname(log_file) or ".").mkdir(parents=True, exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.INFO)
    root = logging.getLogger()
    if getattr(root, "_dhc_configured", False):
        return

    # Clear handlers from prior basicConfig().
    root.handlers.clear()
    root.setLevel(level)

    # File handler — JSON.
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(file_handler)

    # Console handler — human-readable.
    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(console_handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    setattr(root, "_dhc_configured", True)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Project-wide logger accessor — keeps callers off structlog API."""
    return structlog.get_logger(name)
