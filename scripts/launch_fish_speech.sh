#!/usr/bin/env bash
# Serve Fish Audio S2 Pro from its isolated Python environment.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FISH_ROOT="${PARCEL_FISH_ROOT:-$ROOT/third_party/fish-speech}"
PYTHON="${PARCEL_FISH_PYTHON:-$FISH_ROOT/.venv/bin/python}"
CHECKPOINT="${PARCEL_FISH_CHECKPOINT:-$FISH_ROOT/checkpoints/s2-pro}"
DEVICE="${PARCEL_FISH_DEVICE:-cuda}"
HOST="${PARCEL_FISH_HOST:-127.0.0.1}"
PORT="${PARCEL_FISH_PORT:-8091}"

usage() {
  cat <<'EOF'
Usage: scripts/launch_fish_speech.sh [additional Fish api_server.py arguments]

Serves Fish Audio S2 Pro at http://127.0.0.1:8091/v1/tts. The default
profile uses one CUDA fp16 worker. S2 Pro is opt-in because it needs a large
GPU allocation and its model license is not a general commercial license.

Environment overrides:
  PARCEL_FISH_ROOT, PARCEL_FISH_PYTHON, PARCEL_FISH_CHECKPOINT
  PARCEL_FISH_DEVICE, PARCEL_FISH_HOST, PARCEL_FISH_PORT
  PARCEL_FISH_API_KEY       Optional bearer token
  PARCEL_FISH_HALF=0        Disable fp16
  PARCEL_FISH_COMPILE=1     Enable torch.compile
  PARCEL_ALLOW_LOW_VRAM=1   Bypass the 24 GiB CUDA memory preflight
EOF
}

die() {
  echo "launch_fish_speech: $*" >&2
  exit 1
}

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi
[[ ${1:-} == "--" ]] && shift

[[ -d "$FISH_ROOT" ]] || die \
  "Fish Speech checkout not found: $FISH_ROOT (clone https://github.com/fishaudio/fish-speech)"
[[ -x "$PYTHON" ]] || die \
  "isolated Fish Python is missing: $PYTHON (create the Fish Python 3.12 uv environment before launching)"
[[ -d "$CHECKPOINT" ]] || die "S2 Pro checkpoint directory not found: $CHECKPOINT"
for required in \
  config.json \
  tokenizer.json \
  model.safetensors.index.json \
  model-00001-of-00002.safetensors \
  model-00002-of-00002.safetensors \
  codec.pth; do
  [[ -s "$CHECKPOINT/$required" ]] || die "missing or incomplete S2 Pro file: $CHECKPOINT/$required"
done
[[ -n "$HOST" ]] || die "PARCEL_FISH_HOST must not be empty"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "PARCEL_FISH_PORT must be an integer"
(( PORT >= 1 && PORT <= 65535 )) || die "PARCEL_FISH_PORT must be between 1 and 65535"

"$PYTHON" - "$CHECKPOINT" <<'PY' || exit 1
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
index = json.loads((root / "model.safetensors.index.json").read_text())
shards = {root / name for name in index.get("weight_map", {}).values()}
if not shards:
    raise SystemExit("launch_fish_speech: checkpoint index contains no model shards")
missing = [str(path) for path in shards if not path.is_file() or path.stat().st_size == 0]
if missing:
    raise SystemExit("launch_fish_speech: missing indexed shard(s): " + ", ".join(missing))
expected = int(index.get("metadata", {}).get("total_size", 0))
actual = sum(path.stat().st_size for path in shards)
if expected and actual < expected:
    raise SystemExit(
        f"launch_fish_speech: model download is incomplete ({actual} of at least {expected} bytes)"
    )
PY

if ! "$PYTHON" -c 'import fish_speech, torch, uvicorn' >/dev/null 2>&1; then
  die "Fish dependencies are incomplete in $PYTHON; finish the isolated uv sync/install first"
fi

if [[ "$DEVICE" == cuda* ]]; then
  PARCEL_ALLOW_LOW_VRAM="${PARCEL_ALLOW_LOW_VRAM:-0}" "$PYTHON" - <<'PY' || exit 1
import os
import torch

if not torch.cuda.is_available():
    raise SystemExit("launch_fish_speech: CUDA is unavailable in the Fish environment")
device = torch.cuda.current_device()
props = torch.cuda.get_device_properties(device)
total_gib = props.total_memory / 2**30
free_bytes, _ = torch.cuda.mem_get_info(device)
free_gib = free_bytes / 2**30
print(f"Fish CUDA device: {props.name} ({total_gib:.1f} GiB total, {free_gib:.1f} GiB free)")
allow_low_vram = os.environ.get("PARCEL_ALLOW_LOW_VRAM", "0").lower() in {
    "1", "true", "yes", "on"
}
if total_gib < 23.5 and not allow_low_vram:
    raise SystemExit(
        "launch_fish_speech: S2 Pro expects about 24 GiB VRAM; set PARCEL_ALLOW_LOW_VRAM=1 to try anyway"
    )
if free_gib < 20.0 and not allow_low_vram:
    raise SystemExit(
        f"launch_fish_speech: only {free_gib:.1f} GiB VRAM is free; stop other GPU models or set PARCEL_ALLOW_LOW_VRAM=1"
    )
PY
fi

ARGS=(
  --llama-checkpoint-path "$CHECKPOINT"
  --decoder-checkpoint-path "$CHECKPOINT/codec.pth"
  --device "$DEVICE"
  --listen "$HOST:$PORT"
  --workers 1
)
if is_true "${PARCEL_FISH_HALF:-1}"; then
  ARGS+=(--half)
fi
if is_true "${PARCEL_FISH_COMPILE:-0}"; then
  ARGS+=(--compile)
fi
if [[ -n ${PARCEL_FISH_API_KEY:-} ]]; then
  ARGS+=(--api-key "$PARCEL_FISH_API_KEY")
fi
ARGS+=("$@")

echo "NOTICE: review $CHECKPOINT/LICENSE.md before production or commercial use."
echo "Fish Speech S2 Pro: http://$HOST:$PORT/v1/tts (device=$DEVICE, one worker)"
cd "$FISH_ROOT"
export PYTHONUNBUFFERED=1
exec "$PYTHON" tools/api_server.py "${ARGS[@]}"
