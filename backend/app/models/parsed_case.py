"""ParsedCase — TTL-bounded cache of parsed court results.

Natural key is (case_type, case_number, year). The unique constraint on
that tuple doubles as the cache-lookup index.

Dates from the court (filing_date, next_hearing_date, order_date) are
stored as strings to preserve source fidelity — not every value the
court emits is a clean ISO date.
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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

if TYPE_CHECKING:
    from app.models.case_order import CaseOrder
    from app.models.case_party import CaseParty
    from app.models.parser_version import ParserVersion
    from app.models.search_request import SearchRequest


class ParsedCase(Base):
    __tablename__ = "parsed_case"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Natural key columns
    case_type: Mapped[str] = mapped_column(String(32), nullable=False)
    case_number: Mapped[str] = mapped_column(String(32), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    # Parsed payload
    court_case_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filing_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    next_hearing_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    raw_html_ref: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lineage + TTL
    parser_version_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "parser_version.id",
            name="fk_parsed_case_parser_version_id_parser_version",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

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
    parser_version: Mapped["ParserVersion"] = relationship(
        "ParserVersion",
        back_populates="parsed_cases",
    )
    parties: Mapped[List["CaseParty"]] = relationship(
        "CaseParty",
        back_populates="parsed_case",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CaseParty.display_order",
    )
    orders: Mapped[List["CaseOrder"]] = relationship(
        "CaseOrder",
        back_populates="parsed_case",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    search_requests: Mapped[List["SearchRequest"]] = relationship(
        "SearchRequest",
        back_populates="parsed_case",
    )

    __table_args__ = (
        UniqueConstraint(
            "case_type",
            "case_number",
            "year",
            name="uq_parsed_case_natural_key",
        ),
        CheckConstraint(
            "year >= 1950 AND year <= 2100",
            name="ck_parsed_case_year_range",
        ),
        Index("ix_parsed_case_expires_at", "expires_at"),
        Index("ix_parsed_case_parser_version_id", "parser_version_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<ParsedCase id={self.id} "
            f"{self.case_type}/{self.case_number}/{self.year} "
            f"status={self.status!r} expires_at={self.expires_at}>"
        )
