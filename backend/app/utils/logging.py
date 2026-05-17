"""Logging wiring — JSON logs to a rotating file + human-readable stdout.

Single setup at app boot. Logger names are dotted paths
(`app.api.routes.search`, etc).

Design (2026-05-17, post-incident):
    The first ``CLIENT_MODE=real`` run produced an empty
    ``logs/backend/app.log`` because the previous wiring never installed a
    file handler outside test scope — only a plain ``FileHandler`` with no
    rotation, opened against ``log_file`` whether or not it was set. This
    module replaces that with:

      * A ``RotatingFileHandler`` (50 MB, 5 backups → ~250 MB cap) wired
        from ``LOG_FILE_BACKEND``.
      * A separate ``RotatingFileHandler`` for the ``app.outbound`` logger
        wired from ``LOG_FILE_OUTBOUND`` (used by the upstream client +
        capture path; will be empty until callers emit on that logger).
      * A stdlib ``logging.Filter`` that pulls ``request_id`` from a
        ``contextvars.ContextVar`` and stamps every record with it.
      * A structlog processor that does the same thing for structlog-emitted
        records so the JSON file rows always carry ``request_id``.
      * A startup warning when ``LOG_FILE_BACKEND`` is empty so the
        operator notices that file logging is off.

Stdlib only for the rotation (``logging.handlers.RotatingFileHandler``) —
no new dependency. Structlog remains the high-level API as before.
"""
from __future__ import annotations

import contextvars
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any, Optional

import structlog


# ─── request_id contextvar ────────────────────────────────────────────────
#
# Source of truth for the current request's id. Populated by the
# request-id middleware on every inbound HTTP request, cleared on
# response. Logging handlers (both stdlib and structlog) read this so
# every record emitted inside the request automatically carries the id.
#
# We also bind into ``structlog.contextvars`` from the middleware so
# structlog calls pick the id up through ``merge_contextvars`` — that
# path was already wired before this change.
_REQUEST_ID_CTX: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)


def set_request_id(request_id: Optional[str]) -> contextvars.Token:
    """Bind the current request id; returns a token for ``reset_request_id``.

    Callers (typically the request-id middleware) should hold onto the
    token and pass it to ``reset_request_id`` in a ``finally`` so the
    value doesn't leak across requests when an exception unwinds.
    """
    return _REQUEST_ID_CTX.set(request_id)


def reset_request_id(token: contextvars.Token) -> None:
    """Undo a prior ``set_request_id`` call."""
    _REQUEST_ID_CTX.reset(token)


def get_request_id() -> Optional[str]:
    """Read the current request id, or ``None`` outside a request."""
    return _REQUEST_ID_CTX.get()


# ─── stdlib logging Filter that injects request_id ────────────────────────


