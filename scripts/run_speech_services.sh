#!/usr/bin/env bash
# Bring up the local speech services Parcel's audio mode needs, and verify
# them. Companion to scripts/install_speech_services.sh — run that first.
#
# Two services, two shapes:
#   whisper.cpp (STT) is a long-lived HTTP server. This script starts it on
#     127.0.0.1:8178 — that address is configs/robot.yaml's
#     speech.whisper_url, so changing it here means changing it there too —
#     and waits until /health answers before returning.
#   Piper (TTS) is NOT a server. providers.PiperSpeechProvider spawns the
#     binary per utterance ("piper --model <voice> --output-raw") and reads
#     the PCM off stdout, so there is nothing to launch: this script only
#     verifies that the binary, the voice and the voice's .onnx.json are in
#     place. The JSON is required — the runtime reads the voice's native
#     sample rate from it and speech plays at the wrong speed without it.
#
# The health probe deliberately mirrors providers._http_health: a 2xx-4xx
# reply proves a live server, a 5xx or a refused connection does not.
#
# Runtime footprint: whisper-server base.en on CPU holds ~400-600 MB RSS and
# runs faster than real time on ~8 threads; no GPU is used. Piper adds ~1
# core per utterance, only while speaking.
#
# -E so the ERR trap fires inside functions too.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

HOST="${PARCEL_WHISPER_HOST:-127.0.0.1}"
PORT="${PARCEL_WHISPER_PORT:-8178}"
BASE_URL="http://$HOST:$PORT"
LANGUAGE="${PARCEL_WHISPER_LANGUAGE:-en}"
WAIT_S="${PARCEL_WHISPER_WAIT_S:-60}"

WHISPER_MODEL="${PARCEL_WHISPER_MODEL_PATH:-$ROOT/models/whisper/ggml-base.en.bin}"
# Preferred binary is the one install_speech_services.sh builds; the official
# prebuilt release tree is accepted as a fallback so an existing checkout
# keeps working. Whichever is used is printed.
WHISPER_SERVER_CANDIDATES=(
  "$ROOT/third_party/whisper.cpp/build/bin/whisper-server"
  "$ROOT/third_party/whisper.cpp-bin/whisper-bin-ubuntu-x64/whisper-server"
)
WHISPER_SERVER="${PARCEL_WHISPER_SERVER:-}"

# These three paths are configs/robot.yaml's speech.piper_binary and
# speech.piper_voice (plus its mandatory companion JSON).
PIPER_BIN="${PARCEL_PIPER_BINARY:-$ROOT/third_party/piper/piper}"
PIPER_VOICE="${PARCEL_PIPER_VOICE:-$ROOT/models/piper/voice.onnx}"
PIPER_VOICE_JSON="$PIPER_VOICE.json"

RUN_DIR="${PARCEL_SPEECH_RUN_DIR:-$ROOT/.cache/speech}"
PID_FILE="$RUN_DIR/whisper-server.pid"
LOG_FILE="$RUN_DIR/whisper-server.log"

MODE="start"
FAILURES=0

usage() {
  cat <<EOF
Usage: scripts/run_speech_services.sh [options] [-- extra whisper-server args]

Starts whisper.cpp's whisper-server on $BASE_URL (configs/robot.yaml's
speech.whisper_url) in the background, waits for /health, and verifies the
Piper binary and voice are installed. Piper itself is not a server: the
runtime spawns it per utterance, so it is only checked, never launched.

Install the services first with scripts/install_speech_services.sh.

Options:
  -h, --help    Show this help and exit
      --check   Probe whisper /health and verify the Piper binary, voice and
                voice .onnx.json. Starts nothing. Exits nonzero, naming every
                failure, if anything is missing or unreachable.
      --stop    Stop the whisper-server this script started (via the pidfile)
      --        Pass every remaining argument through to whisper-server

State (gitignored, override with PARCEL_SPEECH_RUN_DIR):
  $PID_FILE
  $LOG_FILE

Runtime footprint: whisper-server base.en runs CPU-only at ~400-600 MB RSS
and faster than real time on ~8 threads; Piper needs ~1 core per utterance.

