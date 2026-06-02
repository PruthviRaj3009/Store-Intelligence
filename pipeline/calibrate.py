"""
calibrate.py — dump a representative frame from each clip with the configured
zone polygons + entry line drawn on top, so polygons can be tuned visually.

Run on the machine that has the clips:
  python pipeline/calibrate.py --frame 1200 --out data/calib
Then open data/calib/*.png, adjust polygons in data/store_layout.json, re-run.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow direct invocation

from pipeline.zones import StoreZones

ROOT = Path(__file__).resolve().parents[1]
CLIPS_DIR = ROOT / "data" / "clips"
DEFAULT_LAYOUT = os.getenv("STORE_LAYOUT_PATH", str(ROOT / "data" / "store_layout.json"))


def _draw(cam_cfg, frame):
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    for z in cam_cfg.get("zones", []):
        pts = np.array([[int(x * w), int(y * h)] for x, y in z["polygon"]], dtype=np.int32)
        cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
        cx, cy = pts.mean(axis=0).astype(int)
        cv2.putText(frame, z["zone_id"], (cx - 40, cy), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 255, 0), 2)
    line = cam_cfg.get("entry_line")
    if line:
        p1 = (int(line["p1"][0] * w), int(line["p1"][1] * h))
        p2 = (int(line["p2"][0] * w), int(line["p2"][1] * h))
        cv2.line(frame, p1, p2, (0, 0, 255), 3)
        cv2.putText(frame, "ENTRY LINE", p1, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return frame


def main() -> None:
    import cv2

    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", type=int, default=900, help="frame index to grab")
    ap.add_argument("--layout", default=DEFAULT_LAYOUT)
    ap.add_argument("--out", default=str(ROOT / "data" / "calib"))
    args = ap.parse_args()

    zones = StoreZones.from_file(args.layout)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for cam in zones.layout["cameras"]:
        video = CLIPS_DIR / cam["source_file"]
        if not video.exists():
            print(f"[calibrate] missing {video}, skipping")
            continue
        cap = cv2.VideoCapture(str(video))
        cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            print(f"[calibrate] could not read frame {args.frame} from {video}")
            continue
        frame = _draw(cam, frame)
        dest = out / f"{cam['camera_id']}_frame{args.frame}.png"
        cv2.imwrite(str(dest), frame)
        print(f"[calibrate] wrote {dest}")


if __name__ == "__main__":
    main()
