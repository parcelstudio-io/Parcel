#!/usr/bin/env bash
# Start (or reuse, or probe) the out-of-process perception daemon — card P1-A.
#
# The daemon owns the GPU: OWLv2 (cuda_fp16 after P0-C) and the SigLIP-2
# encoders, behind an AF_UNIX socket. The robot runtime holds no model; it holds
# a DaemonDetector, which degrades to empty-and-stale when this process is not
# there. That is the entire point of the process boundary — see
# src/parcel_robot/perception_daemon/__init__.py.
#
# A HEALTHY daemon already on the socket is REUSED, never restarted. Two
# executors and an owner share this tree; silently killing someone else's GPU
# process to start your own is the failure this check exists to prevent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.parcel/bin/python"

usage() {
  cat <<'EOF'
Usage: scripts/launch_detector_daemon.sh [options]

Options:
  --socket PATH   AF_UNIX socket to bind (default: $XDG_RUNTIME_DIR/parcel_perception.sock,
                  falling back to /tmp/parcel_perception.sock)
  --preload       Warm the OWLv2 session and the SigLIP-2 TEXT session before
                  serving, so the first real frame does not pay a cold
                  onnxruntime session. NOTE: the SigLIP-2 VISION session still
                  loads lazily on the first embed_image (~0.2-0.4 s measured);
                  see src/parcel_robot/perception_daemon/__main__.py.
  --foreground    Run in this terminal (default). Ctrl-C stops it.
  --background    Fork, wait for the health probe, print the pid, and return.
  --probe         Print a running daemon's health as JSON; exit 1 if unreachable.
  --stop          Ask a running daemon to shut down.
  --timeout SECS  Readiness timeout for --background (default 120)
  -h, --help      Show this help

Environment:
  PARCEL_PERCEPTION_SOCKET   default --socket value
  PARCEL_OWLV2_PROVIDER      provider override passed through to the detector
                             (unset = auto = cuda_fp16 on this host, per P0-C)

The daemon writes no files and touches no config. Its only side effect is the
socket, created mode 0600 and removed on exit.
EOF
}

die() { echo "launch_detector_daemon: $*" >&2; exit 1; }

SOCKET="${PARCEL_PERCEPTION_SOCKET:-}"
PRELOAD=0
MODE="foreground"
TIMEOUT=120

while [[ $# -gt 0 ]]; do
  case "$1" in
    --socket) [[ $# -ge 2 && -n "${2:-}" ]] || die "--socket requires a value"; SOCKET="$2"; shift 2 ;;
    --socket=*) SOCKET="${1#*=}"; shift ;;
    --preload) PRELOAD=1; shift ;;
    --foreground) MODE="foreground"; shift ;;
    --background) MODE="background"; shift ;;
    --probe) MODE="probe"; shift ;;
    --stop) MODE="stop"; shift ;;
    --timeout) [[ $# -ge 2 ]] || die "--timeout requires a value"; TIMEOUT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

[[ -x "$PYTHON" ]] || die "missing Parcel environment: $PYTHON"

DAEMON_ARGS=()
[[ -n "$SOCKET" ]] && DAEMON_ARGS+=(--socket "$SOCKET")

probe() {
  "$PYTHON" -m parcel_robot.perception_daemon --probe "${DAEMON_ARGS[@]}" "$@"
}

case "$MODE" in
  probe) exec "$PYTHON" -m parcel_robot.perception_daemon --probe "${DAEMON_ARGS[@]}" ;;
  stop)  exec "$PYTHON" -m parcel_robot.perception_daemon --shutdown "${DAEMON_ARGS[@]}" ;;
esac

# Reuse, never restart. A daemon that answers a health probe is someone's live
# GPU process — possibly the owner's.
if probe >/dev/null 2>&1; then
  echo "Reusing the healthy perception daemon already on ${SOCKET:-the default socket}:"
  probe
  exit 0
fi

RUN_ARGS=("${DAEMON_ARGS[@]}")
(( PRELOAD )) && RUN_ARGS+=(--preload)

if [[ "$MODE" == "foreground" ]]; then
  echo "Starting the perception daemon (foreground; Ctrl-C to stop)"
  exec "$PYTHON" -m parcel_robot.perception_daemon "${RUN_ARGS[@]}"
fi

# The daemon OUTLIVES this script, so it must not keep this script's stdout and
# stderr open: a caller that pipes us (`launch_stack.sh`, `| tee`, a CI step)
# would then wait forever for an EOF the daemon is never going to send. Its
# output goes to a log file, whose path is printed, and stdin is detached.
LOG_FILE="${PARCEL_PERCEPTION_LOG:-${XDG_RUNTIME_DIR:-/tmp}/parcel_perception.log}"
mkdir -p "$(dirname "$LOG_FILE")"
echo "Starting the perception daemon in the background (log: $LOG_FILE)"
"$PYTHON" -m parcel_robot.perception_daemon "${RUN_ARGS[@]}" \
  </dev/null >>"$LOG_FILE" 2>&1 &
DAEMON_PID=$!

deadline=$((SECONDS + TIMEOUT))
while (( SECONDS < deadline )); do
  if probe >/dev/null 2>&1; then
    echo "perception daemon ready (pid $DAEMON_PID)"
    probe
    exit 0
  fi
  if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
    set +e; wait "$DAEMON_PID"; status=$?; set -e
    die "the perception daemon exited during startup (status $status)"
  fi
  sleep 0.5
done

# Only ever kill the process THIS script started.
kill -TERM "$DAEMON_PID" 2>/dev/null || true
die "timed out after ${TIMEOUT}s waiting for the perception daemon"
