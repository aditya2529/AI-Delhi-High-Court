"""AdminSession — MVP shared-secret admin tokens.

We store only the SHA-256 of the bearer token; the raw token is shown
to the operator once on issue and never persisted. Full OAuth/JWT auth
lands in v2 and will replace this table.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

if TYPE_CHECKING:
    from app.models.search_request import SearchRequest


class AdminSession(Base):
    __tablename__ = "admin_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(
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

    # Reverse relationship
    search_requests: Mapped[List["SearchRequest"]] = relationship(
        "SearchRequest",
        back_populates="admin_session",
    )

    __table_args__ = (
        Index("ix_admin_session_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<AdminSession id={self.id} label={self.label!r} "
            f"expires_at={self.expires_at.isoformat() if self.expires_at else None}>"
        )
