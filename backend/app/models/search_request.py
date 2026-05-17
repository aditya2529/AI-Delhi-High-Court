"""SearchRequest — lifecycle row for one user-initiated case search.

Tracks the FSM: initialized -> captcha_displayed -> submitted ->
success | failed | expired.

The `user_ip_hash` column stores HMAC-SHA256(ip, server_secret), not the
raw IP. A daily retention job re-hashes rows older than 90 days with a
rotated secret, severing back-correlation. **(Anonymisation job is
documented but not yet implemented — see DATA-MODEL.md §4.1.)**

GREEN-ZONE (2026-05-17): the historical `parsed_case_id` FK was removed
when court-data tables (`parsed_case` / `case_party` / `case_order`) were
ripped out. Audit rows now record the request itself, not a pointer to a
cached row. The on-success cache hit/miss is recorded only in cache
counters; if forensic correlation is later required, the
case_type+case_number+year already on this row is enough.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

if TYPE_CHECKING:
    from app.models.admin_session import AdminSession
    from app.models.outbound_request_log import OutboundRequestLog


SEARCH_REQUEST_STATUSES = (
    "initialized",
    "captcha_displayed",
    "submitted",
    "success",
    "failed",
    "expired",
)


class SearchRequest(Base):
    __tablename__ = "search_request"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # User input
    case_type: Mapped[str] = mapped_column(String(32), nullable=False)
    case_number: Mapped[str] = mapped_column(String(32), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'initialized'"),
    )

    # Privacy-safe identity
    user_ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Court-side opaque captcha token, only present in the captcha window
    captcha_token: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Optional link to an admin session (kept). The parsed_case FK was
    # removed under the GREEN-ZONE directive (no court-data persistence).
    admin_session_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "admin_session.id",
            name="fk_search_request_admin_session_id_admin_session",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # Failure payload
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # FSM timestamps
    captcha_displayed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # Relationships
    admin_session: Mapped["AdminSession | None"] = relationship(
        "AdminSession",
        back_populates="search_requests",
    )
    outbound_logs: Mapped[List["OutboundRequestLog"]] = relationship(
        "OutboundRequestLog",
        back_populates="search_request",
        # SET NULL on delete at the DB layer — do NOT cascade delete logs.
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "year >= 1950 AND year <= 2100",
            name="ck_search_request_year_range",
        ),
        CheckConstraint(
            "status IN ("
            "'initialized', 'captcha_displayed', 'submitted', "
            "'success', 'failed', 'expired'"
            ")",
            name="ck_search_request_status_enum",
        ),
        # Composite index serves the admin dashboard listing
        # (filter by status, order by created_at).
        Index(
            "ix_search_request_status_created_at",
            "status",
            "created_at",
        ),
        Index("ix_search_request_created_at", "created_at"),
        Index("ix_search_request_user_ip_hash", "user_ip_hash"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<SearchRequest id={self.id} "
            f"{self.case_type}/{self.case_number}/{self.year} "
            f"status={self.status!r}>"
        )
