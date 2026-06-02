# PROMPT: "Write pytest tests for a FastAPI event-ingestion endpoint that must be
#   idempotent by event_id, support partial success on malformed events, and reject
#   batches larger than 500. Use the TestClient."
# CHANGES MADE: Split the lenient (partial-success) path onto /events/ingest/raw
#   since the strict endpoint validates the whole batch; added an explicit
#   duplicate-within-same-batch assertion the model missed.
from helpers import ev, ts


def test_ingest_accepts_valid_batch(post_events):
    r = post_events([ev("E1", "ENTRY", "V1", ts(10, 0)),
                     ev("E2", "ZONE_ENTER", "V1", ts(10, 1), zone="FOH")])
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 2 and body["duplicates"] == 0


def test_ingest_is_idempotent(post_events):
    batch = [ev("DUP1", "ENTRY", "V1", ts(10, 0)),
             ev("DUP2", "EXIT", "V1", ts(10, 5))]
    first = post_events(batch).json()
    assert first["accepted"] == 2
    # replaying the same payload must not double-count
    second = post_events(batch).json()
    assert second["accepted"] == 0 and second["duplicates"] == 2


def test_duplicate_within_single_batch(post_events):
    body = post_events([ev("X", "ENTRY", "V1", ts(10, 0)),
                        ev("X", "ENTRY", "V1", ts(10, 0))]).json()
    assert body["accepted"] == 1 and body["duplicates"] == 1


def test_partial_success_on_malformed(post_events):
    good = ev("G1", "ENTRY", "V1", ts(10, 0))
    bad = ev("B1", "ENTRY", "V2", ts(10, 0))
    bad["confidence"] = 5.0  # invalid: must be 0..1
    body = post_events([good, bad], lenient=True).json()
    assert body["accepted"] == 1
    assert body["rejected"] == 1
    assert body["rejected_detail"][0]["index"] == 1


def test_batch_too_large_is_rejected(post_events):
    big = [ev(f"E{i}", "ENTRY", f"V{i}", ts(10, 0)) for i in range(501)]
    r = post_events(big)
    assert r.status_code == 413
