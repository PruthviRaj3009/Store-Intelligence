"""GET /stores/{id}/anomalies — active operational anomalies.

Types: BILLING_QUEUE_SPIKE, CONVERSION_DROP (vs trailing 7-day avg), DEAD_ZONE.
Severity: INFO / WARN / CRITICAL. Each carries a suggested_action.
Relative time uses the feed clock (latest event), see analytics.py.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from app.analytics import (apply_conversion, build_sessions, feed_now,
                           get_events, get_pos, resolve_window)
from app.config import settings
from app.store import floor_zone_ids, zone_types
from app.tables import Event


def _conversion_for_day(db: DBSession, store_id: str, start, end) -> float | None:
    events = get_events(db, store_id, start, end, include_staff=False)
    if not events:
        return None
    sessions = build_sessions(events, zone_types())
    apply_conversion(sessions, get_pos(db, store_id, start, end))
    n = len(sessions)
    return (sum(1 for s in sessions.values() if s.converted) / n) if n else 0.0


def compute_anomalies(db: DBSession, store_id: str, date: str | None = None) -> dict:
    start, end = resolve_window(db, store_id, date)
    now = feed_now(db, store_id) or end
    events = get_events(db, store_id, start, end, include_staff=False)
    anomalies: list[dict] = []

    # 1) Billing queue spike
    max_q = max((e.queue_depth or 0) for e in events) if events else 0
    if max_q >= settings.QUEUE_SPIKE_DEPTH:
        sev = "CRITICAL" if max_q >= settings.QUEUE_SPIKE_DEPTH * 2 else "WARN"
        anomalies.append({
            "type": "BILLING_QUEUE_SPIKE",
            "severity": sev,
            "detail": f"Queue depth reached {max_q} (threshold {settings.QUEUE_SPIKE_DEPTH}).",
            "suggested_action": "Open an additional billing counter or redirect staff to checkout.",
            "value": max_q,
        })

    # 2) Conversion drop vs trailing 7-day average
    today_conv = _conversion_for_day(db, store_id, start, end)
    prior = []
    for i in range(1, 8):
        s = start - timedelta(days=i)
        c = _conversion_for_day(db, store_id, s, s + timedelta(days=1))
        if c is not None:
            prior.append(c)
    if today_conv is not None and prior:
        baseline = sum(prior) / len(prior)
        if baseline > 0 and today_conv < 0.7 * baseline:
            anomalies.append({
                "type": "CONVERSION_DROP",
                "severity": "WARN",
                "detail": f"Conversion {today_conv:.2%} vs 7-day avg {baseline:.2%}.",
                "suggested_action": "Check staffing, queue length, and stockouts in high-traffic zones.",
                "value": round(today_conv, 4),
                "baseline": round(baseline, 4),
            })
    elif today_conv is not None:
        anomalies.append({
            "type": "CONVERSION_DROP",
            "severity": "INFO",
            "detail": "Insufficient history (<1 prior day) to baseline conversion.",
            "suggested_action": "Accumulate >=7 days of events for trend-based alerting.",
            "value": round(today_conv, 4),
        })

    # 3) Dead zones: a floor zone with no visit in the last DEAD_ZONE_MIN minutes
    cutoff = now - timedelta(minutes=settings.DEAD_ZONE_MIN)
    for zid in floor_zone_ids():
        last_visit = db.execute(
            select(func.max(Event.ts)).where(
                Event.store_id == store_id, Event.zone_id == zid,
                Event.is_staff.is_(False), Event.ts >= start, Event.ts < end,
            )
        ).scalar_one_or_none()
        from app.analytics import _as_utc
        if last_visit is None or _as_utc(last_visit) < cutoff:
            anomalies.append({
                "type": "DEAD_ZONE",
                "severity": "INFO",
                "detail": f"No visits to {zid} in the last {settings.DEAD_ZONE_MIN} min.",
                "suggested_action": f"Check {zid} merchandising/lighting; consider a promo or staff prompt.",
                "zone_id": zid,
            })

    return {
        "store_id": store_id,
        "as_of": now.isoformat() if now else None,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }
