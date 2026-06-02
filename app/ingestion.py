"""Event ingestion: validated, idempotent by event_id, partial-success."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models import EventIn, IngestResult, RejectedEvent
from app.tables import Event


def _to_row(e: EventIn) -> Event:
    return Event(
        event_id=e.event_id,
        store_id=e.store_id,
        camera_id=e.camera_id,
        visitor_id=e.visitor_id,
        event_type=e.event_type.value,
        ts=e.timestamp,
        zone_id=e.zone_id,
        dwell_ms=e.dwell_ms,
        is_staff=e.is_staff,
        confidence=e.confidence,
        queue_depth=e.metadata.queue_depth,
        sku_zone=e.metadata.sku_zone,
        session_seq=e.metadata.session_seq,
        ingested_at=datetime.now(timezone.utc),
    )


def ingest_events(db: DBSession, raw_events: list[dict]) -> IngestResult:
    """Validate + insert a batch. Malformed events are rejected individually
    (partial success); duplicate event_ids are skipped (idempotent)."""
    rejected: list[RejectedEvent] = []
    valid: list[EventIn] = []

    for i, raw in enumerate(raw_events):
        try:
            valid.append(EventIn.model_validate(raw))
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(x) for x in first.get("loc", []))
            rejected.append(RejectedEvent(index=i, error=f"{loc}: {first.get('msg')}"))

    # idempotency: drop ids already in the DB or duplicated within the batch
    incoming_ids = [e.event_id for e in valid]
    existing = set(
        db.execute(select(Event.event_id).where(Event.event_id.in_(incoming_ids))).scalars()
    ) if incoming_ids else set()

    accepted = 0
    duplicates = 0
    seen_in_batch: set[str] = set()
    for e in valid:
        if e.event_id in existing or e.event_id in seen_in_batch:
            duplicates += 1
            continue
        seen_in_batch.add(e.event_id)
        db.merge(_to_row(e))  # merge = upsert-safe even under concurrent retries
        accepted += 1

    db.commit()
    return IngestResult(
        received=len(raw_events),
        accepted=accepted,
        duplicates=duplicates,
        rejected=len(rejected),
        rejected_detail=rejected,
    )


def ingest_jsonl(db: DBSession, path: str) -> IngestResult:
    """Bulk-load an events.jsonl file (used for startup auto-ingest)."""
    import json
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return IngestResult(received=0, accepted=0, duplicates=0, rejected=0)
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return ingest_events(db, rows)
