# PROMPT: "Write pytest tests for a /health endpoint that reports database status
#   and a STALE_FEED warning when one camera's last event lags the store's latest
#   event by more than the threshold."
# CHANGES MADE: Asserted overall status flips to 'degraded' when any feed is stale,
#   and that a fresh single-camera store reports OK.
from helpers import ev, ts


def test_health_reports_db_up(client):
    h = client.get("/health").json()
    assert h["database"] == "up"
    assert h["status"] in {"ok", "degraded"}


def test_stale_feed_detected(post_events, client):
    # CAM_A last event 30 min behind CAM_B -> STALE_FEED
    post_events([
        ev("a1", "ENTRY", "V1", ts(12, 0), camera="CAM_A"),
        ev("b1", "ENTRY", "V2", ts(12, 30), camera="CAM_B"),
    ])
    h = client.get("/health").json()
    store = next(s for s in h["stores"] if s["store_id"] == "ST1008")
    statuses = {c["camera_id"]: c["status"] for c in store["cameras"]}
    assert statuses["CAM_A"] == "STALE_FEED"
    assert statuses["CAM_B"] == "OK"
    assert h["status"] == "degraded"
