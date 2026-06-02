"""
simulate_events.py — DEV/TEST event generator (NOT the detection pipeline).

Purpose: exercise the API end-to-end without a GPU, power the test suite, and
drive the live dashboard demo. It produces events in the exact production schema,
deliberately seeded so runs are reproducible, and aligned to the REAL POS
timestamps so the conversion-correlation path is genuinely tested.

The submitted detection output comes from pipeline/detect.py run on the footage;
this simulator only fabricates plausible movement to validate downstream logic.
It intentionally injects every known edge case (staff, re-entry, group entry,
low-confidence, queue spike, abandonment) so tests can assert on them.

Run:  python scripts/simulate_events.py [--seed 7] [--out data/events.jsonl]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = json.loads((ROOT / "data" / "store_layout.json").read_text(encoding="utf-8"))
STORE_ID = LAYOUT["store_id"]
FLOOR_ZONES = [z["zone_id"] for z in LAYOUT["zones"] if z["type"] == "floor"]
ENTRY_CAM = next(c["camera_id"] for c in LAYOUT["cameras"] if c["role"] == "entry")
BILLING_CAM = next((c["camera_id"] for c in LAYOUT["cameras"] if c["role"] == "billing"), ENTRY_CAM)
FLOOR_CAM = next((c["camera_id"] for c in LAYOUT["cameras"] if c["role"] == "floor"), ENTRY_CAM)
BACKROOM_CAM = next((c["camera_id"] for c in LAYOUT["cameras"] if c["role"] == "backroom"), None)

# Which camera(s) physically cover each zone (from store_layout 'covers_zones').
# Lets us attribute a zone visit to a real covering camera, so floor traffic is
# spread across every floor camera instead of a single hard-coded one.
ZONE_CAMS: dict[str, list[str]] = {}
for _c in LAYOUT["cameras"]:
    for _z in _c.get("covers_zones", []):
        ZONE_CAMS.setdefault(_z, []).append(_c["camera_id"])


def cam_for_zone(rng: random.Random, zone: str) -> str:
    """Pick a camera that covers this zone (random among coverers for realism)."""
    cams = ZONE_CAMS.get(zone)
    return rng.choice(cams) if cams else FLOOR_CAM


def load_pos():
    p = ROOT / "data" / "pos_transactions.csv"
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    out = []
    for r in rows:
        ts = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
        out.append((r["transaction_id"], ts))
    return out


class EventWriter:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.events: list[dict] = []
        self._n = 0

    def emit(self, *, store_id, camera_id, visitor_id, event_type, ts, zone_id=None,
             dwell_ms=0, is_staff=False, confidence=None, queue_depth=None,
             sku_zone=None, session_seq=None):
        self._n += 1
        if confidence is None:
            confidence = round(self.rng.uniform(0.55, 0.97), 2)
        self.events.append({
            "event_id": f"EVT_{visitor_id}_{self._n:05d}",
            "store_id": store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "zone_id": zone_id,
            "dwell_ms": dwell_ms,
            "is_staff": is_staff,
            "confidence": confidence,
            "metadata": {"queue_depth": queue_depth, "sku_zone": sku_zone, "session_seq": session_seq},
        })

    def visit_zone(self, vid, zone, t0, seconds, seq, staff=False):
        """ZONE_ENTER, periodic ZONE_DWELL every 30s, ZONE_EXIT.

        The whole visit is attributed to one camera that covers this zone, so the
        per-camera feeds reflect which physical camera actually saw the movement.
        """
        cam = cam_for_zone(self.rng, zone)
        self.emit(store_id=STORE_ID, camera_id=cam, visitor_id=vid,
                  event_type="ZONE_ENTER", ts=t0, zone_id=zone, sku_zone=zone,
                  is_staff=staff, session_seq=seq)
        elapsed = 30
        while elapsed <= seconds:
            self.emit(store_id=STORE_ID, camera_id=cam, visitor_id=vid,
                      event_type="ZONE_DWELL", ts=t0 + timedelta(seconds=elapsed),
                      zone_id=zone, dwell_ms=elapsed * 1000, sku_zone=zone,
                      is_staff=staff, session_seq=seq)
            elapsed += 30
        self.emit(store_id=STORE_ID, camera_id=cam, visitor_id=vid,
                  event_type="ZONE_EXIT", ts=t0 + timedelta(seconds=seconds),
                  zone_id=zone, dwell_ms=seconds * 1000, sku_zone=zone,
                  is_staff=staff, session_seq=seq)


def build(seed: int) -> list[dict]:
    rng = random.Random(seed)
    w = EventWriter(rng)
    pos = load_pos()

    # ---- converting visitors: one per POS txn, in billing just before the sale ----
    for vi, (txn_id, t_txn) in enumerate(pos):
        vid = f"VIS_C{vi:03d}"
        seq = 1
        entry_t = t_txn - timedelta(minutes=rng.randint(8, 20))
        w.emit(store_id=STORE_ID, camera_id=ENTRY_CAM, visitor_id=vid,
               event_type="ENTRY", ts=entry_t, session_seq=seq); seq += 1
        # browse 1-2 floor zones
        t = entry_t + timedelta(seconds=rng.randint(20, 60))
        for zone in rng.sample(FLOOR_ZONES, k=rng.randint(1, 2)):
            secs = rng.randint(40, 150)
            w.visit_zone(vid, zone, t, secs, seq); seq += 1
            t += timedelta(seconds=secs + rng.randint(10, 40))
        # join billing queue within the conversion window before the txn
        join_t = t_txn - timedelta(minutes=rng.randint(1, 4))
        qd = rng.randint(0, 4)
        w.emit(store_id=STORE_ID, camera_id=BILLING_CAM, visitor_id=vid,
               event_type="BILLING_QUEUE_JOIN", ts=join_t, zone_id="BILLING",
               queue_depth=qd, session_seq=seq); seq += 1
        w.emit(store_id=STORE_ID, camera_id=BILLING_CAM, visitor_id=vid,
               event_type="ZONE_DWELL", ts=join_t + timedelta(seconds=30),
               zone_id="BILLING", dwell_ms=30000, session_seq=seq); seq += 1
        # exit shortly after paying
        w.emit(store_id=STORE_ID, camera_id=ENTRY_CAM, visitor_id=vid,
               event_type="EXIT", ts=t_txn + timedelta(minutes=rng.randint(1, 3)),
               session_seq=seq)

    if not pos:
        return w.events
    base = pos[0][1]
    last = pos[-1][1]

    # ---- non-converting browsers (leave without buying) ----
    for bi in range(18):
        vid = f"VIS_B{bi:03d}"
        entry_t = base + timedelta(minutes=rng.randint(0, max(1, int((last - base).total_seconds() // 60))))
        w.emit(store_id=STORE_ID, camera_id=ENTRY_CAM, visitor_id=vid,
               event_type="ENTRY", ts=entry_t, session_seq=1)
        t = entry_t + timedelta(seconds=30)
        for zone in rng.sample(FLOOR_ZONES, k=rng.randint(1, 3)):
            secs = rng.randint(25, 120)
            w.visit_zone(vid, zone, t, secs, 2)
            t += timedelta(seconds=secs + 20)
        w.emit(store_id=STORE_ID, camera_id=ENTRY_CAM, visitor_id=vid,
               event_type="EXIT", ts=t + timedelta(seconds=20), session_seq=9)

    # ---- billing abandoners (join queue, then leave without buying) ----
    for ai in range(4):
        vid = f"VIS_A{ai:03d}"
        entry_t = base + timedelta(minutes=rng.randint(0, 30))
        w.emit(store_id=STORE_ID, camera_id=ENTRY_CAM, visitor_id=vid,
               event_type="ENTRY", ts=entry_t, session_seq=1)
        join_t = entry_t + timedelta(minutes=2)
        w.emit(store_id=STORE_ID, camera_id=BILLING_CAM, visitor_id=vid,
               event_type="BILLING_QUEUE_JOIN", ts=join_t, zone_id="BILLING",
               queue_depth=rng.randint(3, 6), session_seq=2)
        w.emit(store_id=STORE_ID, camera_id=BILLING_CAM, visitor_id=vid,
               event_type="BILLING_QUEUE_ABANDON", ts=join_t + timedelta(minutes=2),
               zone_id="BILLING", session_seq=3)
        w.emit(store_id=STORE_ID, camera_id=ENTRY_CAM, visitor_id=vid,
               event_type="EXIT", ts=join_t + timedelta(minutes=3), session_seq=4)

    # ---- staff (must be EXCLUDED from customer metrics) ----
    n_staff = json.loads((ROOT / "data" / "staff_roster.json").read_text())["staff_count"]
    for si in range(n_staff):
        vid = f"VIS_STAFF{si:02d}"
        w.emit(store_id=STORE_ID, camera_id=ENTRY_CAM, visitor_id=vid,
               event_type="ENTRY", ts=base + timedelta(minutes=si), is_staff=True, session_seq=1)
        for k, zone in enumerate(rng.sample(FLOOR_ZONES, k=min(3, len(FLOOR_ZONES)))):
            w.visit_zone(vid, zone, base + timedelta(minutes=5 + k * 10), 300, k + 2, staff=True)

    # ---- backroom camera: staff-only presence, spread across the day so the feed
    #      is live (not stale) but never pollutes customer metrics or the heatmap ----
    if BACKROOM_CAM and n_staff:
        span_min = max(1, int((last - base).total_seconds() // 60))
        for ri in range(6):
            t = base + timedelta(minutes=rng.randint(0, span_min))
            w.emit(store_id=STORE_ID, camera_id=BACKROOM_CAM,
                   visitor_id=f"VIS_STAFF{ri % n_staff:02d}", event_type="ZONE_DWELL",
                   ts=t, zone_id=None, dwell_ms=60000, is_staff=True, session_seq=60 + ri)

    # ---- a re-entry (same visitor leaves and returns -> REENTRY, not 2nd ENTRY) ----
    vid = "VIS_C000"  # an existing converter steps out and returns
    re_t = last + timedelta(minutes=2)
    w.emit(store_id=STORE_ID, camera_id=ENTRY_CAM, visitor_id=vid,
           event_type="REENTRY", ts=re_t, confidence=0.62, session_seq=99)
    w.visit_zone(vid, FLOOR_ZONES[0], re_t + timedelta(seconds=20), 60, 100)

    # ---- a group of 3 entering together (must count as 3) ----
    g_t = base + timedelta(minutes=7)
    for gi in range(3):
        vid = f"VIS_G{gi:02d}"
        w.emit(store_id=STORE_ID, camera_id=ENTRY_CAM, visitor_id=vid,
               event_type="ENTRY", ts=g_t + timedelta(seconds=gi), confidence=0.7, session_seq=1)
        w.visit_zone(vid, rng.choice(FLOOR_ZONES), g_t + timedelta(seconds=30 + gi), 50, 2)
        w.emit(store_id=STORE_ID, camera_id=ENTRY_CAM, visitor_id=vid,
               event_type="EXIT", ts=g_t + timedelta(minutes=6), session_seq=3)

    # ---- freshness pass: ensure every camera has a recent event so none reads as a
    #      STALE feed on the live demo. Uses staff presence (excluded from customer
    #      metrics) at a closing walkthrough — realistic and metric-neutral. ----
    def _ts(e):
        return datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))

    if w.events:
        store_last = max(_ts(e) for e in w.events)
        last_by_cam: dict[str, datetime] = {}
        for e in w.events:
            t = _ts(e)
            if e["camera_id"] not in last_by_cam or t > last_by_cam[e["camera_id"]]:
                last_by_cam[e["camera_id"]] = t
        for ci, cam in enumerate(c["camera_id"] for c in LAYOUT["cameras"]):
            seen = last_by_cam.get(cam)
            if seen is None or (store_last - seen).total_seconds() > 8 * 60:
                w.emit(store_id=STORE_ID, camera_id=cam,
                       visitor_id=f"VIS_STAFF{ci % max(1, n_staff):02d}",
                       event_type="ZONE_DWELL", ts=store_last - timedelta(minutes=1),
                       zone_id=None, dwell_ms=60000, is_staff=True, session_seq=70 + ci)

    w.events.sort(key=lambda e: e["timestamp"])
    return w.events


def resolve_cameras(spec, all_ids):
    """"2 3 1" / "CAM_2,CAM_5" / "all" -> list of real camera_ids (None if not given)."""
    if spec is None:
        return None
    if str(spec).strip().lower() == "all":
        return list(all_ids)
    out = []
    for tok in str(spec).replace(",", " ").split():
        cid = tok if tok.upper().startswith("CAM") else f"CAM_{tok}"
        cid = cid.upper()
        if cid in all_ids and cid not in out:
            out.append(cid)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "data" / "events.jsonl"))
    ap.add_argument("--cameras",
                    help='keep only these cameras: e.g. "2 3 1", "CAM_2,CAM_5", or "all" '
                         "(default: all cameras)")
    args = ap.parse_args()

    events = build(args.seed)

    all_ids = [c["camera_id"] for c in LAYOUT["cameras"]]
    selected = resolve_cameras(args.cameras, all_ids)
    if selected is not None:
        events = [e for e in events if e["camera_id"] in selected]
        print(f"[simulate] filtered to cameras {selected}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    n_staff = sum(1 for e in events if e["is_staff"])
    n_visitors = len({e["visitor_id"] for e in events if not e["is_staff"]})
    print(f"[simulate] wrote {len(events)} events -> {out}")
    print(f"[simulate] {n_visitors} customer visitors, {n_staff} staff events, "
          f"seed={args.seed}")


if __name__ == "__main__":
    main()
