# PROMPT: "Write pytest tests for the detection pipeline's zone resolver
#   (StoreZones/CameraZones loaded from store_layout.json) and the staff heuristic
#   classifier. No video — pure logic only."
# CHANGES MADE: Loaded the real data/store_layout.json so the test also guards the
#   shipped layout's structure (a regression catch if a zone/camera is mis-edited).
from pathlib import Path

from pipeline.staff import classify_by_heuristic
from pipeline.zones import StoreZones

LAYOUT = str(Path(__file__).resolve().parents[1] / "data" / "store_layout.json")


def test_store_zones_loads_and_resolves():
    sz = StoreZones.from_file(LAYOUT)
    assert sz.store_id == "ST1008"
    cam = sz.camera("CAM_3")
    # CAM_3 is the entrance camera and has an entry line
    assert cam.entry_line is not None
    # a point inside the ENTRY polygon resolves to ENTRY
    assert cam.zone_for((0.5, 0.5)) == "ENTRY"
    # a point well outside resolves to None
    assert cam.zone_for((0.99, 0.02)) is None


def test_entry_crossing_direction():
    sz = StoreZones.from_file(LAYOUT)
    cam = sz.camera("CAM_3")  # line at y=0.40, outside='above'
    assert cam.entry_crossing((0.5, 0.3), (0.5, 0.6)) == "enter"
    assert cam.entry_crossing((0.5, 0.6), (0.5, 0.3)) == "exit"


def test_is_billing_zone():
    sz = StoreZones.from_file(LAYOUT)
    assert sz.is_billing("BILLING") is True
    assert sz.is_billing("FOH") is False
    assert sz.is_billing(None) is False


def test_staff_heuristic_picks_longest_present():
    # 5 staff expected; the long-dwell, wide-roaming tracks should be flagged
    summaries = {
        "STAFF1": {"duration_s": 600, "zones": {"FOH", "BILLING", "SKINCARE_WALL"}},
        "STAFF2": {"duration_s": 500, "zones": {"FOH", "MAKEUP_WALL"}},
        "CUST1": {"duration_s": 90, "zones": {"FOH"}},
        "CUST2": {"duration_s": 40, "zones": {"SKINCARE_WALL"}},
    }
    staff = classify_by_heuristic(summaries, staff_count=5, min_staff_dwell_s=240)
    assert "STAFF1" in staff and "STAFF2" in staff
    assert "CUST1" not in staff and "CUST2" not in staff
