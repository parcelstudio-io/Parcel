#!/usr/bin/env bash
# Serve the installed whisper.cpp base.en model for local streaming-ASR clients.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHISPER_DIR="${PARCEL_WHISPER_CPP_DIR:-$ROOT/third_party/whisper.cpp-bin/whisper-bin-ubuntu-x64}"
WHISPER_SERVER="${PARCEL_WHISPER_SERVER:-$WHISPER_DIR/whisper-server}"
MODEL="${PARCEL_WHISPER_MODEL_PATH:-$ROOT/models/whisper/ggml-base.en.bin}"
VAD_MODEL="${PARCEL_WHISPER_VAD_MODEL_PATH:-$ROOT/models/whisper/ggml-silero-v6.2.0.bin}"
HOST="${PARCEL_WHISPER_HOST:-127.0.0.1}"
PORT="${PARCEL_WHISPER_PORT:-8178}"
THREADS="${PARCEL_WHISPER_THREADS:-48}"
LANGUAGE="${PARCEL_WHISPER_LANGUAGE:-en}"

usage() {
  cat <<'EOF'
Usage: scripts/launch_whisper.sh [additional whisper-server arguments]

Serves the English whisper.cpp base model at http://127.0.0.1:8178/inference.
This service is optional while Parcel is in text-input mode.

Environment overrides:
  PARCEL_WHISPER_CPP_DIR, PARCEL_WHISPER_SERVER, PARCEL_WHISPER_MODEL_PATH
  PARCEL_WHISPER_HOST, PARCEL_WHISPER_PORT, PARCEL_WHISPER_THREADS
  PARCEL_WHISPER_LANGUAGE, PARCEL_WHISPER_VAD_MODEL_PATH
  PARCEL_WHISPER_VAD=0   Disable the default Silero VAD
EOF
}

die() {
  echo "launch_whisper: $*" >&2
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

[[ -x "$WHISPER_SERVER" ]] || die \
  "whisper-server not found or not executable: $WHISPER_SERVER (install the official whisper.cpp release under third_party/whisper.cpp-bin)"
[[ -s "$MODEL" ]] || die \
  "Whisper model not found: $MODEL (download whisper.cpp ggml-base.en.bin)"
[[ -n "$HOST" ]] || die "PARCEL_WHISPER_HOST must not be empty"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "PARCEL_WHISPER_PORT must be an integer"
(( PORT >= 1 && PORT <= 65535 )) || die "PARCEL_WHISPER_PORT must be between 1 and 65535"
[[ "$THREADS" =~ ^[1-9][0-9]*$ ]] || die "PARCEL_WHISPER_THREADS must be a positive integer"

MODEL_SIZE="$(stat -c %s "$MODEL")"
(( MODEL_SIZE > 100000000 )) || die "Whisper model looks incomplete ($MODEL_SIZE bytes): $MODEL"

ARGS=(
  --model "$MODEL"
  --host "$HOST"
  --port "$PORT"
  --threads "$THREADS"
  --language "$LANGUAGE"
  --no-gpu
  --no-timestamps
  --suppress-nst
)
if is_true "${PARCEL_WHISPER_VAD:-1}"; then
  [[ -s "$VAD_MODEL" ]] || die \
    "Silero VAD model not found: $VAD_MODEL (download ggml-org/whisper-vad)"
  VAD_SIZE="$(stat -c %s "$VAD_MODEL")"
  (( VAD_SIZE > 500000 )) || die "VAD model looks incomplete ($VAD_SIZE bytes): $VAD_MODEL"
  ARGS+=(--vad --vad-model "$VAD_MODEL")
fi
ARGS+=("$@")

export LD_LIBRARY_PATH="$WHISPER_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
echo "Whisper ASR: http://$HOST:$PORT/inference (CPU, language=$LANGUAGE, threads=$THREADS, VAD=${PARCEL_WHISPER_VAD:-1})"
echo "Model: $MODEL"
exec "$WHISPER_SERVER" "${ARGS[@]}"
