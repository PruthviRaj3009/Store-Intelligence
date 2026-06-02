"""Staff vs customer classification.

Two complementary signals (combined; documented in CHOICES.md):

1. Heuristic (always on, pure): staff are present for most of the clip and recur
   across many zones. Given the POS roster tells us exactly how many staff (N)
   work the floor, we mark the N longest-present, widest-roaming tracks as staff,
   provided they exceed a dwell-time floor. This needs no labels and is robust.

2. Optional VLM (Claude Vision): for borderline tracks we crop the person and ask
   a vision model whether they are wearing staff uniform. Enabled only when
   ANTHROPIC_API_KEY is set; the prompt is logged so reviewers can judge it.
"""
from __future__ import annotations

import base64
import os

# Prompt is module-level so DESIGN.md can quote it verbatim.
STAFF_VLM_PROMPT = (
    "You are labelling CCTV crops from a Purplle cosmetics store for analytics. "
    "Store staff wear a branded uniform/apron and a visible ID lanyard, and stand "
    "behind counters. Customers wear street clothes and carry bags/baskets. "
    "Answer with a single JSON object: {\"is_staff\": true|false, \"confidence\": 0..1, "
    "\"reason\": \"...\"}. If unsure, set is_staff=false."
)


def classify_by_heuristic(track_summaries: dict[str, dict], staff_count: int,
                          min_staff_dwell_s: float = 240.0) -> set[str]:
    """track_summaries: visitor_id -> {duration_s, zones:set}.
    Returns the set of visitor_ids judged to be staff."""
    ranked = sorted(
        track_summaries.items(),
        key=lambda kv: (kv[1]["duration_s"], len(kv[1].get("zones", ()))),
        reverse=True,
    )
    staff: set[str] = set()
    for vid, summ in ranked[: max(staff_count, 0)]:
        if summ["duration_s"] >= min_staff_dwell_s:
            staff.add(vid)
    return staff


def classify_crop_with_vlm(image_bytes: bytes) -> dict | None:
    """Ask Claude Vision whether a person crop is staff. Returns parsed dict or
    None if the VLM is unavailable. Best-effort; never raises into the pipeline."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import json

        import anthropic  # optional dependency

        client = anthropic.Anthropic(api_key=api_key)
        b64 = base64.standard_b64encode(image_bytes).decode()
        msg = client.messages.create(
            model=os.getenv("STAFF_VLM_MODEL", "claude-sonnet-4-6"),
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": STAFF_VLM_PROMPT},
                ],
            }],
        )
        text = msg.content[0].text
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start:end + 1]) if start >= 0 else None
    except Exception:  # pragma: no cover - network/optional path
        return None
