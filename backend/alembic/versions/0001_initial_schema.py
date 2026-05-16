"""initial schema for Delhi HC Case Tracker MVP

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-17

Creates the v1 MVP schema. Engine-portable across SQLite and PostgreSQL:
no JSONB, no ARRAY, no partial indexes, no dialect-only column types.

Naming convention follows the SQLAlchemy MetaData convention declared in
backend/app/models/__init__.py, so Alembic autogenerate produces stable,
predictable constraint names (pk_*, fk_*, uq_*, ix_*, ck_*).

Tables (in dependency order):
    parser_version
    admin_session
    parsed_case            (FK -> parser_version)
    search_request         (FK -> parsed_case, admin_session)
    case_party             (FK -> parsed_case)
    case_order             (FK -> parsed_case)
    outbound_request_log   (FK -> search_request)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# Alembic identifiers
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _server_now() -> sa.sql.elements.TextClause:
    """Return a portable server-side "now" default.

    CURRENT_TIMESTAMP is valid in both SQLite and PostgreSQL and resolves
    to UTC on SQLite, to the session timezone on Postgres. The app layer
    sets the Postgres session TZ to UTC at engine init.
    """
    return sa.text("CURRENT_TIMESTAMP")


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ---- parser_version -------------------------------------------------
    op.create_table(
        "parser_version",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("git_sha", sa.String(length=40), nullable=False),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0") if not _is_postgres() else sa.text("false"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=_server_now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=_server_now(),
        ),
        sa.UniqueConstraint("version", name="uq_parser_version_version"),
    )
    op.create_index(
        "ix_parser_version_is_current",
        "parser_version",
        ["is_current"],
    )

    # ---- admin_session --------------------------------------------------
    op.create_table(
        "admin_session",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=_server_now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=_server_now(),
        ),
        sa.UniqueConstraint("token_hash", name="uq_admin_session_token_hash"),
    )
    op.create_index(
        "ix_admin_session_expires_at",
        "admin_session",
        ["expires_at"],
    )

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
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=_server_now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
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

    # ---- search_request -------------------------------------------------
    op.create_table(
        "search_request",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_type", sa.String(length=32), nullable=False),
        sa.Column("case_number", sa.String(length=32), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'initialized'"),
        ),
        sa.Column("user_ip_hash", sa.String(length=64), nullable=False),
        sa.Column("captcha_token", sa.String(length=64), nullable=True),
        sa.Column("parsed_case_id", sa.Integer(), nullable=True),
        sa.Column("admin_session_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("captcha_displayed_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=_server_now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=_server_now(),
        ),
        sa.CheckConstraint(
            "year >= 1950 AND year <= 2100",
            name="ck_search_request_year_range",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'initialized', 'captcha_displayed', 'submitted', "
            "'success', 'failed', 'expired'"
            ")",
            name="ck_search_request_status_enum",
        ),
        sa.ForeignKeyConstraint(
            ["parsed_case_id"],
            ["parsed_case.id"],
            name="fk_search_request_parsed_case_id_parsed_case",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["admin_session_id"],
            ["admin_session.id"],
            name="fk_search_request_admin_session_id_admin_session",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_search_request_status_created_at",
        "search_request",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_search_request_created_at",
        "search_request",
        ["created_at"],
    )
    op.create_index(
        "ix_search_request_user_ip_hash",
        "search_request",
        ["user_ip_hash"],
    )
    op.create_index(
        "ix_search_request_parsed_case_id",
        "search_request",
        ["parsed_case_id"],
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
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=_server_now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
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
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=_server_now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
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

    # ---- outbound_request_log ------------------------------------------
    op.create_table(
        "outbound_request_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("search_request_id", sa.Integer(), nullable=True),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_size_bytes", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=_server_now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=_server_now(),
        ),
        sa.ForeignKeyConstraint(
            ["search_request_id"],
            ["search_request.id"],
            name=(
                "fk_outbound_request_log_search_request_id_search_request"
            ),
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_outbound_request_log_created_at",
        "outbound_request_log",
        ["created_at"],
    )
    op.create_index(
        "ix_outbound_request_log_search_request_id",
        "outbound_request_log",
        ["search_request_id"],
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Reverse dependency order. Drop children before parents.
    op.drop_index(
        "ix_outbound_request_log_search_request_id",
        table_name="outbound_request_log",
    )
    op.drop_index(
        "ix_outbound_request_log_created_at",
        table_name="outbound_request_log",
    )
    op.drop_table("outbound_request_log")

    op.drop_index("ix_case_order_parsed_case_id", table_name="case_order")
    op.drop_table("case_order")

    op.drop_index("ix_case_party_advocate", table_name="case_party")
    op.drop_index("ix_case_party_parsed_case_id", table_name="case_party")
    op.drop_table("case_party")

    op.drop_index(
        "ix_search_request_parsed_case_id", table_name="search_request"
    )
    op.drop_index(
        "ix_search_request_user_ip_hash", table_name="search_request"
    )
    op.drop_index(
        "ix_search_request_created_at", table_name="search_request"
    )
    op.drop_index(
        "ix_search_request_status_created_at", table_name="search_request"
    )
    op.drop_table("search_request")

    op.drop_index(
        "ix_parsed_case_parser_version_id", table_name="parsed_case"
    )
    op.drop_index("ix_parsed_case_expires_at", table_name="parsed_case")
    op.drop_table("parsed_case")

    op.drop_index("ix_admin_session_expires_at", table_name="admin_session")
    op.drop_table("admin_session")

    op.drop_index(
        "ix_parser_version_is_current", table_name="parser_version"
    )
    op.drop_table("parser_version")
