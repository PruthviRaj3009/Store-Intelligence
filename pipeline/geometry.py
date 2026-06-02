"""Pure geometry helpers for zone/line logic (no torch/cv2 — unit-testable).

All coordinates are normalized to [0, 1] relative to the frame so the same
polygons work regardless of resolution.
"""
from __future__ import annotations

Point = tuple[float, float]
Polygon = list[Point]


def point_in_polygon(p: Point, poly: Polygon) -> bool:
    """Ray-casting point-in-polygon test."""
    x, y = p
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _side(p: Point, a: Point, b: Point) -> float:
    """Signed area sign: >0 left of a->b, <0 right, 0 on the line."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def segments_intersect(p1: Point, p2: Point, a: Point, b: Point) -> bool:
    """Do segment p1->p2 and a->b cross?"""
    d1 = _side(p1, a, b)
    d2 = _side(p2, a, b)
    d3 = _side(a, p1, p2)
    d4 = _side(b, p1, p2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def crossing_direction(prev: Point, cur: Point, line_p1: Point, line_p2: Point,
                       outside_side: str = "below") -> str | None:
    """Return 'enter' / 'exit' / None for a track moving prev->cur across a line.

    `outside_side` names where 'outside the store' is relative to the line:
      - 'below'  -> larger y (image y grows downward) is outside
      - 'above'  -> smaller y is outside
      - 'left'   -> smaller x is outside
      - 'right'  -> larger x is outside
    Entering = moving from the outside half-plane to the inside half-plane.
    """
    if not segments_intersect(prev, cur, line_p1, line_p2):
        return None

    def is_outside(pt: Point) -> bool:
        if outside_side == "below":
            return pt[1] > (line_p1[1] + line_p2[1]) / 2
        if outside_side == "above":
            return pt[1] < (line_p1[1] + line_p2[1]) / 2
        if outside_side == "left":
            return pt[0] < (line_p1[0] + line_p2[0]) / 2
        return pt[0] > (line_p1[0] + line_p2[0]) / 2

    prev_out, cur_out = is_outside(prev), is_outside(cur)
    if prev_out and not cur_out:
        return "enter"
    if cur_out and not prev_out:
        return "exit"
    return None


def bbox_foot(bbox_xyxy: tuple[float, float, float, float], w: int, h: int) -> Point:
    """Normalized 'foot' point (bottom-centre of the bbox) — the floor contact
    point, which is the right anchor for zone membership."""
    x1, y1, x2, y2 = bbox_xyxy
    return ((x1 + x2) / 2.0 / w, y2 / h)
