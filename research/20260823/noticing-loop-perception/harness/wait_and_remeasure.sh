#!/usr/bin/env bash
# H6 — re-measure the headline loop rows the moment the HOST goes quiet.
#
# The rows that matter (P1/P2/P3) turned out to be CPU-bound at 640x360, and
# this host spent the measurement window at load 100-180 under another
# executor's 48-thread CPU judge server. This waits for a quiet window
# (1-minute load average under $MAX_LOAD, GPU under $MAX_GPU_UTIL) and then
# re-runs the two headline rows alone, tagging them "_quiet".
#   usage: wait_and_remeasure.sh <corpus-dir> <out-dir> [max_wait_s]
set -euo pipefail

CORPUS="$1"
OUT="$2"
MAX_WAIT="${3:-3600}"
MAX_LOAD="${MAX_LOAD:-40}"
MAX_GPU_UTIL="${MAX_GPU_UTIL:-25}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
PY="$ROOT/.parcel/bin/python"
H6="$ROOT/research/20260823/noticing-loop-perception"
SOCKET="${H6_SOCKET:-$H6/h6_perception.sock}"
PHOTO_LABELS="person,chair,car,bicycle,dog,bench,cup,backpack,umbrella,traffic light"
DUR="${H6_DURATION_S:-90}"

waited=0
while (( waited < MAX_WAIT )); do
  load=$(cut -d' ' -f1 /proc/loadavg)
  util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits | head -1)
  if awk -v l="$load" -v m="$MAX_LOAD" 'BEGIN{exit !(l<m)}' && (( util < MAX_GPU_UTIL )); then
    echo "quiet window at load=$load gpu=$util after ${waited}s"
    for row in photos_free photos_10hz; do
      hz=0; [[ "$row" == "photos_10hz" ]] && hz=10
      env -u TMPDIR "$PY" "$H6/harness/noticing_loop.py" \
        --clip "$CORPUS/clips/photos_640.npz" --clip-name photos_640.npz \
        --gt "$CORPUS/clips/clips_gt.json" --socket "$SOCKET" --labels "$PHOTO_LABELS" \
        --hz "$hz" --duration-s "$DUR" --run-name "${row}_quiet" \
        --out "$OUT/${row}_quiet.json" | tail -n 8
    done
    env -u TMPDIR "$PY" "$H6/harness/query_scaling.py" --corpus "$CORPUS" \
      --socket "$SOCKET" --repeats 20 --out "$OUT/query_scaling_quiet.json" | tail -n 4
    env -u TMPDIR "$PY" "$H6/harness/preprocess_bench.py" --corpus "$CORPUS" \
      --repeats 60 --out "$OUT/preprocess_bench_quiet.json" | tail -n 6
    echo "quiet re-measure complete"
    exit 0
  fi
  sleep 30
  waited=$((waited + 30))
done
echo "no quiet window within ${MAX_WAIT}s (last load=$load gpu=$util)" >&2
exit 2
