"""Pytest fixtures. Sets a throwaway SQLite DB + disables startup auto-seed
BEFORE any app module is imported, then gives each test a clean client + DB."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# --- must run before importing app.* (settings read env at import time) ---
_TMP = Path(tempfile.mkdtemp(prefix="si_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["AUTO_INGEST_ON_STARTUP"] = "false"
os.environ["POS_CSV_PATH"] = str(_TMP / "no_pos.csv")     # absent -> no POS seeded
os.environ["EVENTS_PATH"] = str(_TMP / "no_events.jsonl")  # absent -> no events seeded

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    from app.db import Base, engine
    from app import tables  # noqa: F401  (register tables on Base)

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def post_events(client):
    def _post(events: list[dict], lenient: bool = False):
        url = "/events/ingest/raw" if lenient else "/events/ingest"
        return client.post(url, json={"events": events})
    return _post


@pytest.fixture
def add_pos():
    """Insert a POS transaction directly (conversion correlation tests)."""
    from datetime import datetime

    from app.db import SessionLocal
    from app.tables import PosTransaction

    def _add(transaction_id: str, when: datetime, store_id: str = "ST1008",
             basket: float = 250.0):
        with SessionLocal() as db:
            db.merge(PosTransaction(transaction_id=transaction_id, store_id=store_id,
                                    ts=when, basket_value_inr=basket, line_items=1))
            db.commit()
    return _add
