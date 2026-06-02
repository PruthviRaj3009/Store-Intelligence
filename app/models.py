"""Pydantic schemas — the event contract the detection pipeline must emit,
plus ingest/response models. Validation here is the API's first line of defence
(Part A 'schema compliance' + Part B 'validates, partial success')."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: Optional[int] = None


class EventIn(BaseModel):
    """One behavioural event. Mirrors the schema in the problem statement."""
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: EventType
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        # store everything tz-aware in UTC; naive timestamps are assumed UTC
        from datetime import timezone
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


class IngestBatch(BaseModel):
    events: list[EventIn]


class RejectedEvent(BaseModel):
    index: int
    error: str


class IngestResult(BaseModel):
    received: int
    accepted: int
    duplicates: int
    rejected: int
    rejected_detail: list[RejectedEvent] = []
