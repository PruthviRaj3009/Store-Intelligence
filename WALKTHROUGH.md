# Code & Architecture Walkthrough (study guide)

> Goal: after reading this you can explain **every** part of the system in your own
> words and answer the follow-up video questions. Read the files in the order below
> with this guide open beside them. Don't memorise — understand the *why*.

---

## 0. The one-sentence mental model
> Raw video → (detection) a stream of **events** about people moving through zones →
> (API) those events are turned into **business metrics**, the headline one being
> **conversion rate** = paying visitors ÷ unique visitors.

Everything in the repo is one of those two halves, plus plumbing (Docker, DB, logs).

## 1. The data-flow diagram (draw this from memory)
```
CCTV clip ─► YOLOv8 + ByteTrack ─► per-frame detections (track_id, box)
            (pipeline/detect.py)        │
                                        ▼
                          Observation(visitor, zone, boundary, ts, queue_depth)
                                        │
                          pipeline/sessionizer.py  ── a state machine per visitor
                                        ▼
                              events.jsonl  (ENTRY, ZONE_DWELL, BILLING_QUEUE_JOIN…)
                                        │  POST /events/ingest
                                        ▼
                     Postgres (app/tables.py)  +  POS transactions (app/pos.py)
                                        │
                       app/analytics.py  ── builds "sessions", correlates POS
                                        ▼
        /metrics  /funnel  /heatmap  /anomalies  /health   (app/*.py + main.py)
```

## 2. Read order (simple → complex)
Spend ~10 min per file. Tick them off.

### A. Start with the data (so the rest has meaning)
1. `data/store_layout.json` — the store: zones (ENTRY, FOH, SKINCARE_WALL, MAKEUP_WALL, ACCESSORIES, BILLING), which camera sees them, and each camera's polygons + entry line. **This is the config that drives both halves.**
2. `data/pos_transactions.csv` + `scripts/prepare_data.py` — how the messy 101-row POS export became 24 clean transactions, and where the 5-person staff roster came from. Run it: `python scripts/prepare_data.py`.

### B. The detection half (Part A) — mostly *pure* Python, easy to follow
3. `pipeline/geometry.py` — 3 ideas only: **point-in-polygon** (is a person standing in a zone?), **segment intersection**, and **crossing_direction** (did they cross the doorway line inward = ENTER or outward = EXIT?). All in normalized 0–1 coordinates.
4. `pipeline/zones.py` — wraps the layout: `zone_for(foot_point)` returns which zone a person is in; `entry_crossing(prev, cur)` returns 'enter'/'exit'. Thin layer over geometry.
5. `pipeline/sessionizer.py` — **the heart of Part A. Read this twice.** A finite-state machine: you feed it time-ordered `Observation`s and it emits the event stream. Understand:
   - how an **ENTRY** vs **REENTRY** is decided (the `has_exited` flag),
   - how **ZONE_ENTER/EXIT** fire on zone change and **ZONE_DWELL** every 30 s,
   - how **BILLING_QUEUE_JOIN/ABANDON** work.
6. `pipeline/staff.py` — two ways to spot staff: a **heuristic** (the N longest-present, widest-roaming tracks, where N=5 from the roster) and an optional **Claude Vision** call (the prompt is in the file). Know why heuristic is the default.
7. `pipeline/detect.py` — the **only GPU part**. It runs YOLO+ByteTrack on the primary camera, turns each tracked box into an `Observation`, then calls the sessionizer. Note the **single-primary-camera** decision (see §3.2) — this is the most likely thing they'll grill you on.

