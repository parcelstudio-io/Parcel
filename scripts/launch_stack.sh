#!/usr/bin/env bash
# Orchestrate local model services, MuJoCo, and the Parcel browser panel.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.parcel/bin/python"

usage() {
  cat <<'EOF'
Usage: scripts/launch_stack.sh [stack options] [launch_sim options]

Default: start/reuse Gemma reasoning, then launch MuJoCo + the browser panel.

Stack options:
  --fish             Also start/reuse Fish Audio S2 Pro on port 8091
  --whisper          Also start/reuse whisper.cpp ASR on port 8178
  --no-reasoner      Do not start Gemma; force deterministic panel commands
  -h, --help         Show this help

All other options are forwarded to scripts/launch_sim.sh, for example:
  scripts/launch_stack.sh --no-browser
  scripts/launch_stack.sh --fish --socket /tmp/parcel_demo.sock --port 9000

Environment equivalents:
  PARCEL_ENABLE_REASONER=0|1 (default 1)
  PARCEL_ENABLE_FISH=0|1     (default 0; opt-in for GPU/license reasons)
  PARCEL_ENABLE_WHISPER=0|1  (default 0; useful after an audio endpoint exists)

Services that were already healthy are reused and are not stopped on exit.
Only processes started by this invocation are cleaned up.
EOF
}

die() {
  echo "launch_stack: $*" >&2
  exit 1
}

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

ENABLE_REASONER="${PARCEL_ENABLE_REASONER:-1}"
ENABLE_FISH="${PARCEL_ENABLE_FISH:-0}"
ENABLE_WHISPER="${PARCEL_ENABLE_WHISPER:-0}"
SIM_ARGS=()
PANEL_LLM_ARG=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fish) ENABLE_FISH=1; shift ;;
    --whisper) ENABLE_WHISPER=1; shift ;;
    --no-reasoner) ENABLE_REASONER=0; shift ;;
    --llm)
      ENABLE_REASONER=1
      PANEL_LLM_ARG=1
      SIM_ARGS+=("$1")
      shift
      ;;
    --no-llm)
      ENABLE_REASONER=0
      PANEL_LLM_ARG=1
      SIM_ARGS+=("$1")
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    --)
      shift
      SIM_ARGS+=("$@")
      break
      ;;
    *) SIM_ARGS+=("$1"); shift ;;
  esac
done

[[ -x "$PYTHON" ]] || die "missing Parcel environment: $PYTHON"
for script in launch_reasoner.sh launch_whisper.sh launch_fish_speech.sh launch_sim.sh; do
  [[ -x "$ROOT/scripts/$script" ]] || die "missing executable script: $ROOT/scripts/$script"
done

if (( ! PANEL_LLM_ARG )); then
  if is_true "$ENABLE_REASONER"; then
    SIM_ARGS+=(--llm)
  else
    SIM_ARGS+=(--no-llm)
  fi
fi

http_ready() {
  "$PYTHON" - "$1" "${2:-}" >/dev/null 2>&1 <<'PY'
import json
import sys
import urllib.request

try:
    request = urllib.request.Request(sys.argv[1])
    if sys.argv[2]:
        request.add_header("Authorization", f"Bearer {sys.argv[2]}")
    with urllib.request.urlopen(request, timeout=1.0) as response:
        body = response.read(4096)
        if not 200 <= response.status < 300:
            raise SystemExit(1)
        if body:
            data = json.loads(body)
            if isinstance(data, dict) and data.get("status") not in {None, "ok"}:
                raise SystemExit(1)
except Exception:
    raise SystemExit(1)
PY
}

tcp_ready() {
  "$PYTHON" - "$1" "$2" >/dev/null 2>&1 <<'PY'
import socket
import sys

try:
    with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=1.0):
        pass
except OSError:
    raise SystemExit(1)
PY
}

OWNED_PIDS=()
OWNED_NAMES=()

