# RESUME — Store Intelligence Challenge (handoff)

> Read this first tomorrow. It captures exactly where we stopped and how to continue.
> Last session: 2026-05-31 (evening). Challenge due **2026-06-03**.

## STATUS (updated 2026-06-01, later session)
**Parts A, B, C, D, E are all built and verified on this machine.** Remaining = the GPU
full-quality detection run + git submission (Task #8, needs the friend's GPU machine).
- ✅ Tests: **28 passing, 93% coverage** (`pytest`), all required edge cases + AI prompt blocks.
- ✅ Docs: `docs/DESIGN.md`, `docs/CHOICES.md` (both >250 words), `README.md` (5-command).
- ✅ Dashboard: web UI at `/dashboard` + `scripts/replay_events.py` for live streaming.
- ✅ **Acceptance gate proven on a real `docker compose up`**: Postgres+API up in 4s,
  `/metrics` valid JSON (49 visitors / 0.49 conversion), **DB-down → structured 503**, recovery OK.
- ⏳ Task #8 only: on the GPU machine, calibrate CAM_2 floor zones, run full detection →
  regenerate `data/events.jsonl`, then `docker compose up` + push to a private git repo + invite reviewer.

## TL;DR — where we are
- **Repo:** `D:\PP\store-intelligence\` (built on this machine; runs identically on the friend's GPU machine via Docker).
- **Working:** Data prep ✅, full **API (Part B)** ✅ validated end-to-end, **Docker** ✅ (API image builds, gate passes), detection **pipeline (Part A)** ✅ **validated on the REAL footage** (CPU).
- **Phase 1 DONE (2026-06-01):** CV deps installed; ran YOLOv8n+ByteTrack on the real clips. Confirmed camera roles by eye (CAM_3=entry, CAM_5=billing, CAM_1/2=floor, CAM_4=backroom) and corrected `store_layout.json`. Data-drove the entry-line position via a crossing-count sweep (y=0.40 full-width) and added **crossing debounce** (CROSSING_DEBOUNCE_S) to kill loiter oscillation. CAM_3 now yields a clean event stream (2 ENTRY / 1 EXIT, valid schema, unique ids) over the 2-min clip. Clips are ~2.1–2.5 min, 1080p, 25–30 fps (not 20 min).
- **Scope decision from user:** "complete Phase 1 only" — Tests/docs/dashboard deferred (tasks #5/#6/#7), full multi-camera + GPU run is #8.
- **Next remaining calibration (do on GPU machine, #8):** tune CAM_2 floor-zone polygons (same sweep method), run the primary camera for the full entry+floor+billing stream, regenerate `data/events.jsonl`, and validate counts against eyeballed footage. ByteTrack id-fragmentation on short CPU clips inflates track count — full-length, full-fps GPU runs will reduce this.

## The challenge (1-paragraph reminder)
Build an end-to-end system: raw CCTV → detection events → FastAPI "Store Intelligence" API (metrics, funnel, heatmap, anomalies, health) → optional live dashboard. Must run via `docker compose up`. North-star metric = **offline conversion rate**. Scoring: Detection 30 / API 35 / Production 20 / Thinking 15. 85+ = strong. Integrity check caps hardcoded/non-varying output at 50. (Full briefs: `D:\PP\Purplle...Round 2...pdf` and `D:\PP\Assessment Evaluation Framework...pdf`.)

## Real dataset facts (differs from the idealized brief — documented as assumptions)
- **One store** `ST1008` = "Brigade_Bangalore", Bangalore. Open 10:00–22:00 IST.
- **5 camera clips** `CAM 1..5.mp4` (idealized brief said 3). In `data/clips/` (unzipped). CAM 1–3 ≈ 160–190 MB (longer), CAM 4–5 ≈ 73 MB. 1080p assumed; **probe to confirm fps/res** (we hadn't yet).
- **POS:** real Purplle export, date **2026-04-10**, 101 line-items → **24 transactions** (grouped by invoice). Times 12:15–21:40 IST. Baskets ₹149–₹8243.
- **Staff roster:** POS names **5 salespeople** → used as ground-truth staff count for the staff-exclusion heuristic.
- **Layout:** shipped as an Excel floor-plan *image* (not JSON). We reconstructed `data/store_layout.json` ourselves. Store = long rectangle: entrance bottom-left, brand bays top+bottom walls, F.O.H (makeup/nail) centre, **CASH COUNTER (billing) right side**. Image saved at `data/store_layout.png`.
- **No** `sample_events.jsonl` or `assertions.py` were provided → we define the schema (from the brief) and write our own tests.

## Key architecture decisions (defend these in the follow-up video)
1. **Storage:** PostgreSQL in Docker; SQLite fallback for local/tests (via `DATABASE_URL`). Lets us demo "DB down → 503".
2. **Single-camera identity:** robust multi-camera Re-ID is out of scope for 48h. One **primary wide-coverage camera** carries visitor identity (entry line + all zone polygons drawn on it) → one coherent `visitor_id` space → counts/funnel/conversion all consistent. Other cameras = optional heatmap enrichment. **TODO tomorrow:** confirm which physical camera has the widest coverage (see calibration step) and set it as primary in `store_layout.json`.
3. **Feed clock:** all relative-time logic (today's window, dead-zone, staleness) uses the **latest event time**, not wall-clock — so recorded footage (April) behaves like a live feed.
4. **Conversion:** a visitor present in BILLING within 5 min before a POS txn (same store) = converted. No customer_id in POS → time+store correlation. `conversion_rate = converted entrants / unique entrants`.
5. **Group/Re-entry/Staff:** ByteTrack gives 1 id per person (group of 3 → 3 ENTRYs). Re-entry reuses the id → `REENTRY` event, not a 2nd ENTRY (no double count). Staff flagged `is_staff` and excluded from all customer metrics.
6. **Edge cases:** low-confidence events are kept (flagged), never dropped.

## What's DONE (files that exist and work)
```
store-intelligence/
├── app/                      # FastAPI — Part B (VALIDATED end-to-end on SQLite)
│   ├── main.py               # routes + lifespan(init_db, load POS, auto-ingest events.jsonl) + 503/500 handlers
│   ├── config.py db.py tables.py models.py
│   ├── analytics.py          # sessions, conversion, feed-clock, visitor gating (entered)
│   ├── metrics.py funnel.py anomalies.py health.py
│   ├── ingestion.py          # idempotent, batched, partial-success
│   ├── pos.py store.py logging_mw.py
│   └── Dockerfile            # API image — BUILDS OK
├── pipeline/                 # Detection — Part A (code complete; pure parts smoke-tested)
│   ├── geometry.py zones.py  # pure: point-in-poly, line crossing, zone resolve
│   ├── sessionizer.py        # pure FSM: emits ENTRY/EXIT/ZONE_*/BILLING_*/REENTRY  ✅ smoke-tested
│   ├── staff.py              # heuristic + optional Claude Vision VLM (prompt in file)
│   ├── detect.py             # YOLOv8+ByteTrack driver (needs torch/cv2/GPU) — has --max-frames, --device cpu
│   ├── calibrate.py          # dumps frames with zones overlaid for tuning
│   ├── Dockerfile.gpu run.sh requirements-pipeline.txt
├── scripts/
│   ├── prepare_data.py       # POS CSV → data/pos_transactions.csv + staff_roster.json  ✅ ran
│   └── simulate_events.py    # DEV/TEST event generator (NOT detection) → data/events.jsonl  ✅
├── data/
│   ├── store_layout.json     # OUR reconstruction (zones placeholder polygons — NEED CALIBRATION)
│   ├── pos_transactions.csv  # 24 txns (generated)
│   ├── staff_roster.json     # 5 staff (generated)
│   ├── events.jsonl          # 651 simulated events (for API validation/dashboard)
│   ├── store_layout.png      # the floor-plan image
│   ├── clips/CAM 1..5.mp4    # real footage (unzipped; gitignored)
│   └── raw/pos_raw.csv        # original POS export
├── docker-compose.yml        # db(postgres) + api + pipeline(gpu, profile)
├── requirements.txt pytest.ini .gitignore .dockerignore
└── tests/helpers.py          # (test suite itself deferred per scope)
```

### Verified working (this machine, SQLite, no GPU)
- API end-to-end: `/metrics` → 49 unique visitors, **conversion 0.49**, 24/24 POS attributed, abandonment 0.14; `/funnel` 49→45→28→24; `/heatmap` normalized + confidence; `/anomalies` queue spike + dead zones; `/health` per-camera staleness. Staff (185 events) correctly excluded. Structured JSON logs with trace_id/latency.
- Sessionizer FSM: emits the full event vocabulary with unique ids; ENTRY→…→EXIT→REENTRY verified.
- `docker compose build api` → exit 0.

## RESUME POINT — do this tomorrow (Phase 1 finish)
1. **Verify/finish CV install** (was downloading when we stopped):
   ```powershell
   cd D:\PP\store-intelligence
   .\.venv\Scripts\python.exe -c "import torch,cv2,ultralytics;print('CV READY')"
   # if not ready:
   .\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
   .\.venv\Scripts\python.exe -m pip install ultralytics opencv-python-headless
   ```
2. **Probe clips** (fps/res/duration) and **extract one raw frame per camera** to SEE which camera shows entrance vs floor vs billing. Then pick the **primary** camera.
3. **Calibrate zones:** `python pipeline/calibrate.py --frame 900` → open `data/calib/*.png`, edit polygons + `entry_line` in `data/store_layout.json` until they line up. Put **all** zones (incl. BILLING + entry line) on the chosen **primary** camera.
4. **Bounded CPU detection smoke run** (prove real events on real footage):
   ```powershell
   python pipeline/detect.py --primary CAM_1 --device cpu --frame-stride 15 --max-frames 200 --out data/events_real.jsonl
   ```
   Inspect `data/events_real.jsonl` (ENTRY count sane vs eyeballing the clip; ids unique; schema valid).
5. (Tomorrow/After) On the **friend's GPU machine**: `docker compose --profile pipeline run --rm pipeline` for the full-quality run, then `docker compose up`.

## Deferred (after Phase 1, per user scope) — Tasks #5,#6,#7,#8
- **#5 Tests** >70% coverage + edge cases (empty store, all-staff, zero purchases, re-entry, idempotency) + AI prompt-block headers. `tests/helpers.py` already exists.
- **#6 Docs**: `DESIGN.md` (+ "AI-Assisted Decisions"), `CHOICES.md` (model/schema/API), `README.md` (5-command setup).
- **#7 Dashboard** (Part E bonus): live metric via polling `/metrics`.
- **#8 GPU run + final `docker compose up` verification + submit** (private git repo + invite reviewer).

## Environment notes
- Python 3.13 at `.venv` (Windows). Docker 29 + Compose v5 present. **No NVIDIA GPU on this machine** → detection validated on CPU here; full run on friend's GPU.
- Run API locally without Docker:
  ```powershell
  cd D:\PP\store-intelligence
  .\.venv\Scripts\python.exe scripts\simulate_events.py --seed 7
  .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload   # http://127.0.0.1:8000/docs
  ```
- Run via Docker: `docker compose up` → API at http://localhost:8000 (Postgres-backed).

## Open questions to confirm with user
- Which camera is the primary identity source (decide after seeing frames).
- Clip base timestamp alignment to the POS window (currently `CLIP_BASE_TS=2026-04-10T15:30:00+05:30`) so billing presence overlaps real transactions.
