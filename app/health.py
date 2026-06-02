"""GET /health — service + feed status for the on-call engineer.

Reports DB connectivity, and per store/camera the last event timestamp with a
STALE_FEED warning when a camera lags the store's latest event by > threshold.
Staleness is measured against the store's own feed clock (latest event) so the
check is meaningful for replayed/recorded footage as well as a live feed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from app.analytics import _as_utc
from app.config import settings
from app.db import db_alive
from app.tables import Event


def compute_health(db: DBSession) -> dict:
    alive = db_alive()
    stores: list[dict] = []
    overall_ok = alive

    if alive:
        rows = db.execute(
            select(Event.store_id, Event.camera_id, func.max(Event.ts))
            .group_by(Event.store_id, Event.camera_id)
        ).all()
        by_store: dict[str, list[tuple[str, datetime]]] = {}
        for store_id, camera_id, ts in rows:
            by_store.setdefault(store_id, []).append((camera_id, _as_utc(ts)))

        for store_id, cams in by_store.items():
            store_last = max(ts for _, ts in cams)
            cam_status = []
            for camera_id, ts in sorted(cams):
                lag_min = (store_last - ts).total_seconds() / 60.0
                stale = lag_min > settings.STALE_FEED_MIN
                if stale:
                    overall_ok = False
                cam_status.append({
                    "camera_id": camera_id,
                    "last_event": ts.isoformat(),
                    "lag_min_vs_store": round(lag_min, 1),
                    "status": "STALE_FEED" if stale else "OK",
                })
            stores.append({
                "store_id": store_id,
                "last_event": store_last.isoformat(),
                "cameras": cam_status,
            })

    return {
        "status": "ok" if overall_ok else "degraded",
        "database": "up" if alive else "down",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "stores": stores,
    }
