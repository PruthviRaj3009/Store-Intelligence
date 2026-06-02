# PROMPT: "Write pytest tests for a session-based conversion funnel endpoint.
#   Critically: a re-entering visitor (ENTRY, EXIT, then REENTRY with the same id)
#   must count once at the entry stage; a group of 3 distinct ids must count as 3;
#   stage counts must be monotonically non-increasing."
# CHANGES MADE: Added the monotonic-stages assertion and an explicit check that
#   the funnel 'unit' is documented as session-based in the response.
from helpers import ev, ts


def test_reentry_not_double_counted(post_events, client):
    post_events([
        ev("e1", "ENTRY", "V1", ts(12, 0)),
        ev("e2", "ZONE_ENTER", "V1", ts(12, 1), zone="FOH"),
        ev("e3", "EXIT", "V1", ts(12, 5)),
        ev("e4", "REENTRY", "V1", ts(12, 20)),   # same visitor returns
    ])
    f = client.get("/stores/ST1008/funnel").json()
    entry = next(s for s in f["stages"] if s["stage"] == "entry")
    assert entry["visitors"] == 1                # NOT 2
    assert "session" in f["unit"]


def test_group_entry_counts_individuals(post_events, client):
    post_events([
        ev("g1", "ENTRY", "V1", ts(12, 0)),
        ev("g2", "ENTRY", "V2", ts(12, 0)),
        ev("g3", "ENTRY", "V3", ts(12, 0)),
    ])
    f = client.get("/stores/ST1008/funnel").json()
    entry = next(s for s in f["stages"] if s["stage"] == "entry")
    assert entry["visitors"] == 3


def test_funnel_stages_monotonic(post_events, add_pos, client):
    post_events([
        ev("a1", "ENTRY", "V1", ts(12, 0)),
        ev("a2", "ZONE_ENTER", "V1", ts(12, 1), zone="FOH"),
        ev("a3", "BILLING_QUEUE_JOIN", "V1", ts(12, 3), zone="BILLING", queue_depth=1),
        ev("b1", "ENTRY", "V2", ts(12, 0)),
        ev("b2", "ZONE_ENTER", "V2", ts(12, 1), zone="FOH"),
        ev("c1", "ENTRY", "V3", ts(12, 0)),  # enters, never browses
    ])
    add_pos("TXN1", ts(12, 5))
    f = client.get("/stores/ST1008/funnel").json()
    counts = [s["visitors"] for s in f["stages"]]
    assert counts == sorted(counts, reverse=True)   # entry >= zone >= billing >= purchase
    assert counts[0] == 3
