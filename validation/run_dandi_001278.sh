#!/bin/bash
# Run the DANDI 001278 post-processing check (validation/dandi_001278_postprocess.py) on a GPU
# node. Usage: validation/run_dandi_001278.sh OUTPUT_DIR   (e.g. a directory on scratch)
set -euo pipefail
OUT=${1:?usage: $0 OUTPUT_DIR}
REPO=$(cd "$(dirname "$0")/.." && pwd)
salloc -p mit_normal_gpu -A mit_general --gres=gpu:1 -c 8 --mem=32G -t 00:30:00 \
  -J ozm-dandi-check \
  srun --chdir="$REPO" uv run --no-sync python validation/dandi_001278_postprocess.py "$OUT"