Environment overrides:
  PARCEL_WHISPER_HOST, PARCEL_WHISPER_PORT, PARCEL_WHISPER_LANGUAGE
  PARCEL_WHISPER_SERVER, PARCEL_WHISPER_MODEL_PATH, PARCEL_WHISPER_THREADS
  PARCEL_WHISPER_WAIT_S, PARCEL_PIPER_BINARY, PARCEL_PIPER_VOICE
  PARCEL_SPEECH_RUN_DIR, PARCEL_PYTHON

Related: scripts/launch_whisper.sh serves the same model in the foreground
with Silero VAD enabled, for interactive debugging.
EOF
}

log() {
  echo "run_speech_services: $*"
}

die() {
  echo "run_speech_services: ERROR: $*" >&2
  exit 1
}

on_error() {
  echo "run_speech_services: FAILED at line $1" >&2
}

trap 'on_error "$LINENO"' ERR

fail_check() {
  echo "run_speech_services: FAIL: $*" >&2
  FAILURES=$((FAILURES + 1))
}

# Resolved lazily so --help and --stop work on a host without Python.
resolve_python() {
  local candidate="${PARCEL_PYTHON:-}"
  if [[ -n "$candidate" ]]; then
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
    fi
    return 0
  fi
  if [[ -x "$ROOT/.parcel/bin/python" ]]; then
    echo "$ROOT/.parcel/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
  fi
}

PYTHON="$(resolve_python)"

require_python() {
  [[ -n "$PYTHON" ]] || die \
    "no usable Python found (tried \$PARCEL_PYTHON, $ROOT/.parcel/bin/python, python3);
it is needed for the HTTP health probe and to read the Piper voice sample rate"
}

# http_probe URL — 0 healthy, 2 port open but unhealthy, 1 nothing listening.
# The 0/1 split is exactly providers._http_health's rule (a 4xx still proves a
# live server, a 5xx does not); 2 is extra diagnosis so "another process owns
# this port" does not get reported as "whisper is not running".
http_probe() {
  "$PYTHON" - "$HOST" "$PORT" "$1" <<'PY'
import socket
import sys
from urllib.error import HTTPError
from urllib.request import urlopen

host, port, url = sys.argv[1], int(sys.argv[2]), sys.argv[3]
try:
    with urlopen(url, timeout=2.0):
        sys.exit(0)
except HTTPError as error:
    sys.exit(0 if 200 <= error.code < 500 else 2)
except Exception:
    pass
try:
    socket.create_connection((host, port), 1.0).close()
except OSError:
    sys.exit(1)
sys.exit(2)
PY
}

# http_alive URL — true only when the server is healthy.
http_alive() {
  local status=0
  http_probe "$1" || status=$?
  return "$status"
}

resolve_server() {
  if [[ -n "$WHISPER_SERVER" ]]; then
    if [[ -x "$WHISPER_SERVER" ]]; then
      return 0
    fi
    return 1
  fi
  local candidate
  for candidate in "${WHISPER_SERVER_CANDIDATES[@]}"; do
    if [[ -x "$candidate" ]]; then
      WHISPER_SERVER="$candidate"
      return 0
    fi
  done
  # Leave the preferred path set so error messages name the expected location.
  WHISPER_SERVER="${WHISPER_SERVER_CANDIDATES[0]}"
  return 1
}

pidfile_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(tr -dc '0-9' <"$PID_FILE")"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  echo "$pid"
}

# Guard against a recycled pid: never SIGTERM a process that is not the
# server we started. If /proc is unreadable we cannot tell, so we assume ours.
is_whisper_pid() {
  local pid="$1"
  [[ -r "/proc/$pid/cmdline" ]] || return 0
  local cmdline expected="whisper-server"
  cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline")"
  if [[ -n "$WHISPER_SERVER" ]]; then
    expected="$(basename "$WHISPER_SERVER")"
  fi
  [[ "$cmdline" == *"$expected"* || "$cmdline" == *"whisper-server"* ]]
}

validate_config() {
  [[ -n "$HOST" ]] || die "PARCEL_WHISPER_HOST must not be empty"
  [[ "$PORT" =~ ^[0-9]+$ ]] || die "PARCEL_WHISPER_PORT must be an integer (got: $PORT)"
  ((PORT >= 1 && PORT <= 65535)) || die "PARCEL_WHISPER_PORT must be 1-65535 (got: $PORT)"
  [[ "$WAIT_S" =~ ^[1-9][0-9]*$ ]] \
    || die "PARCEL_WHISPER_WAIT_S must be a positive integer (got: $WAIT_S)"
}

