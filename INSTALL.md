# INSTALL — Run Store Intelligence on another machine (from the zip)

This guide takes a fresh machine from **nothing installed** to a **running system**
(API + database + live dashboard), then optionally the **GPU detection pipeline**.

There are two paths:

- **Path 1 — Docker (recommended).** One command. No Python setup. Works on any
  Windows / macOS / Linux machine with Docker installed.
- **Path 2 — Native Python.** No Docker. Good for a quick look or a CPU-only dev box.

> **Fastest demo:** the zip already contains a prepared `data/events.jsonl`, so the API
> and dashboard show real numbers on a cold start — **you do NOT need the video clips or a
> GPU just to see the system working.** Clips + GPU are only needed to *regenerate* events
> from the raw footage (Path 3 at the bottom).

---

## 0. What's in the zip (and what's not)

Included: all source code (`app/`, `pipeline/`, `scripts/`, `dashboard/`, `tests/`),
config (`docker-compose.yml`, `requirements.txt`, Dockerfiles), and prepared data
(`data/events.jsonl`, `data/store_layout.json`, `data/pos_transactions.csv`,
`data/staff_roster.json`, `data/store_layout.png`).

**Deliberately excluded** to keep the zip small and portable:
- `.venv/` — a Windows-specific virtual env (gigabytes). It is rebuilt on the new machine.
- `data/clips/*.mp4` — the 5 raw CCTV videos (~680 MB total). Only needed for Path 3.
- `data/store.db` — local SQLite cache; regenerated automatically.

If the recipient needs to run detection on the real footage, send the **5 clips separately**
(they're large) and drop them into `data/clips/` as `CAM 1.mp4` … `CAM 5.mp4`.

---

## Path 1 — Docker (recommended)

### 1.1 Install Docker
- **Windows / macOS:** install **Docker Desktop** → https://www.docker.com/products/docker-desktop
  Launch it once and wait until it says "Engine running".
- **Linux:** install Docker Engine + the Compose plugin.

Verify:
```bash
docker --version
docker compose version
```

### 1.2 Unzip
Unzip anywhere, then open a terminal **inside** the unzipped folder:
```bash
cd store-intelligence
```
(You should see `docker-compose.yml` in this folder — that confirms you're in the right place.)

### 1.3 Bring it up — one command
```bash
docker compose up -d --build
```
This builds the API image, starts **PostgreSQL + the API**, and auto-ingests
`data/events.jsonl` on startup. First build takes a few minutes (downloads the base image
and Python deps); later starts are instant.

### 1.4 Verify it works
```bash
curl http://localhost:8000/health
curl http://localhost:8000/stores/ST1008/metrics
```
Then open in a browser:
- **Dashboard:** http://localhost:8000/dashboard
- **API docs (Swagger):** http://localhost:8000/docs

Optional live demo — replays events so the dashboard fills in real time:
```bash
docker compose exec api python scripts/replay_events.py --speed 120
```

### 1.5 Stop / restart
```bash
docker compose down        # stop (keeps the DB volume)
docker compose down -v     # stop AND wipe the database volume
docker compose up -d       # start again (no rebuild needed)
```

---

## Path 2 — Native Python (no Docker)

Use this for a quick look without Docker. Runs the API on **SQLite** (no Postgres needed).

### 2.1 Install Python 3.12+
- Get it from https://www.python.org/downloads/ (on Windows, tick **"Add Python to PATH"**).
- Verify: `python --version`

### 2.2 Create a virtual environment & install deps

**Windows (PowerShell):**
```powershell
cd store-intelligence
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**macOS / Linux:**
```bash
cd store-intelligence
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> If PowerShell blocks activation with a script-execution error, run once:
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

### 2.3 Run the API
```bash
uvicorn app.main:app --reload
```
Then open:
- Dashboard: http://localhost:8000/dashboard
- API docs:  http://localhost:8000/docs

The app creates a local `data/store.db` (SQLite) and auto-ingests `data/events.jsonl`.

### 2.4 Run the tests (proof of quality)
```bash
pytest --cov=app --cov=pipeline
# expect: 28 passing, ~93% coverage
```

---

## Path 3 — Regenerate events from the real clips (optional, GPU)

Only needed to rebuild `data/events.jsonl` from the raw footage. Requires the **5 clips**
in `data/clips/` and (ideally) an **NVIDIA GPU**.

### 3.1 Put the clips in place
Copy the videos into `data/clips/` named exactly:
```
data/clips/CAM 1.mp4
data/clips/CAM 2.mp4
data/clips/CAM 3.mp4
data/clips/CAM 4.mp4
data/clips/CAM 5.mp4
```

### 3.2a With Docker + NVIDIA GPU (recommended for full quality)
Requires the **NVIDIA Container Toolkit** on the host. Confirm Docker sees the GPU:
```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-runtime-ubuntu22.04 nvidia-smi
```
Run detection, then have the API re-ingest:
```bash
docker compose --profile pipeline run --rm pipeline   # → writes data/events.jsonl
docker compose restart api
```

### 3.2b Without a GPU (CPU, slower — for a smoke test)
```bash
pip install -r pipeline/requirements-pipeline.txt
python scripts/prepare_data.py                                   # normalize POS + staff roster
python -m pipeline.detect --primary CAM_2 --device cpu --out data/events.jsonl
```

### 3.3 Calibrate zones (one-time per camera set)
Overlay the configured polygons on a real frame and adjust `data/store_layout.json`
until they line up with the shelves / aisle / billing:
```bash
python -m pipeline.calibrate --frame 900        # writes data/calib/*.png
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker: command not found` | Docker isn't installed / Desktop not running. See 1.1. |
| Port 8000 already in use | Stop the other process, or change the API port mapping in `docker-compose.yml` (`"8001:8000"`) and use `:8001`. |
| Port 5433 already in use | Another Postgres is running; change the `db` port mapping in `docker-compose.yml`. |
| Build is very slow the first time | Normal — it downloads base images + Python wheels once, then caches. |
| `Activate.ps1 cannot be loaded` (Windows) | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again. |
| Dashboard loads but is empty | Make sure `data/events.jsonl` exists; restart: `docker compose restart api`. |
| GPU run fails / `nvidia-smi` not found in container | Install the NVIDIA Container Toolkit, or use the CPU path (3.2b). |

---

## TL;DR

```bash
# unzip, then:
cd store-intelligence
docker compose up -d --build
# open http://localhost:8000/dashboard
```
That's the whole system running on a cold machine. Everything else above is optional depth.
