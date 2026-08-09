#!/usr/bin/env bash
# Launch the MuJoCo simulator and browser control panel as one lifecycle.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.parcel/bin/python"

usage() {
  cat <<'EOF'
Usage: scripts/launch_sim.sh [options]

Options:
  --socket PATH       Simulator Unix socket (default: /tmp/parcel_sim.sock)
  --config FILE       Parcel YAML config passed to both processes
  --scene FILE        MuJoCo scene passed to parcel-sim
  --host HOST         Control-panel bind host (default: 127.0.0.1)
  --port PORT         Control-panel port (default: 8765)
  --llm               Require the configured local reasoner
  --no-llm            Run deterministic text commands without a reasoner
  --no-browser        Do not open a browser window (useful over SSH/headless)
  --kp VALUE          Simulator joint position gain
  --kd VALUE          Simulator joint damping gain
  --sim-arg ARG       Pass one additional argument to parcel-sim (repeatable)
  --panel-arg ARG     Pass one additional argument to parcel-panel (repeatable)
  -h, --help          Show this help

Environment:
  PARCEL_SIM_SOCKET   Default socket when --socket is omitted
  PARCEL_PANEL_HOST   Default panel host
  PARCEL_PANEL_PORT   Default panel port
EOF
}

die() {
  echo "launch_sim: $*" >&2
  exit 1
}

need_value() {
  [[ $# -ge 2 && -n "${2:-}" ]] || die "$1 requires a value"
}

[[ -x "$PYTHON" ]] || die \
  "missing $PYTHON; create the environment and install Parcel with: python3 -m venv .parcel && .parcel/bin/pip install -e '.[dev]'"

if ! "$PYTHON" -c 'import mujoco, parcel_robot.sim, parcel_robot.web_panel' >/dev/null 2>&1; then
  die "Parcel simulator dependencies are not installed in .parcel; run: .parcel/bin/pip install -e '.[dev]'"
fi

# User-space PortAudio so sounddevice can open the mic/speaker without root.
# Never fatal: speech.mode=auto degrades loudly to text mode, and the whole
# simulator must still come up on a host with no audio at all. Set
# PARCEL_SKIP_AUDIO_ENV=1 to opt out entirely.
if [[ "${PARCEL_SKIP_AUDIO_ENV:-0}" != "1" && -f "$ROOT/scripts/env-audio.sh" ]]; then
  # shellcheck source=scripts/env-audio.sh
  source "$ROOT/scripts/env-audio.sh" || true
fi

SOCKET="${PARCEL_SIM_SOCKET:-/tmp/parcel_sim.sock}"
PANEL_HOST="${PARCEL_PANEL_HOST:-127.0.0.1}"
PANEL_PORT="${PARCEL_PANEL_PORT:-8765}"
CONFIG=""
SCENE=""
LLM_MODE=""
NO_BROWSER=0
SIM_ARGS=()
PANEL_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --socket)
      need_value "$@"
      SOCKET="$2"
      shift 2
      ;;
    --socket=*) SOCKET="${1#*=}"; shift ;;
    --config)
      need_value "$@"
      CONFIG="$2"
      shift 2
      ;;
    --config=*) CONFIG="${1#*=}"; shift ;;
    --scene)
      need_value "$@"
      SCENE="$2"
      shift 2
      ;;
    --scene=*) SCENE="${1#*=}"; shift ;;
    --host)
      need_value "$@"
      PANEL_HOST="$2"
      shift 2
      ;;
    --host=*) PANEL_HOST="${1#*=}"; shift ;;
    --port)
      need_value "$@"
      PANEL_PORT="$2"
      shift 2
      ;;
    --port=*) PANEL_PORT="${1#*=}"; shift ;;
    --llm) LLM_MODE="--llm"; shift ;;
    --no-llm) LLM_MODE="--no-llm"; shift ;;
    --no-browser) NO_BROWSER=1; shift ;;
    --kp|--kd)
      need_value "$@"
      SIM_ARGS+=("$1" "$2")
      shift 2
      ;;
    --sim-arg)
      need_value "$@"
      SIM_ARGS+=("$2")
      shift 2
      ;;
    --sim-arg=*) SIM_ARGS+=("${1#*=}"); shift ;;
    --panel-arg)
      need_value "$@"
      PANEL_ARGS+=("$2")
      shift 2
      ;;
    --panel-arg=*) PANEL_ARGS+=("${1#*=}"); shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

