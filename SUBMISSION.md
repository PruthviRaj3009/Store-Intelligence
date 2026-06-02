# SUBMISSION — final steps (Task #8)

Everything except this is done and verified. These steps run on **your friend's NVIDIA-GPU
machine** (and need your GitHub account). Budget ~1–2 hours.

## A. Get the repo onto the GPU machine
```bash
git clone <your-private-repo>   # or copy the store-intelligence/ folder over
cd store-intelligence
# put the 5 clips in data/clips/  (CAM 1.mp4 … CAM 5.mp4)
```
Confirm Docker sees the GPU:
```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-runtime-ubuntu22.04 nvidia-smi
```

## B. Calibrate the floor camera (one-time, ~30 min)
The entrance camera (CAM_3) is already calibrated. Tune the primary floor camera (CAM_2):
```bash
python -m pipeline.calibrate --frame 900      # writes data/calib/CAM_2_frame900.png
```
Open the image, adjust the `CAM_2` polygons + `entry_line` in `data/store_layout.json` until
the zones line up with the shelves/aisle, re-run calibrate to confirm. (Optionally repeat the
crossing-sweep trick from RESUME.md to place the entry line by data.)

## C. Run the full detection (GPU)
```bash
docker compose --profile pipeline run --rm pipeline   # → data/events.jsonl
# or natively:
python -m pipeline.detect --primary CAM_2 --device cuda --out data/events.jsonl
```
Sanity-check the output:
```bash
python - <<'PY'
import json,collections
e=[json.loads(l) for l in open("data/events.jsonl")]
print(len(e),"events",collections.Counter(x["event_type"] for x in e))
PY
```
Tune `CLIP_BASE_TS` (env) so billing events overlap the POS times if you want non-zero
conversion on the real run.

## D. Bring up the system & verify the gate
```bash
docker compose up -d --build
curl localhost:8000/health
curl localhost:8000/stores/ST1008/metrics      # must return valid JSON
open http://localhost:8000/dashboard
# live demo:
python scripts/replay_events.py --speed 120     # watch the dashboard fill
```

## E. Tests (proof of quality)
```bash
pip install -r requirements.txt
pytest --cov=app --cov=pipeline                 # 28 tests, ~93%
```

## F. Submit
1. Create a **private** git repo, push everything.
2. Invite the reviewer handle (from your challenge email) as a collaborator.
3. Confirm `docker compose up` works from a fresh `git clone` on the GPU machine.
4. Send the repo link.

## Acceptance-gate checklist (all already proven on this dev machine)
- [x] `docker compose up` starts the API, no manual steps
- [x] `/metrics` returns valid JSON
- [x] detection pipeline produces structured events (`data/events.jsonl`)
- [x] `DESIGN.md` + `CHOICES.md` present and non-trivial (>250 words each)
- [x] DB-down → structured 503, no stack trace
- [ ] (do on GPU machine) full-quality `events.jsonl` from the real clips
- [ ] (you) private repo + reviewer invited