log_tail() {
  if [[ -s "$LOG_FILE" ]]; then
    echo "--- last 20 lines of $LOG_FILE ---" >&2
    tail -n 20 "$LOG_FILE" >&2
    echo "--- end of log ---" >&2
  else
    echo "(no output in $LOG_FILE)" >&2
  fi
}

whisper_threads() {
  local threads="${PARCEL_WHISPER_THREADS:-}"
  if [[ -z "$threads" ]]; then
    threads="$(nproc 2>/dev/null || echo 4)"
    if ((threads > 8)); then
      threads=8
    fi
  fi
  [[ "$threads" =~ ^[1-9][0-9]*$ ]] || die "PARCEL_WHISPER_THREADS must be a positive integer"
  echo "$threads"
}

check_piper() {
  if [[ ! -e "$PIPER_BIN" ]]; then
    fail_check "piper binary missing: $PIPER_BIN (run scripts/install_speech_services.sh)"
  elif [[ ! -x "$PIPER_BIN" ]]; then
    fail_check "piper binary is not executable: $PIPER_BIN (chmod +x it)"
  else
    log "OK  piper binary: $PIPER_BIN"
  fi

  if [[ ! -s "$PIPER_VOICE" ]]; then
    fail_check "piper voice missing or empty: $PIPER_VOICE (run scripts/install_speech_services.sh)"
  else
    log "OK  piper voice: $PIPER_VOICE"
  fi

  if [[ ! -s "$PIPER_VOICE_JSON" ]]; then
    fail_check "piper voice metadata missing or empty: $PIPER_VOICE_JSON \
(the runtime reads the voice sample rate from it; without it speech plays at the wrong speed)"
  else
    local rate
    rate="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["audio"]["sample_rate"])' \
      "$PIPER_VOICE_JSON" 2>/dev/null || true)"
    if [[ -z "$rate" ]]; then
      fail_check "piper voice metadata has no audio.sample_rate: $PIPER_VOICE_JSON (re-download it)"
    else
      log "OK  piper voice metadata: $PIPER_VOICE_JSON (${rate} Hz)"
    fi
  fi
}

do_check() {
  require_python
  log "checking speech services (starting nothing)"
  local probe=0
  http_probe "$BASE_URL/health" || probe=$?
  if ((probe == 0)); then
    log "OK  whisper.cpp: $BASE_URL/health answered"
  else
    local pid=""
    pid="$(pidfile_pid || true)"
    if [[ -n "$pid" ]]; then
      fail_check "whisper-server (pid $pid) is running but $BASE_URL/health did not answer; see $LOG_FILE"
    elif ((probe == 2)); then
      fail_check "something is listening on $HOST:$PORT but $BASE_URL/health did not answer healthily — another process may own the port"
    elif ! resolve_server; then
      fail_check "whisper-server is not installed: $WHISPER_SERVER not found (run scripts/install_speech_services.sh)"
    elif [[ ! -s "$WHISPER_MODEL" ]]; then
      fail_check "whisper model missing or empty: $WHISPER_MODEL (run scripts/install_speech_services.sh)"
    else
      fail_check "whisper-server is installed ($WHISPER_SERVER) but not running at $BASE_URL (start it with scripts/run_speech_services.sh)"
    fi
  fi

  check_piper

  if ((FAILURES > 0)); then
    echo "run_speech_services: CHECK FAILED ($FAILURES problem(s)) — speech.mode=audio will not come up" >&2
    exit 1
  fi
  log "CHECK PASSED — stt=whisper.cpp at $BASE_URL, tts=piper ($PIPER_VOICE)"
}

