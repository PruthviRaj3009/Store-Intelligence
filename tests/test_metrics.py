# PROMPT: "Write pytest tests for a /stores/{id}/metrics endpoint. Cover: empty
#   store returns zeros not a crash; staff events are excluded from unique visitors;
#   POS time-window conversion correlation works; zero-purchase store yields
#   conversion_rate 0 and full abandonment."
# CHANGES MADE: Added the zero-purchase abandonment assertion (model only tested
#   conversion_rate); used a real POS row via the add_pos fixture so the
#   correlation path is genuinely exercised, not mocked.
from helpers import ev, ts


def test_empty_store_returns_zeros(client):
    m = client.get("/stores/ST1008/metrics").json()
    assert m["unique_visitors"] == 0
    assert m["conversion_rate"] == 0.0
    assert m["abandonment_rate"] == 0.0  # no crash, no null


def test_staff_excluded_from_visitors(post_events, client):
    post_events([
        ev("c1", "ENTRY", "CUST", ts(12, 0)),
        ev("s1", "ENTRY", "STAFF", ts(12, 0), is_staff=True),
        ev("s2", "ZONE_ENTER", "STAFF", ts(12, 1), zone="FOH", is_staff=True),
    ])
    m = client.get("/stores/ST1008/metrics").json()
    assert m["unique_visitors"] == 1
    assert m["staff_excluded"] is True


def test_conversion_correlates_with_pos(post_events, add_pos, client):
    # visitor in BILLING at 12:02, a sale at 12:04 -> converted
    post_events([
        ev("e1", "ENTRY", "V1", ts(12, 0)),
        ev("e2", "BILLING_QUEUE_JOIN", "V1", ts(12, 2), zone="BILLING", queue_depth=2),
        ev("e3", "EXIT", "V1", ts(12, 6)),
    ])
    add_pos("TXN1", ts(12, 4), basket=499.0)
    m = client.get("/stores/ST1008/metrics").json()
    assert m["unique_visitors"] == 1
    assert m["converted_visitors"] == 1
    assert m["conversion_rate"] == 1.0
    assert m["transactions_attributed"] == 1


def test_zero_purchases(post_events, client):
    # visitor reaches billing but there is NO POS row -> not converted, abandoned
    post_events([
        ev("e1", "ENTRY", "V1", ts(12, 0)),
        ev("e2", "BILLING_QUEUE_JOIN", "V1", ts(12, 2), zone="BILLING", queue_depth=1),
        ev("e3", "EXIT", "V1", ts(12, 6)),
    ])
    m = client.get("/stores/ST1008/metrics").json()
    assert m["conversion_rate"] == 0.0
    assert m["billing_visitors"] == 1
    assert m["abandonment_rate"] == 1.0
