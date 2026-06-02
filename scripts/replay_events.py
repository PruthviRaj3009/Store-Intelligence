"""
replay_events.py — stream events.jsonl into the running API in time order so the
live dashboard visibly fills up (proof the pipeline and API are genuinely connected,
not batch-loaded).

Usage:
  python scripts/replay_events.py --api http://localhost:8000 --speed 120
    --speed = how many event-seconds to compress into one real second (120 = 2 min/sec).
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def _post(api: str, events: list[dict]) -> None:
    data = json.dumps({"events": events}).encode()
    req = urllib.request.Request(f"{api}/events/ingest", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--events", default=str(ROOT / "data" / "events.jsonl"))
    ap.add_argument("--speed", type=float, default=120.0, help="event-seconds per real second")
    ap.add_argument("--batch", type=int, default=20)
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.events).read_text(encoding="utf-8").splitlines() if l.strip()]
    rows.sort(key=lambda e: e["timestamp"])
    print(f"[replay] {len(rows)} events -> {args.api} at {args.speed}x")

    def t(e):
        return datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))

    start = t(rows[0])
    buf: list[dict] = []
    wall0 = time.time()
    sent = 0
    for e in rows:
        target = (t(e) - start).total_seconds() / args.speed
        while time.time() - wall0 < target:
            if buf:
                _post(args.api, buf); sent += len(buf); buf = []
            time.sleep(0.05)
        buf.append(e)
        if len(buf) >= args.batch:
            _post(args.api, buf); sent += len(buf); buf = []
    if buf:
        _post(args.api, buf); sent += len(buf)
    print(f"[replay] done, {sent} events streamed")


if __name__ == "__main__":
    main()
