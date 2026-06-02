"""Per-camera zone + entry-line resolver, driven by store_layout.json (pure)."""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.geometry import Point, crossing_direction, point_in_polygon


class CameraZones:
    def __init__(self, cam_cfg: dict):
        self.camera_id = cam_cfg["camera_id"]
        self.role = cam_cfg.get("role", "floor")
        self.zones = [(z["zone_id"], [tuple(pt) for pt in z["polygon"]])
                      for z in cam_cfg.get("zones", [])]
        self.entry_line = cam_cfg.get("entry_line")

    def zone_for(self, foot: Point) -> str | None:
        """Return the zone whose polygon contains the foot point (first match)."""
        for zid, poly in self.zones:
            if point_in_polygon(foot, poly):
                return zid
        return None

    def entry_crossing(self, prev: Point, cur: Point) -> str | None:
        """'enter'/'exit'/None for the doorway line (entry cameras only)."""
        if not self.entry_line:
            return None
        return crossing_direction(
            prev, cur,
            tuple(self.entry_line["p1"]), tuple(self.entry_line["p2"]),
            self.entry_line.get("outside_side", "below"),
        )


class StoreZones:
    def __init__(self, layout: dict):
        self.layout = layout
        self.store_id = layout["store_id"]
        self.cameras = {c["camera_id"]: CameraZones(c) for c in layout["cameras"]}
        self.zone_type = {z["zone_id"]: z["type"] for z in layout["zones"]}

    @classmethod
    def from_file(cls, path: str) -> "StoreZones":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def camera(self, camera_id: str) -> CameraZones:
        return self.cameras[camera_id]

    def is_billing(self, zone_id: str | None) -> bool:
        return bool(zone_id) and self.zone_type.get(zone_id) == "billing"
