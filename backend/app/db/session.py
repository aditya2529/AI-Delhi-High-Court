"""Async SQLAlchemy engine + sessionmaker + FastAPI dependency.

Why a module-level singleton: the engine owns a connection pool. Creating
one per request defeats pooling and breaks SQLite's WAL semantics. We
lazily build the engine on first use so test code can swap DATABASE_URL
before initialising.

SQLite specifics:
* `PRAGMA foreign_keys=ON` is required per-connection — SQLite ships
  with FK enforcement OFF by default. We wire it in a `connect` event
  on the underlying sync engine.
"""
from __future__ import annotations

from typing import AsyncIterator, Optional

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def _enable_sqlite_fks(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
    """Per-connection `PRAGMA foreign_keys=ON` for SQLite.

    SQLite leaves FK enforcement off by default — without this, our
    `ON DELETE` rules silently no-op.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def get_engine() -> AsyncEngine:
    """Return (or lazily build) the process-wide async engine."""
    global _engine, _sessionmaker
    if _engine is not None:
        return _engine

    settings = get_settings()
    _engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        future=True,
        # SQLite is fine with the default pool; explicit args left out.
    )

    # Wire the FK pragma on every new connection (SQLite only).
    if settings.database_url.startswith("sqlite"):
        sync_engine = _engine.sync_engine
        event.listen(sync_engine, "connect", _enable_sqlite_fks)

    _sessionmaker = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the cached sessionmaker; builds the engine if not yet built."""
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None  # for mypy
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — yields one AsyncSession per request.

    Commits on success, rolls back on exception. Always closes.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Tear down the engine. Called on app shutdown + in tests."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
