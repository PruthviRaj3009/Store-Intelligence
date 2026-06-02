# DESIGN.md — Store Intelligence

## 1. The problem in one line
Turn raw in-store CCTV into the same kind of analytics an online store gets for free —
above all, the **offline conversion rate** = paying visitors ÷ unique visitors.

## 2. System architecture
```
 CCTV clips ──► Detection pipeline ──► events.jsonl ──► Intelligence API ──► Dashboard
 (data/clips)   (pipeline/, GPU)       (event stream)   (app/, FastAPI+PG)   (dashboard/)
                                                              ▲
                                              POS transactions (data/pos_transactions.csv)
```

Two deployables, deliberately decoupled:

- **Detection pipeline** (`pipeline/`) — GPU-bound, batch. Reads clips, runs YOLOv8 +
  ByteTrack, and emits behavioural **events** in a fixed schema. The heavy, model-specific
  part is isolated here so the API never depends on CUDA.
- **Intelligence API** (`app/`) — light, always-on. Ingests events into PostgreSQL,
  correlates them with POS, and serves metrics/funnel/heatmap/anomalies/health.

They communicate only through the **event schema** (`app/models.py`). That contract is the
single most important design artifact: it lets the two halves evolve independently and lets
the API be tested with synthetic events, no GPU required.

### Why this split
The challenge explicitly allows pre-processing clips offline and replaying events. We lean
into that: `docker compose up` brings up the **API + DB instantly** (so the acceptance gate
and dashboard work immediately), while detection runs as a **separate GPU-profiled service**
(`docker compose --profile pipeline run pipeline`). A reviewer with no GPU still sees a fully
working system because the API auto-ingests a prepared `events.jsonl` on startup.

## 3. Detection pipeline (Part A)
Pipeline stages, each a small module so the **pure logic is unit-tested without a GPU**:

| Module | Responsibility |
|---|---|
| `detect.py` | YOLOv8n + ByteTrack over frames → per-person `Observation`s (the only GPU/IO code) |
| `geometry.py` | point-in-polygon, doorway line-crossing (pure) |
| `zones.py` | map a foot point to a store zone; map a movement to enter/exit (pure) |
| `sessionizer.py` | a per-visitor **FSM** that turns observations into the event stream (pure) |
| `staff.py` | staff vs customer: dwell-time heuristic + optional Claude Vision (pure-ish) |

**Person → foot point → zone.** We anchor a person to the **bottom-centre of their bbox**
(their floor contact), not the centroid, because that is what actually determines which zone
they stand in.

**Entry/exit** come from a calibrated **doorway line** on the entrance camera; crossing it
inbound = `ENTRY`, outbound = `EXIT`. We **debounce** crossings (a few seconds) because a
person loitering on the threshold makes their foot oscillate across the line — on the real
footage this produced a storm of false ENTRY/EXIT until we added the debounce.

**Edge cases handled:** group entry (ByteTrack = one id per person → 3 people, 3 ENTRYs),
re-entry (same id after an EXIT → `REENTRY`, never a 2nd ENTRY → no double count), staff
(flagged and excluded), partial occlusion (low-confidence events are **kept and flagged**,
never dropped), empty periods (API returns zeros, not nulls), camera overlap (a single
primary identity camera — see CHOICES.md — avoids cross-camera double counting).

## 4. Intelligence API (Part B)
- **Ingestion** (`ingestion.py`): batched (≤500), **idempotent by `event_id`**, partial
  success on malformed events.
- **The session is the unit of analysis** (`analytics.py`): events are collapsed into one
  `VisitorSession` per `visitor_id`. Re-entries reuse the id, so grouping by id makes
  "re-entries must not double-count" automatic. Staff sessions are excluded everywhere.
- **Conversion** = a visitor present in BILLING within 5 min before a POS transaction
  (same store). No `customer_id` exists in POS, so correlation is time + store.
- **Feed clock:** every relative-time decision (today's window, dead-zone, staleness) is
  measured against the **latest event time**, not the server wall clock, so recorded April
  footage behaves like a live feed.

## 5. Production readiness (Part C)
- `docker compose up` → Postgres + API, no manual steps.
- **Structured JSON logs**, one line/request: trace_id, store_id, endpoint, latency_ms,
  event_count, status_code. The trace_id is returned in `X-Trace-Id`.
- **Graceful degradation:** DB down → structured **HTTP 503**, never a stack trace.
- **Tests:** 28 tests, **93% statement coverage** of the unit-testable core (the two
  video-IO entrypoints are validated by running on the real clips, not unit tests).

## 6. AI-Assisted Decisions
We used LLMs throughout and treated their output as a draft to critique, not gospel. Three
places they shaped the design:

1. **Session-based funnel (agreed).** When we described the re-entry double-counting risk,
   the model proposed making `visitor_id` the grouping key and deriving stages from
   per-visitor session state. We agreed — it is the cleanest way to satisfy "no double
   counting" and it fell out naturally into `build_sessions()`.

2. **Cross-camera identity (overrode).** The model's first suggestion was full multi-camera
   Re-ID (OSNet embeddings + a global ID graph). We **overrode** it: in a 48-hour budget that
   is high-risk and hard to validate. We chose a **single primary identity camera** instead,
   and documented the trade-off and its failure mode (see CHOICES.md). This is the decision we
   most consciously took ownership of.

3. **Conversion-window length (partially overrode).** The model suggested attributing a sale
   to the *nearest* prior billing visitor. We kept the time-window idea but made it a fixed,
   configurable 5-minute window (matching the brief) rather than nearest-neighbour, because
   nearest-neighbour silently mis-attributes when the queue is busy. The window bounds the
   error and is explainable.

See `CHOICES.md` for the three deep-dive decisions (model, schema, API).
