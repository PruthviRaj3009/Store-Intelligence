# PROMPT: "Write pytest tests for an anomalies endpoint that flags billing queue
#   spikes, dead zones (a floor zone with no recent visits), and a conversion-drop
#   with INFO severity when there is insufficient history. Each anomaly must carry a
#   severity and a suggested_action."
# CHANGES MADE: Asserted the suggested_action string is present and non-empty
#   (the brief explicitly requires it); used the feed-clock so the dead-zone test is
#   deterministic with recorded timestamps.
from helpers import ev, ts


def _types(body):
    return {a["type"] for a in body["anomalies"]}


def test_billing_queue_spike(post_events, client):
    post_events([
        ev("e1", "ENTRY", "V1", ts(12, 0)),
        ev("e2", "BILLING_QUEUE_JOIN", "V1", ts(12, 2), zone="BILLING", queue_depth=8),
    ])
    a = client.get("/stores/ST1008/anomalies").json()
    assert "BILLING_QUEUE_SPIKE" in _types(a)
    spike = next(x for x in a["anomalies"] if x["type"] == "BILLING_QUEUE_SPIKE")
    assert spike["severity"] in {"WARN", "CRITICAL"}
    assert spike["suggested_action"]


def test_dead_zone_flagged(post_events, client):
    # only FOH is ever visited -> the other floor zones are 'dead'
    post_events([
        ev("e1", "ENTRY", "V1", ts(12, 0)),
        ev("e2", "ZONE_ENTER", "V1", ts(12, 1), zone="FOH"),
    ])
    a = client.get("/stores/ST1008/anomalies").json()
    assert "DEAD_ZONE" in _types(a)
    dz = next(x for x in a["anomalies"] if x["type"] == "DEAD_ZONE")
    assert dz["suggested_action"]


def test_conversion_drop_insufficient_history(post_events, client):
    post_events([ev("e1", "ENTRY", "V1", ts(12, 0))])
    a = client.get("/stores/ST1008/anomalies").json()
    cd = [x for x in a["anomalies"] if x["type"] == "CONVERSION_DROP"]
    assert cd and cd[0]["severity"] == "INFO"