class _RequestIdFilter(logging.Filter):
    """Stamp every LogRecord with ``record.request_id`` from the contextvar.

    The default value is ``"-"`` so the formatter never raises a
    ``KeyError`` when emission happens outside a request (startup,
    background workers, etc.).
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - stdlib API
        if not hasattr(record, "request_id"):
            record.request_id = _REQUEST_ID_CTX.get() or "-"
        return True


# ─── structlog processor: same job, for structlog records ─────────────────


def _structlog_inject_request_id(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """If the bound contextvars don't already carry request_id, fall back
    to the stdlib contextvar so direct ``structlog.get_logger().info(...)``
    calls also pick it up."""
    if "request_id" not in event_dict:
        rid = _REQUEST_ID_CTX.get()
        if rid:
            event_dict["request_id"] = rid
    return event_dict


# ─── Constants for the rotating handlers ──────────────────────────────────

# 50 MB per file, 5 backups → ~250 MB cap (matches the founder's brief).
_MAX_BYTES = 50 * 1024 * 1024
_BACKUP_COUNT = 5

# Human-readable format for stdout. File format is JSON, produced by
# the ``_JsonOrPassthroughFormatter`` defined below.
_CONSOLE_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s [rid=%(request_id)s] %(message)s"
)


class _JsonOrPassthroughFormatter(logging.Formatter):
    """Emits one JSON line per record.

    Structlog records arrive with the JSON payload already in
    ``record.getMessage()`` (it's a complete ``{...}`` string), so we
    can wrap it in our envelope without re-serialising. Records emitted
    via plain stdlib calls (e.g. uvicorn) get the message quoted as a
    JSON string instead.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Ensure the request_id attribute is present even if the filter
        # didn't run (defensive — handlers can be attached to non-root
        # loggers where our filter isn't installed).
        if not hasattr(record, "request_id"):
            record.request_id = _REQUEST_ID_CTX.get() or "-"
        # Render once via the standard pathway so ``%(asctime)s`` etc work.
        ts = self.formatTime(record, self.datefmt)
        msg = record.getMessage()
        looks_like_json = (
            len(msg) >= 2 and msg[0] == "{" and msg[-1] == "}"
        )
        if looks_like_json:
            payload = msg
        else:
            payload = _json_string(msg)
        envelope = (
            '{"ts":"' + ts + '","level":"' + record.levelname
            + '","logger":"' + record.name
            + '","request_id":"' + str(record.request_id) + '","message":'
            + payload + "}"
        )
        if record.exc_info:
            envelope = envelope[:-1] + ',"exc_info":' + _json_string(
                self.formatException(record.exc_info)
            ) + "}"
        return envelope


def _json_string(s: str) -> str:
    """Minimal JSON-string escaper. Avoids pulling ``json`` for one op."""
    return (
        '"'
        + s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        + '"'
    )


# ─── Main entry point ─────────────────────────────────────────────────────


def configure_logging(
    *,
    log_level: str,
    log_file: str,
    log_file_outbound: str = "",
) -> None:
    """Configure stdlib logging + structlog.

    Re-entrant: every call tears down handlers we previously installed
    on the root + ``app.outbound`` loggers and rewires from scratch.
    This is what tests need (each test points LOG_FILE_BACKEND at a
    fresh ``tmp_path``) AND what hot-reload-style re-init needs at
    runtime. Handlers installed by *other* code (uvicorn's access log)
    are left intact — we only remove handlers we tagged with
    ``_dhc_owned = True``.

    Args:
        log_level: ``"DEBUG"``, ``"INFO"`` … case-insensitive.
        log_file: path to the rotating backend log file. Empty string →
            file logging is disabled and a startup warning is emitted.
        log_file_outbound: path for the ``app.outbound`` logger's
            rotating file. Empty string → outbound file logging
            disabled (records still go to the root stdout handler).
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    root = logging.getLogger()

    # Remove only the handlers WE installed on past calls, so we don't
    # blow away uvicorn's or pytest's handlers. Also evict any plain
    # ``StreamHandler`` that alembic's ``fileConfig`` may have attached
    # (it has no marker, but matches the exact ``logging.StreamHandler``
    # class and writes to ``sys.stderr`` — same surface ours covers, so
    # leaving it would double every line).
    _remove_owned_handlers(root)
    _remove_alembic_console_handlers(root)
    _remove_owned_handlers(logging.getLogger("app.outbound"))
    root.setLevel(level)
    root.disabled = False

    # Pytest's logging-capture machinery sets ``logger.disabled = True``
    # on every logger it touched once its caplog fixture tears down.
    # Across test boundaries we re-enable every ``app.*`` logger so
    # subsequent emissions actually reach our handlers. In production
    # this is a no-op — nothing disables those loggers there.
    _reenable_app_loggers()

    # Always-on stdout handler. Human-readable, includes request_id so the
    # operator can grep terminal output too.
    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    console_handler.addFilter(_RequestIdFilter())
    console_handler._dhc_owned = True  # type: ignore[attr-defined]
    root.addHandler(console_handler)

    # Rotating file handler — ONLY if a log_file path was supplied.
    if log_file:
        _attach_rotating_file_handler(
            root, log_file, level, _MAX_BYTES, _BACKUP_COUNT
        )
    else:
        # Use the stdout handler we just attached to make sure the
        # warning is visible even though the file isn't being written.
        root.warning(
            "logging.file_disabled: LOG_FILE_BACKEND is empty — "
            "backend logs only go to stdout. Set LOG_FILE_BACKEND to "
            "enable persistent file logging."
        )

    # Outbound logger: route to its own rotating file. We keep
    # ``propagate=True`` so the root stdout handler still sees the
    # records (useful for live tailing).
    if log_file_outbound:
        outbound_logger = logging.getLogger("app.outbound")
        outbound_logger.setLevel(level)
        _attach_rotating_file_handler(
            outbound_logger, log_file_outbound, level,
            _MAX_BYTES, _BACKUP_COUNT,
        )

    # Structlog config — JSON renderer + contextvars merge + our
    # contextvar fallback. The JSON output lands in the stdlib handlers
    # above through ``structlog.stdlib.LoggerFactory``.
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _structlog_inject_request_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        # ``True`` matches the prior behaviour for the module-level
        # ``log = get_logger(__name__)`` references. Re-init still
        # works for STDLIB handlers (file paths) because those go
        # through ``logging.getLogger()`` which IS shared.
        cache_logger_on_first_use=True,
    )


def _remove_alembic_console_handlers(logger: logging.Logger) -> None:
    """Evict the ``StreamHandler`` alembic re-attaches every time
    ``command.upgrade`` re-reads ``alembic.ini``.

    Heuristic: a plain stdlib ``StreamHandler`` (exact class, not a
    subclass) writing to ``sys.stderr`` AND not tagged with
    ``_dhc_owned``. That uniquely matches alembic's handler without
    touching uvicorn / pytest handlers, which use subclasses (e.g.
    ``logging.handlers.QueueHandler``, ``LogCaptureHandler``).
    """
    to_remove = [
        h for h in list(logger.handlers)
        if type(h) is logging.StreamHandler  # noqa: E721 — exact match by design
        and not getattr(h, "_dhc_owned", False)
        and getattr(h, "stream", None) is sys.stderr
    ]
    for h in to_remove:
        logger.removeHandler(h)


def _reenable_app_loggers() -> None:
    """Reset ``logger.disabled = False`` for every ``app.*`` logger.

    pytest's caplog fixture toggles ``disabled`` between tests as part
    of its capture-handler teardown; without re-enabling them, the
    second test's log lines silently vanish even though handlers are
    attached and levels are set correctly.

    Cheap walk through ``Logger.manager.loggerDict`` — only touches
    loggers that have actually been instantiated.
    """
    manager = logging.Logger.manager
    for name, candidate in list(manager.loggerDict.items()):
        if isinstance(candidate, logging.Logger) and name.startswith("app"):
            candidate.disabled = False


def _remove_owned_handlers(logger: logging.Logger) -> None:
    """Detach + close any handlers we tagged with ``_dhc_owned``.

    Closing rotating file handlers releases the file descriptor — on
    Windows in particular, leaving them dangling stops pytest's tmp_path
    cleanup from working.
    """
    owned = [h for h in list(logger.handlers) if getattr(h, "_dhc_owned", False)]
    for h in owned:
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:  # noqa: BLE001 — handler cleanup must not raise
            pass


def _attach_rotating_file_handler(
    logger: logging.Logger,
    log_file: str,
    level: int,
    max_bytes: int,
    backup_count: int,
) -> None:
    """Create the parent dir, attach a RotatingFileHandler with our
    JSON-passthrough formatter + request_id filter."""
    parent = os.path.dirname(log_file) or "."
    Path(parent).mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=False,  # open immediately so a 0-byte file is created on boot
    )
    handler.setLevel(level)
    handler.setFormatter(_JsonOrPassthroughFormatter())
    handler.addFilter(_RequestIdFilter())
    handler._dhc_owned = True  # type: ignore[attr-defined]
    logger.addHandler(handler)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Project-wide logger accessor — keeps callers off structlog API."""
    return structlog.get_logger(name)
