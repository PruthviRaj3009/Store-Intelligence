"""Load normalized POS transactions from CSV into the DB (idempotent)."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.tables import PosTransaction


def _parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_pos(db: DBSession, csv_path: str | None = None) -> int:
    path = Path(csv_path or settings.POS_CSV_PATH)
    if not path.exists():
        return 0
    existing = set(db.execute(select(PosTransaction.transaction_id)).scalars())
    added = 0
    for row in csv.DictReader(open(path, encoding="utf-8")):
        tid = row["transaction_id"]
        if tid in existing:
            continue
        db.add(
            PosTransaction(
                transaction_id=tid,
                store_id=row["store_id"],
                ts=_parse_ts(row["timestamp"]),
                basket_value_inr=float(row.get("basket_value_inr") or 0),
                line_items=int(row.get("line_items") or 1),
            )
        )
        added += 1
    db.commit()
    return added
