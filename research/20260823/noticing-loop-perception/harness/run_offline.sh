#!/usr/bin/env bash
# H6 — the rows that do not need the loop running: the ingress freshness
# before/after, the RGB-only null result, and the threshold sweeps.
#   usage: run_offline.sh <corpus-dir> <out-dir>
# The cuda_fp16 sweeps load their OWN detector session, so this script stops
# the H6 daemon around them (VRAM on this box is shared with two llama.cpp
# servers and H2's daemon) and starts it again afterwards. It never touches any
# process it did not start.
set -euo pipefail

CORPUS="$1"
OUT="$2"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
PY="$ROOT/.parcel/bin/python"
H6="$ROOT/research/20260823/noticing-loop-perception"
SOCKET="${H6_SOCKET:-$H6/h6_perception.sock}"
CLIPS="$CORPUS/clips"
LOGS="${H6_LOGS:-$OUT/logs}"
mkdir -p "$OUT" "$LOGS"

ingress() {  # ingress <name> <clip> <detector> <labels> <frames>
  echo "=== ingress $1 ==="
  env -u TMPDIR "$PY" "$H6/harness/ingress_freshness.py" \
    --clip "$CLIPS/$2" --detector "$3" --socket "$SOCKET" --labels "$4" \
    --frames "$5" --run-name "$1" --out "$OUT/ingress_$1.json" | tail -n 24
}

sweep() {  # sweep <which> <provider> [verify]
  echo "=== sweep $1 $2 ==="
  env -u TMPDIR "$PY" "$H6/harness/threshold_sweep.py" \
    --corpus "$CORPUS" --which "$1" --provider "$2" \
    --verify-threshold "${3:-0}" --out "$OUT/sweep_$1_$2.json" | tail -n 22
}

start_daemon() {
  env -u TMPDIR PARCEL_PERCEPTION_PROVIDER=cuda_fp16 PARCEL_OWLV2_ONNX=1 \
    PARCEL_SIGLIP2_ONNX=1 nohup "$PY" -m parcel_robot.perception_daemon \
    --socket "$SOCKET" --preload --log-level INFO >> "$LOGS/daemon.log" 2>&1 &
  for _ in $(seq 1 60); do
    if "$PY" -m parcel_robot.perception_daemon --socket "$SOCKET" --probe >/dev/null 2>&1; then
      echo "daemon up"; return 0
    fi
    sleep 2
  done
  echo "daemon did NOT come back up" >&2; return 1
}

# --- rows that use the daemon (or no GPU at all) ---------------------------
ingress before_cpu_int8_1280 renders_1280.npz cpu_int8 render 16
ingress after_daemon_640     renders_640.npz  daemon   render 32
ingress rgb_only_photos_640  photos_640.npz   daemon   photo  32

# --- CPU-side sweeps (the incumbent operating point) -----------------------
sweep photos_native cpu_int8
sweep renders_1280  cpu_int8

# --- GPU sweeps: the daemon steps aside for its own VRAM -------------------
"$PY" -m parcel_robot.perception_daemon --socket "$SOCKET" --shutdown || true
sleep 5
sweep photos_native cuda_fp16 0.10
sweep photos_640    cuda_fp16
sweep renders_1280  cuda_fp16 0.10
sweep renders_640   cuda_fp16
start_daemon
echo "offline rows written to $OUT"
