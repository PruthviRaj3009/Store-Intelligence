"""SQLAlchemy ORM tables for events and POS transactions."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Event(Base):
    __tablename__ = "events"

    # event_id is the natural idempotency key (problem statement: "globally unique")
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(32), index=True)
    camera_id: Mapped[str] = mapped_column(String(32))
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    ts: Mapped[datetime] = mapped_column("timestamp", DateTime(timezone=True), index=True)
    zone_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    dwell_ms: Mapped[int] = mapped_column(Integer, default=0)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    # flattened metadata
    queue_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sku_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)

    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# composite index that the metrics/funnel queries hit most
Index("ix_events_store_ts", Event.store_id, Event.ts)


class PosTransaction(Base):
    __tablename__ = "pos_transactions"

    transaction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(32), index=True)
    ts: Mapped[datetime] = mapped_column("timestamp", DateTime(timezone=True), index=True)
    basket_value_inr: Mapped[float] = mapped_column(Float, default=0.0)
    line_items: Mapped[int] = mapped_column(Integer, default=1)
