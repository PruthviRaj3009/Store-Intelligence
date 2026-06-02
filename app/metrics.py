"""GET /stores/{id}/metrics and /heatmap computation."""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.analytics import (apply_conversion, build_sessions, get_events,
                           get_pos, resolve_window, visitor_sessions)
from app.config import settings
from app.store import floor_zone_ids, zone_types


def _round(x: float, n: int = 4) -> float:
    return round(x, n)


def compute_metrics(db: DBSession, store_id: str, date: str | None = None) -> dict:
    start, end = resolve_window(db, store_id, date)
    ztypes = zone_types()
    events = get_events(db, store_id, start, end, include_staff=False)
    sessions = build_sessions(events, ztypes)
    pos = get_pos(db, store_id, start, end)
    attributed = apply_conversion(sessions, pos)

    vsessions = visitor_sessions(sessions)
    unique_visitors = len(vsessions)
    converted = sum(1 for s in vsessions if s.converted)
    billing_visitors = [s for s in vsessions if s.reached_billing]
    abandoned = sum(1 for s in billing_visitors if not s.converted)

    # avg dwell (seconds) per zone, across visitors who dwelt there
    dwell_acc: dict[str, list[int]] = {}
    for s in vsessions:
        for zid, ms in s.dwell_by_zone.items():
            dwell_acc.setdefault(zid, []).append(ms)
    avg_dwell = {
        zid: _round(sum(v) / len(v) / 1000.0, 1) for zid, v in dwell_acc.items()
    }

    queue_depths = [e.queue_depth for e in events if e.queue_depth]
    current_queue = queue_depths[-1] if queue_depths else 0

    return {
        "store_id": store_id,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "unique_visitors": unique_visitors,
        "converted_visitors": converted,
        "conversion_rate": _round(converted / unique_visitors) if unique_visitors else 0.0,
        "transactions_attributed": attributed,
        "pos_transactions": len(pos),
        "avg_dwell_seconds_by_zone": avg_dwell,
        "queue_depth_current": current_queue,
        "queue_depth_max": max(queue_depths) if queue_depths else 0,
        "billing_visitors": len(billing_visitors),
        "abandonment_rate": _round(abandoned / len(billing_visitors)) if billing_visitors else 0.0,
        "staff_excluded": True,
    }


def compute_heatmap(db: DBSession, store_id: str, date: str | None = None) -> dict:
    start, end = resolve_window(db, store_id, date)
    ztypes = zone_types()
    events = get_events(db, store_id, start, end, include_staff=False)
    sessions = build_sessions(events, ztypes)

    visits: dict[str, int] = {}
    dwell: dict[str, list[int]] = {}
    for s in sessions.values():
        for zid in s.floor_zones:
            visits[zid] = visits.get(zid, 0) + 1
        for zid, ms in s.dwell_by_zone.items():
            dwell.setdefault(zid, []).append(ms)

    zones_out = []
    max_visits = max(visits.values()) if visits else 0
    avg_dwell_raw = {z: (sum(v) / len(v) / 1000.0) for z, v in dwell.items()}
    max_dwell = max(avg_dwell_raw.values()) if avg_dwell_raw else 0.0

    for zid in floor_zone_ids():
        v = visits.get(zid, 0)
        d = avg_dwell_raw.get(zid, 0.0)
        zones_out.append({
            "zone_id": zid,
            "visits": v,
            "avg_dwell_seconds": _round(d, 1),
            "visit_score": _round(100 * v / max_visits, 1) if max_visits else 0.0,
            "dwell_score": _round(100 * d / max_dwell, 1) if max_dwell else 0.0,
        })

    n_sessions = len(sessions)
    return {
        "store_id": store_id,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "sessions": n_sessions,
        "data_confidence": "low" if n_sessions < settings.HEATMAP_MIN_SESSIONS else "ok",
        "zones": sorted(zones_out, key=lambda z: z["visit_score"], reverse=True),
    }
