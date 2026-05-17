"""ParserVersion — parser code lineage.

Used to track which parser version is current. Originally it also linked
back to `parsed_case` rows so we could re-parse stale cached entries on a
parser bump, but court data is no longer persisted (GREEN-ZONE, 2026-05-17).
The table remains for operability metadata (which parser version the
process is running, when it was deployed) and so a v2 reintroduction of
cached results — if ever sanctioned — has a stable lineage anchor.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ParserVersion(Base):
    __tablename__ = "parser_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    git_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("0"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    __table_args__ = (
        Index("ix_parser_version_is_current", "is_current"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<ParserVersion id={self.id} version={self.version!r} "
            f"current={self.is_current}>"
        )
