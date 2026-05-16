"""CaseOrder — judgments/orders attached to a parsed case.

Stores the court-hosted PDF URL plus its label and emit date. We do not
mirror the PDF in v1 — Sneha hasn't yet signed off on hosting court
content ourselves.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

if TYPE_CHECKING:
    from app.models.parsed_case import ParsedCase


class CaseOrder(Base):
    __tablename__ = "case_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parsed_case_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "parsed_case.id",
            name="fk_case_order_parsed_case_id_parsed_case",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    order_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pdf_url: Mapped[str] = mapped_column(String(1024), nullable=False)

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
        back_populates="orders",
    )

    __table_args__ = (
        Index("ix_case_order_parsed_case_id", "parsed_case_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CaseOrder id={self.id} parsed_case_id={self.parsed_case_id} "
            f"title={self.title[:40]!r} date={self.order_date!r}>"
        )
