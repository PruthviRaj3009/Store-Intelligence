"""Store layout loading + zone metadata helpers."""
from __future__ import annotations

import functools
import json

from app.config import settings


@functools.lru_cache(maxsize=1)
def layout() -> dict:
    with open(settings.STORE_LAYOUT_PATH, encoding="utf-8") as f:
        return json.load(f)


def zone_types() -> dict[str, str]:
    """zone_id -> type ('entry' | 'floor' | 'billing')."""
    return {z["zone_id"]: z["type"] for z in layout().get("zones", [])}


def floor_zone_ids() -> list[str]:
    return [z["zone_id"] for z in layout().get("zones", []) if z["type"] == "floor"]


def store_ids() -> list[str]:
    return [layout()["store_id"]]
