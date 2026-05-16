"""OutboundRequestLog — record of every HTTP call we make to the court site.

Powers rate-limit accounting, latency monitoring, and incident forensics.
Retained 30 days; older rows are archived to a flat-file dump (gzipped
NDJSON) by a daily job — job is documented in DATA-MODEL.md but not
built in v1.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
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
    from app.models.search_request import SearchRequest


class OutboundRequestLog(Base):
    __tablename__ = "outbound_request_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_request_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "search_request.id",
            name="fk_outbound_request_log_search_request_id_search_request",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_size_bytes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    search_request: Mapped["SearchRequest | None"] = relationship(
        "SearchRequest",
        back_populates="outbound_logs",
    )

    __table_args__ = (
        Index("ix_outbound_request_log_created_at", "created_at"),
        Index(
            "ix_outbound_request_log_search_request_id",
            "search_request_id",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<OutboundRequestLog id={self.id} "
            f"{self.method} {self.url[:60]!r} "
            f"status={self.response_status} latency_ms={self.latency_ms}>"
        )
