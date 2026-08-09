#!/usr/bin/env bash
# Watch the live voice->nav e2e cases run SEQUENTIALLY in a native MuJoCo window.
#
# Each case gets its own sim process and its own viewer window (the e2e harness
# already tears both down between cases), preceded by a banner — instruction,
# expected outcome, goal region — and followed by the verdict and the case's own
# key metrics. A scoreboard prints at the end.
#
#   scripts/watch_nav_evals.sh                 # every case, in file order
#   scripts/watch_nav_evals.sh --only sidewalk # substring filter on the case name
#   scripts/watch_nav_evals.sh --pause         # wait for Enter between cases
#   scripts/watch_nav_evals.sh --list          # print the plan, run nothing
#
# Anything after the flags is forwarded to each per-case pytest invocation, e.g.
#   scripts/watch_nav_evals.sh --only lamppost -- -vv
#
# The full pass is long: ~10 live cases, each up to the 270 s case deadline.
# Use --only while watching a specific behaviour.
#
# Env:
#   MUJOCO_GL  defaults to glfw here (a real window). Override with
#              MUJOCO_GL=egl for a headless smoke run.
#   DISPLAY    must point at an X/Wayland display for glfw. A missing DISPLAY
#              is reported here rather than as a MuJoCo crash 20 s later.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PARCEL_PYTHON:-$REPO/.parcel/bin/python}"

export MUJOCO_GL="${MUJOCO_GL:-glfw}"

if [[ "$MUJOCO_GL" == "glfw" && -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo "watch_nav_evals: MUJOCO_GL=glfw needs a display; DISPLAY and WAYLAND_DISPLAY are both unset." >&2
  echo "                 Set DISPLAY=:0 (or run with MUJOCO_GL=egl for a headless pass)." >&2
  exit 2
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "watch_nav_evals: interpreter not found: $PYTHON" >&2
  exit 2
fi

exec "$PYTHON" "$REPO/scripts/watch_nav_evals.py" --python "$PYTHON" "$@"
