# PROMPT: "Write pytest tests for the /heatmap endpoint (normalized 0-100 zone
#   scores + a data_confidence flag when there are few sessions) and for the POS CSV
#   loader (load_pos must be idempotent)."
# CHANGES MADE: Wrote the POS CSV to a tmp file and asserted the second load adds 0
#   rows, proving idempotency rather than just a row count.
import csv

from helpers import ev, ts


def test_heatmap_normalized_with_low_confidence(post_events, client):
    post_events([
        ev("e1", "ENTRY", "V1", ts(12, 0)),
        ev("e2", "ZONE_ENTER", "V1", ts(12, 1), zone="FOH"),
        ev("e3", "ZONE_DWELL", "V1", ts(12, 2), zone="FOH", dwell_ms=60000),
        ev("e4", "ENTRY", "V2", ts(12, 5)),
        ev("e5", "ZONE_ENTER", "V2", ts(12, 6), zone="SKINCARE_WALL"),
    ])
    h = client.get("/stores/ST1008/heatmap").json()
    assert h["data_confidence"] == "low"          # < 20 sessions
    scores = {z["zone_id"]: z["visit_score"] for z in h["zones"]}
    assert max(scores.values()) == 100.0          # top zone normalized to 100
    assert all(0 <= v <= 100 for v in scores.values())


def test_load_pos_is_idempotent(tmp_path):
    from app.db import Base, SessionLocal, engine
    from app import tables  # noqa: F401
    from app.pos import load_pos

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    p = tmp_path / "pos.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["store_id", "transaction_id", "timestamp", "basket_value_inr", "line_items"])
        w.writerow(["ST1008", "T1", "2026-04-10T12:00:00Z", "500.0", "2"])
        w.writerow(["ST1008", "T2", "2026-04-10T12:05:00Z", "750.0", "1"])

    with SessionLocal() as db:
        assert load_pos(db, str(p)) == 2
        assert load_pos(db, str(p)) == 0   # idempotent: already present
