"""CaseParty — petitioners and respondents for a parsed case.

Separate table (instead of denormalizing into parsed_case) because:
1. Party count is variable.
2. v2 will likely ship "find all cases for advocate X".
3. Keeps parsed_case row width bounded.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

if TYPE_CHECKING:
    from app.models.parsed_case import ParsedCase


PARTY_ROLES = ("petitioner", "respondent")


class CaseParty(Base):
    __tablename__ = "case_party"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parsed_case_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "parsed_case.id",
            name="fk_case_party_parsed_case_id_parsed_case",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    advocate: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
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

    parsed_case: Mapped["ParsedCase"] = relationship(
        "ParsedCase",
        back_populates="parties",
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('petitioner', 'respondent')",
            name="ck_case_party_role_enum",
        ),
        Index("ix_case_party_parsed_case_id", "parsed_case_id"),
        Index("ix_case_party_advocate", "advocate"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CaseParty id={self.id} parsed_case_id={self.parsed_case_id} "
            f"role={self.role!r} name={self.name!r}>"
        )
