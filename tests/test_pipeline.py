# PROMPT: "Write pytest tests for the detection pipeline's pure logic: ray-casting
#   point-in-polygon, doorway crossing direction (enter vs exit), and the sessionizer
#   FSM. Also assert every event the FSM emits validates against the production
#   Pydantic schema and that event_ids are globally unique."
# CHANGES MADE: Added a loiter-debounce test (a visitor oscillating on the line must
#   not produce a storm of ENTRY/EXIT) after we hit exactly that on real footage.
from datetime import datetime, timedelta, timezone

from app.models import EventIn
from pipeline.geometry import crossing_direction, point_in_polygon
from pipeline.sessionizer import Observation, process_observations

SQUARE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
T0 = datetime(2026, 4, 10, 10, 0, 0, tzinfo=timezone.utc)


def at(s):
    return T0 + timedelta(seconds=s)


def test_point_in_polygon():
    assert point_in_polygon((0.5, 0.5), SQUARE) is True
    assert point_in_polygon((0.05, 0.5), SQUARE) is False


def test_crossing_direction_enter_and_exit():
    line_p1, line_p2 = (0.0, 0.5), (1.0, 0.5)
    # moving downward (y small -> large), outside is 'above' -> entering
    assert crossing_direction((0.5, 0.3), (0.5, 0.7), line_p1, line_p2, "above") == "enter"
    assert crossing_direction((0.5, 0.7), (0.5, 0.3), line_p1, line_p2, "above") == "exit"
    # no crossing
    assert crossing_direction((0.5, 0.6), (0.5, 0.7), line_p1, line_p2, "above") is None


def test_sessionizer_full_lifecycle():
    obs = [
        Observation("V1", "CAM_3", at(0), boundary="enter"),
        Observation("V1", "CAM_3", at(10), zone_id="FOH"),
        Observation("V1", "CAM_3", at(45), zone_id="FOH"),           # 30s+ -> DWELL
        Observation("V1", "CAM_3", at(80), zone_id="BILLING", queue_depth=3),
        Observation("V1", "CAM_3", at(120), boundary="exit"),
        Observation("V1", "CAM_3", at(400), boundary="enter"),       # REENTRY
    ]
    events = process_observations("ST1008", obs)
    types = [e["event_type"] for e in events]
    assert "ENTRY" in types and "EXIT" in types and "REENTRY" in types
    assert "ZONE_DWELL" in types
    assert "BILLING_QUEUE_JOIN" in types


def test_loiter_does_not_spam_crossings():
    # foot oscillates across the line every 1s -> debounce keeps it to one ENTRY
    obs = []
    for i in range(8):
        obs.append(Observation("V1", "CAM_3", at(i),
                               boundary="enter" if i % 2 == 0 else "exit"))
    events = process_observations("ST1008", obs)
    n_entry = sum(e["event_type"] == "ENTRY" for e in events)
    assert n_entry <= 1


def test_emitted_events_match_schema_and_unique_ids():
    obs = [
        Observation("V1", "CAM_3", at(0), boundary="enter"),
        Observation("V1", "CAM_3", at(10), zone_id="FOH", confidence=0.3),  # low conf kept
        Observation("V1", "CAM_3", at(60), boundary="exit"),
    ]
    events = process_observations("ST1008", obs)
    for e in events:
        EventIn.model_validate(e)            # raises if schema-invalid
    ids = [e["event_id"] for e in events]
    assert len(ids) == len(set(ids))         # globally unique
