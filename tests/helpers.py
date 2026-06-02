"""Shared test helpers: an event factory + a fixed test day."""
from __future__ import annotations

from datetime import datetime, timezone

DAY = datetime(2026, 4, 10, tzinfo=timezone.utc)


def ts(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute, second=second)


def ev(event_id, etype, visitor, when, *, zone=None, is_staff=False, conf=0.9,
       queue_depth=None, dwell_ms=0, store="ST1008", camera="CAM_1") -> dict:
    when_s = when.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(when, datetime) else when
    return {
        "event_id": event_id,
        "store_id": store,
        "camera_id": camera,
        "visitor_id": visitor,
        "event_type": etype,
        "timestamp": when_s,
        "zone_id": zone,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": conf,
        "metadata": {"queue_depth": queue_depth, "sku_zone": zone, "session_seq": 1},
    }
