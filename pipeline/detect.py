"""
detect.py — YOLOv8 + ByteTrack detection/tracking driver (the only GPU part).

Architecture decision (see CHOICES.md > 'Cross-camera identity'):
  Robust multi-camera person Re-ID is out of scope for a 48h build. Instead we
  designate ONE primary, wide-coverage camera as the source of visitor identity
  and draw the full set of zone polygons (entry line, floor zones, billing) on
  that camera in store_layout.json. The identity FSM (sessionizer) then runs in a
  single, coherent visitor_id space, so entry counts, the funnel, dwell and POS
  conversion are all consistent. The remaining cameras are optional heatmap
  enrichment (--enrich) and are emitted as anonymous zone visits.

Pure logic (zones, geometry, sessionizer, staff heuristic) lives in sibling
modules and is unit-tested without a GPU. This file only does frame I/O + YOLO.

Examples:
  python pipeline/detect.py --primary CAM_1 --device cuda --out data/events.jsonl
  python pipeline/detect.py --all --device cpu          # cpu fallback, all clips
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow direct invocation

from pipeline.sessionizer import Observation, process_observations
from pipeline.staff import classify_by_heuristic
from pipeline.zones import StoreZones

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAYOUT = os.getenv("STORE_LAYOUT_PATH", str(ROOT / "data" / "store_layout.json"))
CLIPS_DIR = ROOT / "data" / "clips"

# Clip wall-clock origin. Aligned to the POS day so billing presence overlaps
# real transactions and the conversion path is exercised. Tune per clip.
DEFAULT_BASE_TS = os.getenv("CLIP_BASE_TS", "2026-04-10T15:30:00+05:30")


def _load_model(weights: str, device: str):
    from ultralytics import YOLO  # heavy import kept local

    model = YOLO(weights)
    model.to(device)
    return model


def _frame_ts(base: datetime, frame_idx: int, fps: float) -> datetime:
    return base + timedelta(seconds=frame_idx / max(fps, 1.0))


def process_camera(camera_id: str, video: Path, zones: StoreZones, *, device: str,
                   weights: str, conf: float, frame_stride: int, base_ts: datetime,
                   staff_count: int, identity: bool, max_frames: int | None = None) -> list[dict]:
    """Run detection+tracking on ONE camera and return its events.

    identity=True  -> this is the primary camera: it owns visitor identity, so we
                      detect entry-line crossings and emit ENTRY/EXIT/REENTRY. Its
                      visitor_ids are the plain "V{track}" space.
    identity=False -> an enrichment (side) camera: we do NOT read its entry line, so
                      it emits only anonymous ZONE_* (and billing-queue) events for
                      the heatmap / per-camera health. Its visitor_ids are namespaced
                      "{camera_id}:V{track}" so they never collide with — or get
                      counted as — real entrants from the primary camera.
    """
    import cv2  # noqa

    cam = zones.camera(camera_id)
    model = _load_model(weights, device)

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or cam.__dict__.get("frame_w", 1920))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
    cap.release()

    # plain "V" for the identity camera; camera-prefixed for enrichment cameras
    vid_prefix = "V" if identity else f"{camera_id}:V"

    observations: list[Observation] = []
    summaries: dict[str, dict] = {}
    last_foot: dict[str, tuple[float, float]] = {}

    # stream=True keeps memory flat over a 20-min clip
    results = model.track(
        source=str(video), stream=True, persist=True, conf=conf,
        classes=[0], tracker="bytetrack.yaml", device=device, verbose=False,
        vid_stride=frame_stride,
    )

    for frame_idx, r in enumerate(results):
        if max_frames is not None and frame_idx >= max_frames:
            break
        ts = _frame_ts(base_ts, frame_idx * frame_stride, fps)
        if r.boxes is None or r.boxes.id is None:
            continue
        xyxy = r.boxes.xyxy.cpu().numpy()
        ids = r.boxes.id.int().cpu().tolist()
        confs = r.boxes.conf.cpu().tolist()

        # foot points this frame (for queue-depth counting in billing)
        feet = []
        for box, tid in zip(xyxy, ids):
            fx = (box[0] + box[2]) / 2.0 / w
            fy = box[3] / h
            feet.append((f"{vid_prefix}{tid}", (fx, fy)))

        for (vid, foot), c in zip(feet, confs):
            zone = cam.zone_for(foot)
            # only the identity camera reads the doorway line -> only it makes ENTRY/EXIT
            boundary = None
            if identity:
                prev = last_foot.get(vid)
                boundary = cam.entry_crossing(prev, foot) if prev else None
            last_foot[vid] = foot

            qd = None
            if zone and zones.is_billing(zone):
                qd = sum(1 for _, f2 in feet if cam.zone_for(f2) == zone)

            observations.append(Observation(
                visitor_id=vid, camera_id=camera_id, ts=ts, zone_id=zone,
                boundary=boundary, confidence=float(c), queue_depth=qd,
            ))
            s = summaries.setdefault(vid, {"first": ts, "last": ts, "zones": set()})
            s["last"] = ts
            if zone:
                s["zones"].add(zone)

    # staff classification (heuristic over track lifetimes)
    track_summ = {
        vid: {"duration_s": (s["last"] - s["first"]).total_seconds(), "zones": s["zones"]}
        for vid, s in summaries.items()
    }
    staff_ids = classify_by_heuristic(track_summ, staff_count)
    for o in observations:
        if o.visitor_id in staff_ids:
            o.is_staff = True

    events = process_observations(zones.store_id, observations,
                                  is_billing=zones.is_billing)
    role = "identity" if identity else "enrich"
    print(f"[detect] {camera_id} ({role}): {len(observations)} obs -> {len(events)} events; "
          f"staff tracks={len(staff_ids)}")
    return events


def resolve_cameras(spec: str | None, all_ids: list[str]) -> list[str] | None:
    """Turn a camera selection like "2 3 1", "CAM_2,CAM_3", or "all" into a list of
    real camera_ids (order preserved). Returns None when no selection was given."""
    if spec is None:
        return None
    if spec.strip().lower() == "all":
        return list(all_ids)
    out: list[str] = []
    for tok in spec.replace(",", " ").split():
        cid = tok if tok.upper().startswith("CAM") else f"CAM_{tok}"
        cid = cid.upper()
        if cid in all_ids and cid not in out:
            out.append(cid)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", help="camera_id to use as identity source")
    ap.add_argument("--all", action="store_true",
                    help="also process every other camera (with zones) as anonymous enrichment")
    ap.add_argument("--cameras",
                    help='which cameras to process: e.g. "2 3 1", "CAM_2,CAM_5", or "all". '
                         "Overrides --all. The identity camera (--primary) is run first if included.")
    ap.add_argument("--device", default=os.getenv("DEVICE", "cuda"))
    ap.add_argument("--weights", default=os.getenv("YOLO_WEIGHTS", "yolov8n.pt"))
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--frame-stride", type=int, default=3, help="process every Nth frame")
    ap.add_argument("--max-frames", type=int, default=None, help="cap processed frames (smoke runs)")
    ap.add_argument("--layout", default=DEFAULT_LAYOUT)
    ap.add_argument("--base-ts", default=DEFAULT_BASE_TS)
    ap.add_argument("--out", default=str(ROOT / "data" / "events.jsonl"))
    args = ap.parse_args()

    zones = StoreZones.from_file(args.layout)
    staff_count = 5
    roster = ROOT / "data" / "staff_roster.json"
    if roster.exists():
        staff_count = json.loads(roster.read_text()).get("staff_count", 5)

    cameras = zones.layout["cameras"]
    all_ids = [c["camera_id"] for c in cameras]

    def clip_for(camera_id: str) -> Path:
        name = next(c["source_file"] for c in cameras if c["camera_id"] == camera_id)
        return CLIPS_DIR / name

    def has_zones(camera_id: str) -> bool:
        return bool(next(c for c in cameras if c["camera_id"] == camera_id).get("zones"))

    # the identity camera: --primary wins, else the layout's declared primary_camera,
    # else the first entry-role camera, else the first camera listed.
    primary = args.primary or zones.layout.get("primary_camera")
    if not primary:
        primary = next((c["camera_id"] for c in cameras
                        if c.get("role") == "entry"), cameras[0]["camera_id"])

    # decide which cameras to process:
    #   --cameras "2 3 1"/"all"  -> exactly those (overrides --all)
    #   --all                    -> primary + every other camera that has zones
    #   neither                  -> just the primary camera
    selected = resolve_cameras(args.cameras, all_ids)
    if selected is None:
        selected = all_ids if args.all else [primary]
    if not selected:
        raise SystemExit(f"[detect] no valid cameras in --cameras {args.cameras!r}; known: {all_ids}")

    # identity goes to the chosen primary if it's in the selection, else the first selected
    identity_cam = primary if primary in selected else selected[0]
    order = [identity_cam] + [c for c in selected if c != identity_cam]

    base_ts = datetime.fromisoformat(args.base_ts).astimezone(timezone.utc)

    events: list[dict] = []
    for cid in order:
        is_identity = (cid == identity_cam)
        if not is_identity and not has_zones(cid):
            print(f"[detect] skip {cid}: no zones defined (e.g. backroom)")
            continue
        cvideo = clip_for(cid)
        if not cvideo.exists():
            if is_identity:
                raise SystemExit(f"[detect] clip not found: {cvideo}. Unzip the footage into data/clips/")
            print(f"[detect] skip {cid}: clip not found {cvideo}")
            continue
        events += process_camera(
            cid, cvideo, zones, device=args.device, weights=args.weights,
            conf=args.conf, frame_stride=args.frame_stride, base_ts=base_ts,
            staff_count=staff_count, identity=is_identity, max_frames=args.max_frames,
        )

    events.sort(key=lambda e: e["timestamp"])  # one merged, time-ordered stream

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    cams_run = sorted({e["camera_id"] for e in events})
    print(f"[detect] wrote {len(events)} events from cameras {cams_run} -> {out}")


if __name__ == "__main__":
    main()
