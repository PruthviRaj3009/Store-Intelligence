#!/usr/bin/env bash
# One command: process the footage into data/events.jsonl.
# Usage: pipeline/run.sh [DEVICE] [PRIMARY_CAM]
set -euo pipefail

DEVICE="${1:-cuda}"
PRIMARY="${2:-CAM_1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 1) normalize POS + roster (idempotent)
python scripts/prepare_data.py

# 2) unzip clips if needed
if [ ! -d data/clips ] || [ -z "$(ls -A data/clips 2>/dev/null || true)" ]; then
  echo "Place the CCTV clips (CAM 1.mp4 ...) in data/clips/ before running detection."
fi

# 3) run detection on the primary identity camera
python pipeline/detect.py --primary "$PRIMARY" --device "$DEVICE" --out data/events.jsonl

echo "Done -> data/events.jsonl. Start the API with: docker compose up"