### C. The API half (Part B) — where events become metrics
8. `app/models.py` — the **event schema** (Pydantic). This is the contract the pipeline must emit and the API validates.
9. `app/tables.py` — the two DB tables: `events` and `pos_transactions`. Note `event_id` is the primary key = idempotency.
10. `app/analytics.py` — **the heart of Part B. Read twice.** Three ideas:
    - `build_sessions()` — collapse the event stream into one **VisitorSession per visitor_id** (this is why re-entries don't double-count),
    - `apply_conversion()` — mark a session converted if it was in BILLING within 5 min before a POS txn,
    - `feed_now()` / `resolve_window()` — the **"feed clock"** (relative time = latest event, not wall-clock).
11. `app/metrics.py`, `app/funnel.py`, `app/anomalies.py`, `app/health.py` — each is a thin function that calls analytics and shapes a JSON response. Read `metrics.py` first.
12. `app/ingestion.py` — idempotent (skip seen `event_id`s) + partial-success (reject bad events individually).
13. `app/main.py` — wires routes, runs startup (create tables, load POS, auto-ingest `events.jsonl`), and the **503/500 error handlers** (graceful degradation).
14. `app/logging_mw.py` — one JSON log line per request (trace_id, latency, status…).

### D. The plumbing (Part C)
15. `docker-compose.yml` + `app/Dockerfile` + `pipeline/Dockerfile.gpu` — `docker compose up` = Postgres + API; detection is a separate GPU-profiled service.

## 3. The 5 decisions you MUST be able to defend
(These map directly to the kind of follow-up questions in the brief.)

1. **Why YOLOv8 + ByteTrack?** Fast, well-documented, pretrained on COCO (person class), ByteTrack gives stable IDs so a *group of 3 = 3 tracks = 3 ENTRYs*. We value working + explainable over exotic.
2. **Cross-camera identity (the hard one).** We did **not** attempt multi-camera Re-ID in 48h. Instead one **primary wide-coverage camera** owns visitor identity (entry line + all zones drawn on it) → one coherent `visitor_id` space → counts/funnel/conversion stay consistent. *Failure mode:* a person only ever seen by a side camera is missed. *With more time:* OSNet Re-ID + homography to a floor plan.
3. **Conversion correlation.** No `customer_id` in POS → we correlate by **time + store**: in BILLING within 5 min before a sale = converted. Trade-off: a browser near billing at the wrong moment could be mis-attributed; the 5-min window bounds that.
4. **Feed clock (event-time not wall-clock).** Lets recorded April footage behave like a live feed; for a real feed, latest-event ≈ now. Without it every metric would read "stale".
5. **Re-entry / staff / low-confidence.** Re-entry reuses the id → `REENTRY`, never a 2nd ENTRY. Staff flagged and excluded from every customer metric. Low-confidence events are **kept and flagged**, never silently dropped.

## 4. Likely follow-up questions → where the answer lives
| Question style | Look at | Your answer hook |
|---|---|---|
| "Group of 3 enters — 1 or 3 events?" | `sessionizer.py`, ByteTrack | 3 — one track id each |
| "Customer leaves and a different one enters 3 s later from same spot — what breaks?" | `detect.py` foot-point + ByteTrack id reuse | id may be reassigned → could mislabel REENTRY; mitigated by time gap, fixed by Re-ID |
| "At 40 live stores, what breaks first in /funnel?" | `analytics.build_sessions` loads all events in window into memory | rebuild per-request + full-window scan → move to incremental/materialised aggregates, index on (store, ts) |
| "You chose rule-based zones over a VLM — when would you switch?" | `staff.py` VLM hook | switch if uniforms/zones ambiguous and labelled data scarce; VLM cost/latency is the trade-off |
| "DB goes down — what does a user see?" | `main.py` handlers + `db.py` | structured 503, no stack trace |

## 5. Learn by running it (the fastest way to understand)
```powershell
cd D:\PP\store-intelligence
.\.venv\Scripts\python.exe scripts\simulate_events.py --seed 7      # make events
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload          # start API
# open http://127.0.0.1:8000/docs  → click each endpoint → see the JSON
```
Then **change an input and watch the output move**: edit `simulate_events.py` (e.g. add more abandoners), regenerate, refresh `/metrics`. Seeing the numbers react is how the logic sticks.

## 6. A good study order for ONE focused hour
1. (10 min) §1–§2A here + skim `store_layout.json`.
2. (20 min) `sessionizer.py` — trace one visitor through it on paper.
3. (20 min) `analytics.py` — trace how 651 events become "49 visitors, 24 converted".
4. (10 min) Run §5 and poke `/docs`.
5. (Anytime) Re-read §3 until you can say all 5 decisions out loud.
```
```
