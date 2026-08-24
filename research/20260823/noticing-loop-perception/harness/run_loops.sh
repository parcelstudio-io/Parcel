#!/usr/bin/env bash
# H6 — every noticing-loop run, in one reproducible sequence.
#   usage: run_loops.sh <corpus-dir> <out-dir> [suffix]
# The daemon must already be listening on $H6_SOCKET (started by the executor,
# never the owner's). Nothing here touches git, the owner's stack, or :8765.
set -euo pipefail

CORPUS="$1"
OUT="$2"
SUFFIX="${3:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
PY="$ROOT/.parcel/bin/python"
H6="$ROOT/research/20260823/noticing-loop-perception"
SOCKET="${H6_SOCKET:-$H6/h6_perception.sock}"
CLIPS="$CORPUS/clips"
GT="$CLIPS/clips_gt.json"
PHOTO_LABELS="person,chair,car,bicycle,dog,bench,cup,backpack,umbrella,traffic light"
RENDER_LABELS="person,bench,tree,building,lamppost,planter,door"
DUR="${H6_DURATION_S:-60}"

mkdir -p "$OUT"

loop() {  # loop <name> <clip> <labels> <extra args...>
  local name="$1" clip="$2" labels="$3"; shift 3
  echo "=== $name$SUFFIX ==="
  env -u TMPDIR "$PY" "$H6/harness/noticing_loop.py" \
    --clip "$CLIPS/$clip" --clip-name "$clip" --gt "$GT" --socket "$SOCKET" \
    --labels "$labels" --duration-s "$DUR" --run-name "$name$SUFFIX" \
    --out "$OUT/$name$SUFFIX.json" "$@" | tail -n 14
}

loop photos_free   photos_640.npz  "$PHOTO_LABELS"  --hz 0
loop renders_free  renders_640.npz "$RENDER_LABELS" --hz 0
loop photos_10hz   photos_640.npz  "$PHOTO_LABELS"  --hz 10
loop photos_15hz   photos_640.npz  "$PHOTO_LABELS"  --hz 15
loop photos_20hz   photos_640.npz  "$PHOTO_LABELS"  --hz 20
loop renders_10hz  renders_640.npz "$RENDER_LABELS" --hz 10
loop photos_10hz_contended photos_640.npz "$PHOTO_LABELS" --hz 10 \
     --contend-url "${H6_REASONER_URL:-http://127.0.0.1:8081/v1/completions}" --contend-tokens 256
H6_DURATION_S=20 DUR=20 loop photos_free_puregallery photos_640.npz "$PHOTO_LABELS" \
     --hz 0 --pure-gallery
echo "all loop runs written to $OUT"
