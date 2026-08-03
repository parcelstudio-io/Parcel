#!/usr/bin/env bash
# Serve the official Gemma 4 QAT GGUF with the installed llama.cpp CPU build.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_DIR="${PARCEL_LLAMA_CPP_DIR:-$ROOT/third_party/llama.cpp-bin/llama-b10235}"
LLAMA_SERVER="${PARCEL_LLAMA_SERVER:-$LLAMA_DIR/llama-server}"
MODEL="${PARCEL_REASONER_MODEL_PATH:-$ROOT/models/gemma-4-26b-a4b/gemma-4-26B_q4_0-it.gguf}"
HOST="${PARCEL_REASONER_HOST:-127.0.0.1}"
PORT="${PARCEL_REASONER_PORT:-8080}"
THREADS="${PARCEL_REASONER_THREADS:-48}"
BATCH_THREADS="${PARCEL_REASONER_BATCH_THREADS:-96}"
CTX_SIZE="${PARCEL_REASONER_CTX_SIZE:-8192}"
ALIAS="${PARCEL_REASONER_MODEL_ALIAS:-gemma-4-26b-a4b}"

usage() {
  cat <<'EOF'
Usage: scripts/launch_reasoner.sh [additional llama-server arguments]

Serves Gemma 4 26B-A4B QAT Q4 on CPU at http://127.0.0.1:8080 by default.
The CPU profile deliberately leaves the NVIDIA GPU free for simulation/Fish TTS.

Environment overrides:
  PARCEL_LLAMA_CPP_DIR, PARCEL_LLAMA_SERVER, PARCEL_REASONER_MODEL_PATH
  PARCEL_REASONER_HOST, PARCEL_REASONER_PORT, PARCEL_REASONER_THREADS
  PARCEL_REASONER_BATCH_THREADS, PARCEL_REASONER_CTX_SIZE
  PARCEL_REASONER_MODEL_ALIAS

Arguments after -- are passed to llama-server after the profile defaults.
EOF
}

die() {
  echo "launch_reasoner: $*" >&2
  exit 1
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi
[[ ${1:-} == "--" ]] && shift

[[ -x "$LLAMA_SERVER" ]] || die \
  "llama-server not found or not executable: $LLAMA_SERVER (install the official llama.cpp release under third_party/llama.cpp-bin)"
[[ -s "$MODEL" ]] || die \
  "Gemma GGUF not found: $MODEL (download google/gemma-4-26B-A4B-it-qat-q4_0-gguf)"
[[ -n "$HOST" ]] || die "PARCEL_REASONER_HOST must not be empty"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "PARCEL_REASONER_PORT must be an integer"
(( PORT >= 1 && PORT <= 65535 )) || die "PARCEL_REASONER_PORT must be between 1 and 65535"
for setting in "$THREADS" "$BATCH_THREADS" "$CTX_SIZE"; do
  [[ "$setting" =~ ^[1-9][0-9]*$ ]] || die "thread counts and context size must be positive integers"
done

python3 - "$MODEL" <<'PY' || exit 1
from pathlib import Path
import sys

path = Path(sys.argv[1])
with path.open("rb") as stream:
    magic = stream.read(4)
if magic != b"GGUF":
    raise SystemExit(f"launch_reasoner: invalid GGUF header in {path}")
if path.stat().st_size < 10_000_000_000:
    raise SystemExit(f"launch_reasoner: Gemma model looks incomplete ({path.stat().st_size} bytes): {path}")
PY

export LD_LIBRARY_PATH="$LLAMA_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
echo "Gemma reasoner: http://$HOST:$PORT/v1 (CPU, $THREADS generation threads, context $CTX_SIZE)"
echo "Model: $MODEL"
exec "$LLAMA_SERVER" \
  --model "$MODEL" \
  --alias "$ALIAS" \
  --host "$HOST" \
  --port "$PORT" \
  --ctx-size "$CTX_SIZE" \
  --threads "$THREADS" \
  --threads-batch "$BATCH_THREADS" \
  --n-gpu-layers 0 \
  --jinja \
  --reasoning auto \
  --reasoning-format deepseek \
  "$@"
