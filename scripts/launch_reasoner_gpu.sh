#!/usr/bin/env bash
# Serve a profile-pinned Parcel reasoner only after CUDA admission passes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${PARCEL_REASONER_GPU_PROFILE:-$ROOT/configs/reasoner/llama_cpp_cuda12_oci_b10236.json}"
OCI_ROOT="${PARCEL_LLAMA_CUDA_ROOTFS:-$ROOT/third_party/llama.cpp-oci/llama-b10236-cuda12/rootfs}"
LLAMA_DIR="${PARCEL_LLAMA_CUDA_DIR:-$OCI_ROOT/app}"
LLAMA_SERVER="${PARCEL_LLAMA_CUDA_SERVER:-$LLAMA_DIR/llama-server}"
CUDA_COMPAT_LIB="${PARCEL_LLAMA_CUDA_COMPAT_LIB:-$OCI_ROOT/usr/local/cuda/lib64}"
CUDA_TARGET_LIB="${PARCEL_LLAMA_CUDA_TARGET_LIB:-$OCI_ROOT/usr/local/cuda-12.8/targets/x86_64-linux/lib}"
NCCL_LIBRARY="${PARCEL_LLAMA_NCCL_LIBRARY:-$OCI_ROOT/usr/lib/x86_64-linux-gnu/libnccl.so.2.25.1}"
MODEL="${PARCEL_REASONER_MODEL_PATH:-$ROOT/models/gemma-4-26b-a4b/gemma-4-26B_q4_0-it.gguf}"
PYTHON="${PARCEL_PYTHON:-$ROOT/.parcel/bin/python}"
HOST="${PARCEL_REASONER_HOST:-127.0.0.1}"
PORT="${PARCEL_REASONER_PORT:-8081}"
THREADS="${PARCEL_REASONER_THREADS:-32}"
BATCH_THREADS="${PARCEL_REASONER_BATCH_THREADS:-32}"
CTX_SIZE="${PARCEL_REASONER_CTX_SIZE:-8192}"
GPU_LAYERS="${PARCEL_REASONER_GPU_LAYERS:-999}"
ALIAS="${PARCEL_REASONER_MODEL_ALIAS:-gemma-4-26b-a4b}"
LOG_FILE="${PARCEL_REASONER_LOG_FILE:-}"

usage() {
  cat <<'EOF'
Usage: scripts/launch_reasoner_gpu.sh [additional llama-server arguments]

Serves the model selected by the CUDA profile and environment overrides with
the provenance-locked official llama.cpp b10236 CUDA 12 OCI runtime. The
read-only doctor verifies the exact image marker and critical-file hashes,
model hash, server version, CUDA backend/device, compute capability, and VRAM
floors before model load.

This profile does not replace scripts/launch_reasoner.sh or its CPU binary.
Prepare it with scripts/fetch_reasoner_cuda_oci.py --prepare.

Environment overrides:
  PARCEL_REASONER_GPU_PROFILE, PARCEL_LLAMA_CUDA_ROOTFS
  PARCEL_LLAMA_CUDA_DIR, PARCEL_LLAMA_CUDA_SERVER, PARCEL_REASONER_MODEL_PATH
  PARCEL_LLAMA_CUDA_COMPAT_LIB, PARCEL_LLAMA_CUDA_TARGET_LIB
  PARCEL_LLAMA_NCCL_LIBRARY, PARCEL_REASONER_LOG_FILE
  PARCEL_PYTHON, PARCEL_REASONER_HOST, PARCEL_REASONER_PORT
  PARCEL_REASONER_THREADS, PARCEL_REASONER_BATCH_THREADS
  PARCEL_REASONER_CTX_SIZE, PARCEL_REASONER_GPU_LAYERS
  PARCEL_REASONER_MODEL_ALIAS, PARCEL_REASONER_CUDA_VISIBLE_DEVICES

Arguments after -- are passed to llama-server after the pinned defaults.
EOF
}

die() {
  echo "launch_reasoner_gpu: $*" >&2
  exit 1
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi
[[ ${1:-} == "--" ]] && shift

[[ -x "$PYTHON" ]] || die "Parcel Python is missing: $PYTHON"
[[ -x "$LLAMA_SERVER" ]] || die \
  "pinned CUDA llama-server is missing: $LLAMA_SERVER (run scripts/fetch_reasoner_cuda_oci.py --prepare)"
[[ -f "$PROFILE" ]] || die "CUDA profile is missing: $PROFILE"
[[ -d "$CUDA_COMPAT_LIB" ]] || die "CUDA compatibility library directory is missing: $CUDA_COMPAT_LIB"
[[ -d "$CUDA_TARGET_LIB" ]] || die "CUDA target library directory is missing: $CUDA_TARGET_LIB"
[[ -f "$NCCL_LIBRARY" ]] || die "NCCL library is missing: $NCCL_LIBRARY"
[[ -n "$HOST" ]] || die "PARCEL_REASONER_HOST must not be empty"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "PARCEL_REASONER_PORT must be an integer"
(( PORT >= 1 && PORT <= 65535 )) || die "PARCEL_REASONER_PORT must be between 1 and 65535"
for setting in "$THREADS" "$BATCH_THREADS" "$CTX_SIZE" "$GPU_LAYERS"; do
  [[ "$setting" =~ ^[1-9][0-9]*$ ]] || die \
    "thread counts, context size, and GPU layers must be positive integers"
done

export CUDA_VISIBLE_DEVICES="${PARCEL_REASONER_CUDA_VISIBLE_DEVICES:-0}"
export LD_LIBRARY_PATH="$LLAMA_DIR:$CUDA_COMPAT_LIB:$CUDA_TARGET_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LD_PRELOAD="$NCCL_LIBRARY${LD_PRELOAD:+:$LD_PRELOAD}"
if ! PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" \
  -m parcel_robot.reasoner_gpu \
  --profile "$PROFILE" \
  --repo-root "$ROOT" \
  --binary "$LLAMA_SERVER" \
  --model "$MODEL" \
  --require-inference-ready \
  --compact; then
  die "CUDA admission failed; no model was loaded"
fi

echo "Parcel reasoner ($ALIAS): http://$HOST:$PORT/v1 (CUDA device $CUDA_VISIBLE_DEVICES, requested GPU layers $GPU_LAYERS)"
echo "Model artifact: $MODEL"
server_args=(
  --model "$MODEL"
  --alias "$ALIAS"
  --host "$HOST"
  --port "$PORT"
  --ctx-size "$CTX_SIZE"
  --threads "$THREADS"
  --threads-batch "$BATCH_THREADS"
  --n-gpu-layers "$GPU_LAYERS"
  --jinja
  --reasoning auto
  --reasoning-format deepseek
  --metrics
)
if [[ -n "$LOG_FILE" ]]; then
  [[ -d "$(dirname "$LOG_FILE")" ]] || die "reasoner log directory is missing: $(dirname "$LOG_FILE")"
  server_args+=(--log-file "$LOG_FILE" --log-timestamps)
fi
exec "$LLAMA_SERVER" "${server_args[@]}" "$@"
