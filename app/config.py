"""Central configuration, read from environment with sensible local defaults."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Settings:
    # SQLite fallback keeps the app + tests runnable with zero infra; docker-compose
    # overrides this with a Postgres URL. (See CHOICES.md > storage engine.)
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'store.db'}")

    STORE_LAYOUT_PATH: str = os.getenv("STORE_LAYOUT_PATH", str(ROOT / "data" / "store_layout.json"))
    POS_CSV_PATH: str = os.getenv("POS_CSV_PATH", str(ROOT / "data" / "pos_transactions.csv"))
    EVENTS_PATH: str = os.getenv("EVENTS_PATH", str(ROOT / "data" / "events.jsonl"))

    # auto-load events.jsonl on startup so /metrics has data even on a cold start
    AUTO_INGEST_ON_STARTUP: bool = os.getenv("AUTO_INGEST_ON_STARTUP", "true").lower() == "true"

    # --- business-logic knobs (documented in CHOICES.md) ---
    CONVERSION_WINDOW_MIN: int = int(os.getenv("CONVERSION_WINDOW_MIN", "5"))   # billing presence before a txn
    STALE_FEED_MIN: int = int(os.getenv("STALE_FEED_MIN", "10"))               # /health STALE_FEED threshold
    DEAD_ZONE_MIN: int = int(os.getenv("DEAD_ZONE_MIN", "30"))                 # anomaly: no visits in N min
    HEATMAP_MIN_SESSIONS: int = int(os.getenv("HEATMAP_MIN_SESSIONS", "20"))   # data_confidence flag
    QUEUE_SPIKE_DEPTH: int = int(os.getenv("QUEUE_SPIKE_DEPTH", "5"))          # anomaly: queue_depth >= N
    INGEST_MAX_BATCH: int = int(os.getenv("INGEST_MAX_BATCH", "500"))

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
