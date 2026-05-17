"""remove court-data tables per GREEN-ZONE directive

Revision ID: 0002_remove_case_data_tables
Revises: 0001_initial_schema
Create Date: 2026-05-17

Owner: Rohit (Database)
Directive: GREEN-ZONE — no long-term database storage of court data.

This migration drops the three tables that used to persist court output:
    parsed_case
    case_party
    case_order

And drops `search_request.parsed_case_id` (the FK pointer to the
now-gone parsed_case row). The audit row itself stays — it stores only
the user's *request* (case_type/number/year + IP hash), never the
court's *response*.

The cache that replaces these tables lives in process memory only — see
`backend/app/cache/in_memory_case_cache.py` and
`docs/architecture/DATA-MODEL.md` §4.

------------------------------------------------------------------------
Migration safety notes
------------------------------------------------------------------------
* Drop order respects FK chain: case_party + case_order (children) →
  search_request.parsed_case_id (FK column on a sibling) → parsed_case
  (parent).
* `parser_version` is intentionally KEPT — its rows are parser metadata,
  not court output, and we may want lineage continuity in v2.
* Estimated lock window on prod-size data: the GREEN-ZONE rip-out is
  being run before any production rows accumulate, so the lock window
  is microseconds. If this ever runs against a populated DB, the DROP
  TABLE on parsed_case would be a full-table delete + DDL; on SQLite
  that rewrites the page file. Still <1s for any v1 dataset.
* `downgrade()` recreates the exact 0001 shape (verbatim DDL) so a
  rollback is a faithful undo. This is a draft until the human DBA
  signs off.

------------------------------------------------------------------------
SQLite caveat: ALTER TABLE … DROP COLUMN
------------------------------------------------------------------------
SQLite gained native DROP COLUMN in 3.35 (2021). The MVP targets
3.40+, so `op.drop_column(...)` works without a batch rebuild. We use
`with op.batch_alter_table(...)` anyway to keep the migration portable
to older SQLite installs and to PostgreSQL (where batch is a no-op).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# Alembic identifiers
revision = "0002_remove_case_data_tables"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers (kept self-contained — do not import from 0001 to avoid coupling)
# ---------------------------------------------------------------------------

def _server_now() -> sa.sql.elements.TextClause:
    return sa.text("CURRENT_TIMESTAMP")


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


# ---------------------------------------------------------------------------
# upgrade — drop the three court-data tables + the dangling FK column
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # 1) Drop search_request.parsed_case_id (FK + index) BEFORE the parent
    #    table is gone, so the FK constraint is removed cleanly.
    with op.batch_alter_table("search_request") as batch:
        batch.drop_index("ix_search_request_parsed_case_id")
        batch.drop_constraint(
            "fk_search_request_parsed_case_id_parsed_case",
            type_="foreignkey",
        )
        batch.drop_column("parsed_case_id")

    # 2) Drop case_order (child of parsed_case).
    op.drop_index("ix_case_order_parsed_case_id", table_name="case_order")
    op.drop_table("case_order")

    # 3) Drop case_party (child of parsed_case).
    op.drop_index("ix_case_party_advocate", table_name="case_party")
    op.drop_index("ix_case_party_parsed_case_id", table_name="case_party")
    op.drop_table("case_party")

    # 4) Drop parsed_case itself.
    op.drop_index(
        "ix_parsed_case_parser_version_id", table_name="parsed_case"
    )
    op.drop_index("ix_parsed_case_expires_at", table_name="parsed_case")
    op.drop_table("parsed_case")


# ---------------------------------------------------------------------------
# downgrade — re-create exactly what 0001 created. Verbatim from
# `backend/alembic/versions/0001_initial_schema.py`. If 0001 ever changes
# shape, this block must be updated to match.
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # ---- parsed_case ----------------------------------------------------
    op.create_table(
        "parsed_case",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_type", sa.String(length=32), nullable=False),
        sa.Column("case_number", sa.String(length=32), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("court_case_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("filing_date", sa.String(length=32), nullable=True),
        sa.Column("next_hearing_date", sa.String(length=32), nullable=True),
        sa.Column("raw_html_ref", sa.Text(), nullable=True),
        sa.Column("parser_version_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=_server_now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=_server_now(),
        ),
        sa.CheckConstraint(
            "year >= 1950 AND year <= 2100",
            name="ck_parsed_case_year_range",
        ),
        sa.ForeignKeyConstraint(
            ["parser_version_id"],
            ["parser_version.id"],
            name="fk_parsed_case_parser_version_id_parser_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "case_type",
            "case_number",
            "year",
            name="uq_parsed_case_natural_key",
        ),
    )
    op.create_index(
        "ix_parsed_case_expires_at",
        "parsed_case",
        ["expires_at"],
    )
    op.create_index(
        "ix_parsed_case_parser_version_id",
        "parsed_case",
        ["parser_version_id"],
    )

    # ---- case_party -----------------------------------------------------
    op.create_table(
        "case_party",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("parsed_case_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("advocate", sa.String(length=255), nullable=True),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=_server_now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=_server_now(),
        ),
        sa.CheckConstraint(
            "role IN ('petitioner', 'respondent')",
            name="ck_case_party_role_enum",
        ),
        sa.ForeignKeyConstraint(
            ["parsed_case_id"],
            ["parsed_case.id"],
            name="fk_case_party_parsed_case_id_parsed_case",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_case_party_parsed_case_id",
        "case_party",
        ["parsed_case_id"],
    )
    op.create_index(
        "ix_case_party_advocate",
        "case_party",
        ["advocate"],
    )

    # ---- case_order -----------------------------------------------------
    op.create_table(
        "case_order",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("parsed_case_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("order_date", sa.String(length=32), nullable=True),
        sa.Column("pdf_url", sa.String(length=1024), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=_server_now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=_server_now(),
        ),
        sa.ForeignKeyConstraint(
            ["parsed_case_id"],
            ["parsed_case.id"],
            name="fk_case_order_parsed_case_id_parsed_case",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_case_order_parsed_case_id",
        "case_order",
        ["parsed_case_id"],
    )

    # ---- search_request.parsed_case_id (FK + index) ---------------------
    # Add the column back, then re-attach the FK + index. Nullable, so
    # existing rows survive the round-trip without a backfill.
    with op.batch_alter_table("search_request") as batch:
        batch.add_column(
            sa.Column("parsed_case_id", sa.Integer(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_search_request_parsed_case_id_parsed_case",
            "parsed_case",
            ["parsed_case_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_search_request_parsed_case_id",
        "search_request",
        ["parsed_case_id"],
    )

    # _is_postgres / _server_now are kept available for future column
    # additions; reference them to avoid unused-import lint warnings if
    # the file is checked.
    _ = _is_postgres
