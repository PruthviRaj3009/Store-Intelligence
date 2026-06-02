# Store Intelligence

Turn raw in-store CCTV into live store analytics — entries, zone dwell, a conversion funnel,
anomalies — with the **offline conversion rate** as the north-star metric.

Built for the Apex/Purplle "Store Intelligence" challenge. Store: `ST1008` Brigade_Bangalore.

```
CCTV clips ─► detection (YOLOv8+ByteTrack) ─► events.jsonl ─► FastAPI + Postgres ─► dashboard
                                                                     ▲ POS transactions
```

---

## Quick start (5 commands)

```bash
git clone <repo-url> && cd store-intelligence
docker compose up -d --build            # 1. start Postgres + API (auto-ingests data/events.jsonl)
curl localhost:8000/health              # 2. service + per-camera feed status
curl localhost:8000/stores/ST1008/metrics   # 3. conversion rate, visitors, dwell, queue
open http://localhost:8000/dashboard    # 4. live dashboard (or visit in a browser)
                                        # 5. full API docs at http://localhost:8000/docs
```

`docker compose up` starts the **API + database** immediately and auto-ingests the prepared
`data/events.jsonl`, so every endpoint works on a cold clone with no GPU.

## Run the detection pipeline on the clips

The detection step is GPU-bound and runs as a **separate, profiled service** so it never
blocks the API.

```bash
# put the 5 clips in data/clips/  (CAM 1.mp4 … CAM 5.mp4)
docker compose --profile pipeline run --rm pipeline    # GPU run → writes data/events.jsonl
docker compose restart api                              # API re-ingests the new events
```

Without Docker (e.g. a CPU dev box):
```bash
pip install -r pipeline/requirements-pipeline.txt
python scripts/prepare_data.py                          # normalize POS + staff roster
python -m pipeline.detect --primary CAM_2 --device cpu --out data/events.jsonl
```

**Calibrating zones** (one-time per camera set): overlay the configured polygons on a real
frame and adjust `data/store_layout.json` until they line up:
```bash
python -m pipeline.calibrate --frame 900    # writes data/calib/*.png
```

## Endpoints
| Method | Path | Returns |
|---|---|---|
| POST | `/events/ingest` | ingest events (idempotent, ≤500/batch, partial success) |
| GET | `/stores/{id}/metrics` | unique visitors, **conversion rate**, dwell/zone, queue, abandonment |
| GET | `/stores/{id}/funnel` | Entry → Zone → Billing → Purchase, session-based |
| GET | `/stores/{id}/heatmap` | zone visit/dwell scores (0–100) + `data_confidence` |
| GET | `/stores/{id}/anomalies` | queue spike, conversion drop, dead zone + `suggested_action` |
| GET | `/health` | DB status + per-camera `STALE_FEED` |

## Tests
```bash
pip install -r requirements.txt
pytest --cov=app --cov=pipeline          # 28 tests, ~93% coverage
```

## Layout
```
app/        FastAPI service (ingestion, metrics, funnel, anomalies, health)
pipeline/   YOLOv8+ByteTrack detection, zone/geometry/sessionizer (pure) + GPU Dockerfile
scripts/    prepare_data.py (POS→clean), simulate_events.py (dev/test event generator)
data/       store_layout.json, pos_transactions.csv, events.jsonl, clips/
docs/       DESIGN.md, CHOICES.md
tests/      pytest suite (edge cases + AI prompt blocks)
```

## Docs
- **`docs/DESIGN.md`** — architecture + AI-assisted decisions.
- **`docs/CHOICES.md`** — model / schema / API decisions with trade-offs.
- **`WALKTHROUGH.md`** — code study guide.
- **`RESUME.md`** — build status / handoff.

## Notes & assumptions
- One store (`ST1008`), 5 cameras (CAM 3 = entrance, CAM 5 = billing, CAM 1/2 = floor,
  CAM 4 = backroom). See `docs/CHOICES.md > Data reconciliation`.
- Relative-time logic uses the **latest event time** (the "feed clock"), so recorded footage
  behaves like a live feed.
- Conversion correlation is time + store (no `customer_id` in POS): billing presence within
  5 min before a sale = converted.
