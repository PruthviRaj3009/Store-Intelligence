"""GET /stores/{id}/funnel — session-based conversion funnel.

Stages: Entry -> Zone Visit -> Billing Queue -> Purchase.
The unit is the SESSION (visitor_id), so a re-entering customer is counted once.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.analytics import (apply_conversion, build_sessions, get_events,
                           get_pos, resolve_window, visitor_sessions)
from app.store import zone_types


def _drop(prev: int, cur: int) -> float:
    return round(100 * (prev - cur) / prev, 1) if prev else 0.0


def compute_funnel(db: DBSession, store_id: str, date: str | None = None) -> dict:
    start, end = resolve_window(db, store_id, date)
    events = get_events(db, store_id, start, end, include_staff=False)
    sessions = build_sessions(events, zone_types())
    pos = get_pos(db, store_id, start, end)
    apply_conversion(sessions, pos)

    vsessions = visitor_sessions(sessions)
    entered = len(vsessions)
    visited_zone = sum(1 for s in vsessions if s.floor_zones)
    billing = sum(1 for s in vsessions if s.reached_billing)
    purchased = sum(1 for s in vsessions if s.converted)

    stages = [
        {"stage": "entry", "visitors": entered, "drop_off_pct": 0.0},
        {"stage": "zone_visit", "visitors": visited_zone, "drop_off_pct": _drop(entered, visited_zone)},
        {"stage": "billing_queue", "visitors": billing, "drop_off_pct": _drop(visited_zone, billing)},
        {"stage": "purchase", "visitors": purchased, "drop_off_pct": _drop(billing, purchased)},
    ]
    return {
        "store_id": store_id,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "unit": "session (visitor_id, re-entry de-duplicated)",
        "stages": stages,
        "overall_conversion_rate": round(purchased / entered, 4) if entered else 0.0,
    }
