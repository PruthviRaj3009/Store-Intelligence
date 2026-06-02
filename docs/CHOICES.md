# CHOICES.md — key decisions, trade-offs, and what AI suggested

Three decisions, each as: **options considered → what AI suggested → what we chose & why**.
Plus the data-reconciliation choices forced by the real (vs idealized) dataset.

---

## Decision 1 — Detection model & tracker

**Options considered**
- YOLOv8 (n/s/m) for person detection — mature, one-line `model.track()` with ByteTrack.
- RT-DETR — stronger on occlusion, heavier, fiddlier to deploy.
- MediaPipe — light but weak on small/occluded people in wide CCTV shots.
- Trackers: ByteTrack vs DeepSORT/StrongSORT (appearance Re-ID).

**What AI suggested**
The model recommended YOLOv8 + ByteTrack as the pragmatic default, and floated RT-DETR +
StrongSORT "if accuracy matters more than speed."

**What we chose & why**
**YOLOv8n + ByteTrack.** Reasons grounded in *this* task: (1) the brief explicitly scores
engineering judgment over model accuracy and says detection need not be perfect; (2) ByteTrack
keeps low-confidence boxes in the association step, which matters for the partial-occlusion
edge case; (3) one id per person makes the **group-of-3 = 3 ENTRYs** requirement free; (4) it
runs on CPU for development and GPU for the real run with a single flag. We start at `n`
(nano) and can swap to `s`/`m` by changing one argument if recall is poor — no code change.
**When we'd switch:** if validation shows ByteTrack id-fragmentation inflating re-entry counts
(we saw some on short CPU clips), we'd add appearance Re-ID (StrongSORT/OSNet).

**VLM use.** `staff.py` includes an optional **Claude Vision** classifier for borderline
staff crops; the prompt is in the file and quoted in DESIGN. We made it *optional* (heuristic
is the default) because a per-crop network call is too slow/expensive to run on every track,
and the dwell-time heuristic + the POS staff roster (we know exactly 5 staff work the floor)
already separates staff well. The VLM is there for the ambiguous tail.

---

## Decision 2 — Event schema design

**Options considered**
- A thin schema (just type + timestamp + visitor) vs a **rich, self-describing** event.
- Where to put queue depth / zone label / sequence — top-level columns vs a `metadata` blob.
- Whether to emit **low-confidence** events at all.

**What AI suggested**
A flat schema with everything top-level "for easy SQL." 

**What we chose & why**
We kept the brief's schema and made three deliberate calls:
1. **`metadata` as a nested object** (`queue_depth`, `sku_zone`, `session_seq`) — these are
   event-type-specific and mostly null; nesting keeps the core columns clean while staying
   queryable. We flatten them into indexed columns at ingest (`tables.py`) to get SQL speed
   *and* a tidy contract — best of both, overriding the "everything flat" suggestion.
2. **`confidence` is mandatory and low-confidence events are emitted, never suppressed.**
   The brief penalizes silent dropping; downstream consumers decide how to weigh confidence.
3. **`event_id` is the idempotency key.** Globally unique (uuid4) so `POST /events/ingest`
   is safe to retry — the API upserts on it.

The schema is the **contract between the two halves** of the system. Designing it first let
us build and test the entire API against synthetic events before the GPU pipeline existed.

---

## Decision 3 — API architecture: single primary identity camera

This is the decision we most own. The store has **5 cameras** (entrance, two floor, billing,
backroom) with overlapping views — the brief warns about cross-camera double counting.

**Options considered**
- (a) Full multi-camera **Re-ID** — embed every person, stitch ids across cameras.
- (b) Count per-camera and **deduplicate** by appearance + time.
- (c) **One primary, wide-coverage camera owns visitor identity**; others enrich.

**What AI suggested**
Option (a) — OSNet embeddings + a global identity graph.

**What we chose & why — (c).** Robust multi-camera Re-ID is a research-grade problem; in a
48-hour build it is high-risk and very hard to *validate* (you can't tell a stitching bug from
a detection bug). So we designate one **primary camera** as the source of `visitor_id` and draw
the entry line + all zone polygons on it, so the whole funnel lives in **one coherent id
space** — entry counts, dwell, billing approach and conversion stay mutually consistent, and
overlapping cameras can't double-count because only the primary mints identities. The billing
camera contributes queue depth; the others are reserved for heatmap enrichment.

**Trade-off / failure mode (stated honestly):** a visitor seen *only* by a side camera and
never by the primary is missed. **What would change our mind:** labelled multi-camera data and
more time → add OSNet Re-ID + a homography that projects all cameras onto one floor plan, then
identity is a floor-plan track, not a per-camera one.

**Storage: PostgreSQL** (SQLite fallback for local/tests). Postgres lets us honestly
demonstrate the "DB down → 503" production requirement and matches a real deployment; SQLite
keeps tests infra-free.

---

## Data reconciliation (real dataset ≠ idealized brief)
The shipped data differed from the brief, and handling that is part of the work:
- **Layout came as an Excel floor-plan image**, not JSON → we reconstructed
  `data/store_layout.json` and **verified camera roles by inspecting a frame from each clip**
  (CAM 3 = entrance, CAM 5 = billing, CAM 1/2 = floor, CAM 4 = backroom).
- **POS was a 39-column line-item export** → `scripts/prepare_data.py` collapses it to one row
  per invoice (24 transactions) and converts IST → UTC. The same script derives the **staff
  roster** from the 5 distinct salespeople, which calibrates the staff heuristic.
- **No `sample_events.jsonl` / `assertions.py`** → we define the schema from the brief and
  write our own test suite.
- Clips are **~2–2.5 min** (not 20), 1080p, 25–30 fps — noted so entry-count expectations are
  realistic.
