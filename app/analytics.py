"""Core analytics: windows, session building, and POS conversion correlation.

Design decisions encoded here (defended in CHOICES.md / DESIGN.md):

1. The unit of analysis is the SESSION = one visitor_id within the window.
   Re-entries reuse the same visitor_id (a REENTRY event, not a new ENTRY), so
   grouping by visitor_id makes "re-entries must not double-count" automatic.

2. We exclude is_staff events from every customer metric.

3. "Feed clock": all relative-time logic (today's window, dead-zone, staleness)
   is measured against the LATEST event time for the store, not the server wall
   clock. This makes the system behave correctly when replaying recorded footage
   (our clips are from 2026-04-10) — for a genuine live feed, latest-event ~= now.

4. Conversion: a visitor who was present in the BILLING zone within
   CONVERSION_WINDOW_MIN before a POS transaction (same store) is a converted
   visitor. There is no customer_id in POS data, so correlation is time+store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.tables import Event, PosTransaction

BILLING_ZONE = "BILLING"
ENTRY_ZONE = "ENTRY"
BILLING_PRESENCE_TYPES = {"ZONE_ENTER", "ZONE_DWELL", "BILLING_QUEUE_JOIN"}


# ----------------------------- time helpers -----------------------------

def feed_now(db: DBSession, store_id: str) -> datetime | None:
    """Latest event timestamp for a store = the 'current' time of its feed."""
    ts = db.execute(
        select(func.max(Event.ts)).where(Event.store_id == store_id)
    ).scalar_one_or_none()
    return _as_utc(ts) if ts else None


def resolve_window(db: DBSession, store_id: str, date: str | None = None) -> tuple[datetime, datetime]:
    """Return [start, end) for the analytics window.

    - explicit ?date=YYYY-MM-DD -> that whole UTC day
    - otherwise -> the most recent calendar day that has events ("today")
    """
    if date:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        ref = feed_now(db, store_id)
        if ref is None:
            now = datetime.now(timezone.utc)
            return datetime.combine(now.date(), time.min, tzinfo=timezone.utc), \
                   datetime.combine(now.date(), time.max, tzinfo=timezone.utc)
        day = ref.date()
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ----------------------------- session model -----------------------------

@dataclass
class VisitorSession:
    visitor_id: str
    entered: bool = False
    reentered: bool = False
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    floor_zones: set[str] = field(default_factory=set)
    reached_billing: bool = False
    abandoned_billing: bool = False
    billing_times: list[datetime] = field(default_factory=list)
    dwell_by_zone: dict[str, int] = field(default_factory=dict)
    max_queue_depth: int = 0
    converted: bool = False


def visitor_sessions(sessions: dict[str, "VisitorSession"]) -> list["VisitorSession"]:
    """Sessions that represent a real entrant (an ENTRY/REENTRY/EXIT was seen).
    Anonymous side-camera zone tracks are excluded from visitor/conversion counts
    but still contribute to the heatmap."""
    return [s for s in sessions.values() if s.entered]


def get_events(db: DBSession, store_id: str, start: datetime, end: datetime,
               include_staff: bool = False) -> list[Event]:
    stmt = (
        select(Event)
        .where(Event.store_id == store_id, Event.ts >= start, Event.ts < end)
        .order_by(Event.ts)
    )
    if not include_staff:
        stmt = stmt.where(Event.is_staff.is_(False))
    return list(db.execute(stmt).scalars())


def get_pos(db: DBSession, store_id: str, start: datetime, end: datetime) -> list[PosTransaction]:
    stmt = (
        select(PosTransaction)
        .where(PosTransaction.store_id == store_id,
               PosTransaction.ts >= start, PosTransaction.ts < end)
        .order_by(PosTransaction.ts)
    )
    return list(db.execute(stmt).scalars())


def build_sessions(events: list[Event], zone_types: dict[str, str]) -> dict[str, VisitorSession]:
    """Collapse the (already staff-filtered) event stream into per-visitor sessions."""
    sessions: dict[str, VisitorSession] = {}
    for e in events:
        s = sessions.get(e.visitor_id)
        if s is None:
            s = sessions[e.visitor_id] = VisitorSession(visitor_id=e.visitor_id)
        ts = _as_utc(e.ts)
        s.first_ts = ts if s.first_ts is None else min(s.first_ts, ts)
        s.last_ts = ts if s.last_ts is None else max(s.last_ts, ts)

        if e.event_type == "ENTRY":
            s.entered = True
        elif e.event_type == "REENTRY":
            s.entered = True
            s.reentered = True
        elif e.event_type == "EXIT":
            # a visitor we saw leave was, by definition, in the store
            s.entered = True
        elif e.event_type == "BILLING_QUEUE_ABANDON":
            s.abandoned_billing = True

        if e.zone_id:
            ztype = zone_types.get(e.zone_id, "floor")
            if e.zone_id == BILLING_ZONE or ztype == "billing":
                if e.event_type in BILLING_PRESENCE_TYPES:
                    s.reached_billing = True
                    s.billing_times.append(ts)
            elif ztype == "floor":
                s.floor_zones.add(e.zone_id)
            if e.dwell_ms:
                s.dwell_by_zone[e.zone_id] = max(s.dwell_by_zone.get(e.zone_id, 0), e.dwell_ms)
        if e.queue_depth:
            s.max_queue_depth = max(s.max_queue_depth, e.queue_depth)
    return sessions


def apply_conversion(sessions: dict[str, VisitorSession], pos: list[PosTransaction],
                     window_min: int | None = None) -> int:
    """Mark sessions converted if a billing presence falls within `window_min`
    before a POS transaction. Returns count of attributed transactions."""
    window = timedelta(minutes=window_min if window_min is not None else settings.CONVERSION_WINDOW_MIN)
    attributed = 0
    for txn in pos:
        t = _as_utc(txn.ts)
        matched = False
        for s in sessions.values():
            if any(t - window <= bt <= t for bt in s.billing_times):
                s.converted = True
                matched = True
        if matched:
            attributed += 1
    return attributed
