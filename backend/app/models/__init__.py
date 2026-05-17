"""SQLAlchemy 2.x declarative models for Delhi HC Case Tracker.

The `Base` declared here carries a MetaData with a strict naming convention
so Alembic autogenerate produces predictable constraint names matching
those in `backend/alembic/versions/0001_initial_schema.py` and the GREEN-ZONE
follow-on `0002_remove_case_data_tables.py`.

All model modules are imported below so that `Base.metadata` is fully
populated when Alembic introspects this package via `env.py`.

GREEN-ZONE (2026-05-17): the former `parsed_case`, `case_party`, and
`case_order` models have been removed. Court data is no longer persisted —
see `app.cache.InMemoryCaseCache` and `docs/architecture/DATA-MODEL.md` §4.
"""
from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Naming convention — must stay in sync with the Alembic migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Project-wide declarative base.

    All model classes inherit from this. The shared MetaData uses our
    naming convention so constraint names are stable across runs.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# Import models so they register with Base.metadata. Order matters only
# for human readers; SQLAlchemy resolves relationships lazily.
from app.models.parser_version import ParserVersion  # noqa: E402,F401
from app.models.admin_session import AdminSession  # noqa: E402,F401
from app.models.search_request import SearchRequest  # noqa: E402,F401
from app.models.outbound_request_log import OutboundRequestLog  # noqa: E402,F401

__all__ = [
    "Base",
    "ParserVersion",
    "AdminSession",
    "SearchRequest",
    "OutboundRequestLog",
]