do_stop() {
  if [[ ! -f "$PID_FILE" ]]; then
    log "nothing to stop: no pidfile at $PID_FILE"
    exit 0
  fi
  local pid
  pid="$(pidfile_pid || true)"
  if [[ -z "$pid" ]]; then
    log "stale pidfile removed (process is already gone): $PID_FILE"
    rm -f "$PID_FILE"
    exit 0
  fi
  if ! is_whisper_pid "$pid"; then
    echo "run_speech_services: WARNING: pid $pid is not a whisper-server; refusing to kill it." >&2
    echo "run_speech_services: removing the stale pidfile $PID_FILE" >&2
    rm -f "$PID_FILE"
    exit 0
  fi
  log "stopping whisper-server (pid $pid)"
  kill -TERM "$pid" 2>/dev/null || true
  local waited=0
  while ((waited < 20)); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
    waited=$((waited + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    log "pid $pid ignored SIGTERM; sending SIGKILL"
    kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  log "stopped"
}

do_start() {
  require_python
  if http_alive "$BASE_URL/health"; then
    log "whisper.cpp already healthy at $BASE_URL — leaving it alone"
    check_piper
    if ((FAILURES > 0)); then
      die "piper is not installed correctly; run scripts/install_speech_services.sh"
    fi
    log "READY: stt=whisper.cpp at $BASE_URL, tts=piper ($PIPER_VOICE)"
    return 0
  fi

  local running
  running="$(pidfile_pid || true)"
  if [[ -n "$running" ]]; then
    log "whisper-server (pid $running) is already up but not healthy yet; waiting"
  else
    resolve_server || die \
      "whisper-server not found: $WHISPER_SERVER (run scripts/install_speech_services.sh first)"
    [[ -x "$WHISPER_SERVER" ]] || die "whisper-server is not executable: $WHISPER_SERVER"
    [[ -s "$WHISPER_MODEL" ]] || die \
      "whisper model missing or empty: $WHISPER_MODEL (run scripts/install_speech_services.sh first)"
    local model_size
    model_size="$(stat -c %s "$WHISPER_MODEL")"
    ((model_size > 100000000)) || die \
      "whisper model looks truncated ($model_size bytes): $WHISPER_MODEL — re-run scripts/install_speech_services.sh --force"

    # Fail closed before starting anything: speech.mode=audio needs both
    # halves, and a half-up stack is a worse failure than no stack.
    check_piper
    if ((FAILURES > 0)); then
      die "piper is not installed correctly; run scripts/install_speech_services.sh"
    fi

    local threads
    threads="$(whisper_threads)"
    local args=(
      --model "$WHISPER_MODEL"
      --host "$HOST"
      --port "$PORT"
      --threads "$threads"
      --language "$LANGUAGE"
      --no-gpu
      --no-timestamps
    )
    args+=("$@")

    mkdir -p "$RUN_DIR"
    : >"$LOG_FILE"
    # The prebuilt release tree ships its shared objects next to the binary.
    local server_dir
    server_dir="$(dirname "$WHISPER_SERVER")"
    export LD_LIBRARY_PATH="$server_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    log "starting $WHISPER_SERVER (threads=$threads, language=$LANGUAGE, CPU only)"
    nohup "$WHISPER_SERVER" "${args[@]}" >>"$LOG_FILE" 2>&1 &
    running=$!
    echo "$running" >"$PID_FILE"
    log "whisper-server pid $running, log $LOG_FILE"
  fi

  local deadline=$((WAIT_S * 2))
  local waited=0
  while ((waited < deadline)); do
    if ! kill -0 "$running" 2>/dev/null; then
      rm -f "$PID_FILE"
      log_tail
      die "whisper-server exited during startup (pid $running) — see the log above"
    fi
    if http_alive "$BASE_URL/health"; then
      log "READY: stt=whisper.cpp at $BASE_URL, tts=piper ($PIPER_VOICE)"
      log "stop it later with: scripts/run_speech_services.sh --stop"
      return 0
    fi
    sleep 0.5
    waited=$((waited + 1))
  done

  log_tail
  die "whisper-server did not answer $BASE_URL/health within ${WAIT_S}s (pid $running still alive; stop it with --stop)"
}

main() {
  while (($#)); do
    case "$1" in
      -h | --help)
        usage
        exit 0
        ;;
      --check) MODE="check" ;;
      --stop) MODE="stop" ;;
      --)
        shift
        break
        ;;
      -*) die "unknown option: $1 (see --help)" ;;
      *) die "unexpected argument: $1 (pass whisper-server arguments after --)" ;;
    esac
    shift
  done

  validate_config
  case "$MODE" in
    check)
      (($# == 0)) || die "--check takes no extra whisper-server arguments"
      do_check
      ;;
    stop)
      (($# == 0)) || die "--stop takes no extra whisper-server arguments"
      do_stop
      ;;
    *) do_start "$@" ;;
  esac
}

main "$@"