cleanup() {
  trap - EXIT INT TERM
  local index pid
  for ((index=${#OWNED_PIDS[@]} - 1; index >= 0; index--)); do
    pid="${OWNED_PIDS[index]}"
    if kill -0 "$pid" 2>/dev/null; then
      echo "Stopping ${OWNED_NAMES[index]} (pid $pid)"
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for pid in "${OWNED_PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_for_http() {
  local url="$1" pid="$2" name="$3" timeout="$4"
  local token="${5:-}"
  local deadline=$((SECONDS + timeout)) next_update=$((SECONDS + 10))
  while (( SECONDS < deadline )); do
    http_ready "$url" "$token" && return 0
    if ! kill -0 "$pid" 2>/dev/null; then
      set +e
      wait "$pid"
      local status=$?
      set -e
      echo "$name exited during startup (status $status)." >&2
      return 1
    fi
    if (( SECONDS >= next_update )); then
      echo "Still waiting for $name..."
      next_update=$((SECONDS + 10))
    fi
    sleep 0.5
  done
  echo "Timed out after ${timeout}s waiting for $name at $url" >&2
  return 1
}

wait_for_tcp() {
  local host="$1" port="$2" pid="$3" name="$4" timeout="$5"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    tcp_ready "$host" "$port" && return 0
    if ! kill -0 "$pid" 2>/dev/null; then
      set +e
      wait "$pid"
      local status=$?
      set -e
      echo "$name exited during startup (status $status)." >&2
      return 1
    fi
    sleep 0.25
  done
  echo "Timed out after ${timeout}s waiting for $name at $host:$port" >&2
  return 1
}

start_owned() {
  local name="$1"
  shift
  echo "Starting $name"
  "$@" &
  OWNED_PIDS+=("$!")
  OWNED_NAMES+=("$name")
}

if is_true "$ENABLE_REASONER"; then
  REASONER_PORT="${PARCEL_REASONER_PORT:-8080}"
  REASONER_HEALTH="${PARCEL_REASONER_HEALTH_URL:-http://127.0.0.1:$REASONER_PORT/health}"
  if http_ready "$REASONER_HEALTH"; then
    echo "Reusing healthy Gemma reasoner at $REASONER_HEALTH"
  else
    start_owned "Gemma reasoner" "$ROOT/scripts/launch_reasoner.sh"
    REASONER_PID="${OWNED_PIDS[${#OWNED_PIDS[@]}-1]}"
    wait_for_http "$REASONER_HEALTH" "$REASONER_PID" "Gemma reasoner" 180 || exit 1
  fi
fi

if is_true "$ENABLE_WHISPER"; then
  WHISPER_HOST="${PARCEL_WHISPER_PROBE_HOST:-127.0.0.1}"
  WHISPER_PORT="${PARCEL_WHISPER_PORT:-8178}"
  if tcp_ready "$WHISPER_HOST" "$WHISPER_PORT"; then
    echo "Reusing whisper.cpp server at $WHISPER_HOST:$WHISPER_PORT"
  else
    start_owned "whisper.cpp ASR" "$ROOT/scripts/launch_whisper.sh"
    WHISPER_PID="${OWNED_PIDS[${#OWNED_PIDS[@]}-1]}"
    wait_for_tcp "$WHISPER_HOST" "$WHISPER_PORT" "$WHISPER_PID" "whisper.cpp ASR" 60 || exit 1
  fi
fi

if is_true "$ENABLE_FISH"; then
  FISH_PORT="${PARCEL_FISH_PORT:-8091}"
  FISH_HEALTH="${PARCEL_FISH_HEALTH_URL:-http://127.0.0.1:$FISH_PORT/v1/health}"
  FISH_API_KEY="${PARCEL_FISH_API_KEY:-}"
  if http_ready "$FISH_HEALTH" "$FISH_API_KEY"; then
    echo "Reusing healthy Fish Speech server at $FISH_HEALTH"
  else
    echo "Fish S2 Pro is opt-in; review its checkpoint license before commercial use."
    start_owned "Fish Speech S2 Pro" "$ROOT/scripts/launch_fish_speech.sh"
    FISH_PID="${OWNED_PIDS[${#OWNED_PIDS[@]}-1]}"
    wait_for_http "$FISH_HEALTH" "$FISH_PID" "Fish Speech S2 Pro" 300 "$FISH_API_KEY" || exit 1
  fi
fi

echo "Model services ready; starting simulator and browser control deck."
set +e
"$ROOT/scripts/launch_sim.sh" "${SIM_ARGS[@]}"
STATUS=$?
set -e
exit "$STATUS"