[[ -n "$SOCKET" ]] || die "socket path must not be empty"
[[ -n "$PANEL_HOST" ]] || die "panel host must not be empty"
[[ "$PANEL_PORT" =~ ^[0-9]+$ ]] || die "panel port must be an integer"
(( PANEL_PORT >= 1 && PANEL_PORT <= 65535 )) || die "panel port must be between 1 and 65535"

if [[ "$SOCKET" != /* ]]; then
  SOCKET="$ROOT/$SOCKET"
fi
SOCKET_PARENT="$(dirname "$SOCKET")"
[[ -d "$SOCKET_PARENT" ]] || die "socket parent directory does not exist: $SOCKET_PARENT"
[[ -w "$SOCKET_PARENT" ]] || die "socket parent directory is not writable: $SOCKET_PARENT"

if [[ -n "$CONFIG" ]]; then
  [[ "$CONFIG" = /* ]] || CONFIG="$ROOT/$CONFIG"
  [[ -f "$CONFIG" ]] || die "config file not found: $CONFIG"
fi
if [[ -n "$SCENE" ]]; then
  [[ "$SCENE" = /* ]] || SCENE="$ROOT/$SCENE"
  [[ -f "$SCENE" ]] || die "scene file not found: $SCENE"
fi

# Do not remove paths here. The simulator only replaces a verified Unix socket;
# this probe prevents it from replacing the endpoint of an already-running sim.
set +e
"$PYTHON" - "$SOCKET" <<'PY'
import errno
import os
import socket
import stat
import sys

path = sys.argv[1]
if len(os.fsencode(path)) > 107:
    print(f"Unix socket path is too long ({len(os.fsencode(path))} bytes; max 107): {path}", file=sys.stderr)
    raise SystemExit(22)
try:
    mode = os.lstat(path).st_mode
except FileNotFoundError:
    raise SystemExit(0)
except OSError as exc:
    print(f"cannot inspect socket path {path}: {exc}", file=sys.stderr)
    raise SystemExit(22)
if not stat.S_ISSOCK(mode):
    print(f"refusing to replace non-socket path: {path}", file=sys.stderr)
    raise SystemExit(21)
probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
probe.settimeout(0.35)
try:
    probe.connect(path)
except OSError as exc:
    if exc.errno in {errno.ECONNREFUSED, errno.ENOENT}:
        print(f"Found stale simulator socket; parcel-sim will replace it safely: {path}")
        raise SystemExit(23)
    print(f"cannot safely classify existing socket {path}: {exc}", file=sys.stderr)
    raise SystemExit(22)
finally:
    probe.close()
print(f"a simulator is already listening on {path}", file=sys.stderr)
raise SystemExit(20)
PY
SOCKET_CHECK=$?
set -e
STALE_SOCKET_ID=""
case "$SOCKET_CHECK" in
  0) ;;
  23)
    STALE_SOCKET_ID="$(stat -c '%d:%i' -- "$SOCKET")" || die "could not identify stale socket: $SOCKET"
    ;;
  20|21|22) exit 1 ;;
  *) die "socket preflight failed with status $SOCKET_CHECK" ;;
esac

SIM_CMD=("$PYTHON" -m parcel_robot.sim --socket "$SOCKET")
PANEL_CMD=("$PYTHON" -m parcel_robot.web_panel --socket "$SOCKET" --host "$PANEL_HOST" --port "$PANEL_PORT")
if [[ -n "$CONFIG" ]]; then
  SIM_CMD+=(--config "$CONFIG")
  PANEL_CMD+=(--config "$CONFIG")
fi
if [[ -n "$SCENE" ]]; then
  SIM_CMD+=(--scene "$SCENE")
fi
if [[ -n "$LLM_MODE" ]]; then
  PANEL_CMD+=("$LLM_MODE")
fi
if (( NO_BROWSER )); then
  PANEL_CMD+=(--no-browser)
fi
SIM_CMD+=("${SIM_ARGS[@]}")
PANEL_CMD+=("${PANEL_ARGS[@]}")

SIM_PID=""
PANEL_PID=""

terminate_child() {
  local pid="$1"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null || true
  fi
  [[ -z "$pid" ]] || wait "$pid" 2>/dev/null || true
}

cleanup_owned_socket() {
  [[ -n "$SIM_PID" ]] || return 0
  "$PYTHON" - "$SOCKET" <<'PY' || true
import errno
import os
import socket
import stat
import sys

path = sys.argv[1]
try:
    before = os.lstat(path)
except FileNotFoundError:
    raise SystemExit(0)
except OSError as exc:
    print(f"launch_sim: could not inspect leftover socket {path}: {exc}", file=sys.stderr)
    raise SystemExit(1)
if not stat.S_ISSOCK(before.st_mode):
    print(f"launch_sim: preserving non-socket path found during cleanup: {path}", file=sys.stderr)
    raise SystemExit(1)
probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
probe.settimeout(0.25)
try:
    probe.connect(path)
except OSError as exc:
    if exc.errno not in {errno.ECONNREFUSED, errno.ENOENT}:
        print(f"launch_sim: preserving socket with uncertain state {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)
else:
    print(f"launch_sim: preserving active simulator socket: {path}", file=sys.stderr)
    raise SystemExit(1)
finally:
    probe.close()
try:
    after = os.lstat(path)
except FileNotFoundError:
    raise SystemExit(0)
if not stat.S_ISSOCK(after.st_mode) or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
    print(f"launch_sim: socket path changed during cleanup; preserving it: {path}", file=sys.stderr)
    raise SystemExit(1)
os.unlink(path)
PY
}

cleanup() {
  trap - EXIT INT TERM
  terminate_child "$PANEL_PID"
  terminate_child "$SIM_PID"
  cleanup_owned_socket
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cd "$ROOT"
export PYTHONUNBUFFERED=1
echo "Starting parcel-sim on $SOCKET"
"${SIM_CMD[@]}" &
SIM_PID=$!

for _ in {1..200}; do
  if [[ -S "$SOCKET" ]]; then
    CURRENT_SOCKET_ID="$(stat -c '%d:%i' -- "$SOCKET" 2>/dev/null || true)"
    if [[ -z "$STALE_SOCKET_ID" || "$CURRENT_SOCKET_ID" != "$STALE_SOCKET_ID" ]]; then
      break
    fi
  fi
  if ! kill -0 "$SIM_PID" 2>/dev/null; then
    set +e
    wait "$SIM_PID"
    STATUS=$?
    set -e
    die "parcel-sim exited before its socket was ready (status $STATUS)"
  fi
  sleep 0.05
done
[[ -S "$SOCKET" ]] || die "timed out waiting 10 seconds for simulator socket: $SOCKET"

echo "Starting Parcel control deck at http://$PANEL_HOST:$PANEL_PORT"
(( NO_BROWSER )) && echo "Browser auto-open disabled; open the URL manually."
echo "Closing either process or pressing Ctrl+C stops both."
"${PANEL_CMD[@]}" &
PANEL_PID=$!

while kill -0 "$SIM_PID" 2>/dev/null && kill -0 "$PANEL_PID" 2>/dev/null; do
  sleep 0.2
done

set +e
if ! kill -0 "$SIM_PID" 2>/dev/null; then
  wait "$SIM_PID"
  STATUS=$?
  echo "parcel-sim exited (status $STATUS); stopping control deck."
else
  wait "$PANEL_PID"
  STATUS=$?
  echo "parcel-panel exited (status $STATUS); stopping simulator."
fi
set -e
exit "$STATUS"
