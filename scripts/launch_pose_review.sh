#!/usr/bin/env bash
# Launch MuJoCo plus the simulator-only browser pose/gesture gallery.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_SIM="$ROOT/scripts/launch_sim.sh"

usage() {
  cat <<'EOF'
Usage: scripts/launch_pose_review.sh [options passed to launch_sim.sh]

Starts MuJoCo and opens the bounded pose/gesture review page at /poses.
After a 3-second countdown, every pose and trajectory plays in catalog order.
The page can also run one motion or step previous/next.
Watch the native MuJoCo window for articulated joint motion.

Pose-review option:
  --manual            Open the gallery without starting the automatic review
  --autoplay          Explicitly select the default automatic review behavior

Useful launch_sim options:
  --config FILE       Use another Parcel configuration
  --scene FILE        Use another MuJoCo scene
  --socket PATH       Use a distinct simulator socket
  --port PORT         Use a distinct browser-panel port
  --no-browser        Print the URL without opening a browser
  -h, --help          Show this help

The gallery runs without a language model or audio services. All other options
are forwarded to scripts/launch_sim.sh. Ctrl+C or closing MuJoCo stops both the
simulator and browser server.
EOF
}

[[ -x "$LAUNCH_SIM" ]] || {
  echo "launch_pose_review: missing executable $LAUNCH_SIM" >&2
  exit 1
}

BROWSER_PATH="/poses?autoplay=1"
FORWARDED=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --autoplay)
      BROWSER_PATH="/poses?autoplay=1"
      shift
      ;;
    --manual)
      BROWSER_PATH="/poses"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      FORWARDED+=("$@")
      break
      ;;
    *)
      FORWARDED+=("$1")
      shift
      ;;
  esac
done

# Voice/audio are irrelevant to visual commissioning. Operators may explicitly
# override this environment variable if they also want to inspect audio state.
export PARCEL_SKIP_AUDIO_ENV="${PARCEL_SKIP_AUDIO_ENV:-1}"

echo "Launching simulator pose review at ${BROWSER_PATH}"
exec "$LAUNCH_SIM" \
  --no-llm \
  --panel-arg=--pose-review \
  --panel-arg=--browser-path \
  --panel-arg="$BROWSER_PATH" \
  "${FORWARDED[@]}"
