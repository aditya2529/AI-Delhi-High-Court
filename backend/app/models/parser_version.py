"""ParserVersion — parser code lineage.

Used to track which parser produced each cached `parsed_case` row, so
that a parser regression can trigger targeted re-parses of stale rows.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

if TYPE_CHECKING:
    from app.models.parsed_case import ParsedCase


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

    # Reverse relationships
    parsed_cases: Mapped[List["ParsedCase"]] = relationship(
        "ParsedCase",
        back_populates="parser_version",
        # RESTRICT on delete — handled at the DB layer; relationship is
        # informational only.
    )

    __table_args__ = (
        Index("ix_parser_version_is_current", "is_current"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<ParserVersion id={self.id} version={self.version!r} "
            f"current={self.is_current}>"
        )
