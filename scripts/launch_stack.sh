#!/usr/bin/env bash
# Orchestrate local model services, MuJoCo, and the Parcel browser panel.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.parcel/bin/python"

# Card R27 — THE OWNER DECLARATION, and the only place in the tree that makes it.
#
# `memory.path` in robot.yaml is relative, and sqlite resolves a relative path
# against the process CWD, so for years "the shipped config" meant "the owner's
# real conversation memory" for anything started from the repo root — tests and
# in-process runtimes included. 256 synthetic rows are the measured cost.
#
# src/parcel_robot/memory_path.py now REFUSES that file to any process that has
# not declared itself the owner's stack. This line is that declaration. It lives
# in the launcher and not in the library on purpose: an executor who imports the
# runtime cannot accidentally acquire it, which is the entire mechanism. Under
# pytest it is ignored outright.
#
# Already-set values are respected so PARCEL_MEMORY_PATH=/tmp/... still isolates
# a live proof launched through this script.
export PARCEL_MEMORY_PURPOSE="${PARCEL_MEMORY_PURPOSE:-owner}"

usage() {
  cat <<'EOF'
Usage: scripts/launch_stack.sh [stack options] [launch_sim options]

Default: the hosted GPT Realtime lane, Gemma reasoning, MuJoCo + the panel.

The hosted Realtime lane is the PRODUCTION path and is ON by default (owner
directive, 2026-08-18). A bare `scripts/launch_stack.sh` loads
~/.config/parcel/realtime.env and requires the lane; if the credential or the
config file is missing it refuses loudly and starts nothing. That refusal is
the contract: a stack that comes up silently on the legacy voice path looks
identical in the panel and is only discovered one typed sentence later.

Stack options:
  --prototype        Shorthand for --profile prototype (card P0-A). Deep-merges
                     configs/robot.prototype.yaml over configs/robot.yaml and
                     prefers configs/realtime.prototype.yaml for the hosted
                     lane. Changes nothing when the flag is absent.
  --profile NAME     Select the config profile configs/robot.NAME.yaml. Exported
                     as PARCEL_PROFILE, so the panel and the simulator resolve
                     the same overlay without either learning a new flag.
  --dry-run          Print the resolved profile, overlay and realtime config,
                     then exit 0 without starting or contacting anything.
  --fish             Also start/reuse Fish Audio S2 Pro on port 8091
  --whisper          Also start/reuse whisper.cpp ASR on port 8178
  --no-reasoner      Do not start Gemma. The hosted lane remains active unless
                     combined with --legacy for deterministic panel commands.
  --legacy           E2E TESTING ONLY. Disable the hosted lane and come up on
                     the local legacy voice path. Prints a banner; never the
                     default, never silent.
  --realtime         Accepted and ignored: the hosted lane is already the
                     default. Kept so existing muscle memory keeps working.
  -h, --help         Show this help

All other options are forwarded to scripts/launch_sim.sh, for example:
  scripts/launch_stack.sh --no-browser
  scripts/launch_stack.sh --fish --socket /tmp/parcel_demo.sock --port 9000

Environment equivalents:
  PARCEL_ENABLE_REASONER=0|1 (default 1)
  PARCEL_ENABLE_FISH=0|1     (default 0; opt-in for GPU/license reasons)
  PARCEL_ENABLE_WHISPER=0|1  (default 0; useful after an audio endpoint exists)
  PARCEL_ENABLE_REALTIME=0|1 (default 1 — the prod path; the hosted lane costs
                             real money, and that is the accepted cost of the
                             production path being the one that is tested)
  PARCEL_REALTIME_ENV=<path> (default ~/.config/parcel/realtime.env, mode 600)
  PARCEL_REALTIME_CONFIG=<path> (the lane's YAML; usually set by realtime.env.
                             A selected profile's configs/realtime.<profile>.yaml
                             wins over this when it exists, and says so.)
  PARCEL_PROFILE=<name>      (default unset = the shipped configuration; same
                             effect as --profile <name>)

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

# Card P0-A. Which YAML the hosted lane gets, and WHY, as one decision made in
# one place so the dry-run and the real launch can never disagree about it.
#
# A selected profile's file wins over PARCEL_REALTIME_CONFIG deliberately:
# realtime.env sets that variable on almost every host, so an env-first rule
# would mean `--prototype` silently launched the production voice lane while
# the panel showed the prototype robot. Absent, it falls back exactly as before
# and prints the note the card asks for.
REALTIME_YAML=""
REALTIME_YAML_SOURCE=""
select_realtime_yaml() {
  local profile_yaml=""
  [[ -n "$PROFILE" ]] && profile_yaml="$ROOT/configs/realtime.$PROFILE.yaml"
  if [[ -n "$profile_yaml" && -f "$profile_yaml" ]]; then
    REALTIME_YAML="$profile_yaml"
    REALTIME_YAML_SOURCE="profile"
  elif [[ -n "${PARCEL_REALTIME_CONFIG:-}" ]]; then
    REALTIME_YAML="$PARCEL_REALTIME_CONFIG"
    REALTIME_YAML_SOURCE="env"
  else
    REALTIME_YAML="$ROOT/configs/realtime.yaml"
    REALTIME_YAML_SOURCE="default"
  fi
  if [[ -n "$profile_yaml" && ! -f "$profile_yaml" ]]; then
    echo "Note: $profile_yaml is absent, so the hosted lane falls back to $REALTIME_YAML."
    echo "      For the $PROFILE voice lane: cp $ROOT/configs/realtime.$PROFILE.yaml.example $profile_yaml"
  fi
}

ENABLE_REASONER="${PARCEL_ENABLE_REASONER:-1}"
ENABLE_FISH="${PARCEL_ENABLE_FISH:-0}"
ENABLE_WHISPER="${PARCEL_ENABLE_WHISPER:-0}"
# The hosted GPT Realtime lane is the production path (owner directive,
# 2026-08-18). Default 1: a bare launch is a REAL launch, and a machine without
# the credential/config refuses instead of quietly falling back to the legacy
# voice path. Only --legacy (or PARCEL_ENABLE_REALTIME=0) turns it off, and
# both say so out loud.
ENABLE_REALTIME="${PARCEL_ENABLE_REALTIME:-1}"
REALTIME_ENV="${PARCEL_REALTIME_ENV:-$HOME/.config/parcel/realtime.env}"
LEGACY_REQUESTED=0
SIM_ARGS=()
PANEL_LLM_ARG=0
# Card P0-A. Empty = the shipped configuration and today's behaviour exactly.
PROFILE="${PARCEL_PROFILE:-}"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fish) ENABLE_FISH=1; shift ;;
    --whisper) ENABLE_WHISPER=1; shift ;;
    --no-reasoner) ENABLE_REASONER=0; shift ;;
    # Accepted no-op: the hosted lane is already the default. Kept so that
    # every note, doc and habit that says `--realtime` keeps working.
    --realtime) ENABLE_REALTIME=1; shift ;;
    --legacy) ENABLE_REALTIME=0; LEGACY_REQUESTED=1; shift ;;
    --prototype) PROFILE="prototype"; shift ;;
    --profile)
      [[ $# -ge 2 && -n "${2:-}" ]] || die "--profile requires a value"
      PROFILE="$2"
      shift 2
      ;;
    --profile=*) PROFILE="${1#*=}"; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
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

# Card P0-A — resolve the profile BEFORE anything starts, and export it so the
# panel and the simulator (which launch_sim.sh starts as separate processes,
# neither of which parses this script's flags) read the same overlay. A named
# profile with no file is a typo at the command line: refuse by name rather
# than start the shipped configuration and let it look like it worked.
ROBOT_OVERLAY=""
if [[ -n "$PROFILE" ]]; then
  [[ "$PROFILE" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die \
    "invalid --profile value: $PROFILE (it names configs/robot.<profile>.yaml, not a path)"
  ROBOT_OVERLAY="$ROOT/configs/robot.$PROFILE.yaml"
  [[ -f "$ROBOT_OVERLAY" ]] || die \
    "--profile $PROFILE selected but $ROBOT_OVERLAY does not exist"
  export PARCEL_PROFILE="$PROFILE"
  echo "Config profile: $PROFILE ($ROBOT_OVERLAY deep-merged over configs/robot.yaml)"
fi

if (( DRY_RUN )); then
  select_realtime_yaml
  echo "profile=${PROFILE:--}"
  echo "robot_config=$ROOT/configs/robot.yaml"
  echo "robot_overlay=${ROBOT_OVERLAY:--}"
  echo "realtime_config=$REALTIME_YAML"
  echo "realtime_config_source=$REALTIME_YAML_SOURCE"
  echo "realtime_enabled=$ENABLE_REALTIME"
  echo "dry run: nothing started, no credential read"
  exit 0
fi

# The hosted lane: fail LOUDLY and before anything else starts. A stack that
# comes up with a silently disabled lane is the worst outcome here, because the
# panel looks identical and the owner discovers it one typed sentence later.
if is_true "$ENABLE_REALTIME"; then
  KEY_ENV="${PARCEL_REALTIME_KEY_ENV:-OPENAI_API_KEY}"
  if [[ -f "$REALTIME_ENV" ]]; then
    echo "Loading realtime credential from $REALTIME_ENV (value never printed)"
    set -a
    # shellcheck disable=SC1090
    . "$REALTIME_ENV"
    set +a
  fi
  if [[ -z "${!KEY_ENV:-}" ]]; then
    die "the hosted Realtime lane is the production path and it needs a credential:
       \$$KEY_ENV is unset and $REALTIME_ENV does not define it.
       Put the key in that file (mode 600, outside the repo):
         install -m 600 /dev/null $REALTIME_ENV
         printf '%s=sk-...\\n' "$KEY_ENV" > $REALTIME_ENV
       For local e2e testing of the legacy voice path only: scripts/launch_stack.sh --legacy"
  fi
  select_realtime_yaml
  if [[ ! -f "$REALTIME_YAML" ]]; then
    die "the hosted Realtime lane is the production path and it needs $REALTIME_YAML,
       which is absent (the repo deliberately ships no configs/realtime.yaml).
       Copy the documented example and edit it, or point PARCEL_REALTIME_CONFIG
       at your own copy outside the repo (realtime.env usually does this):
         cp $ROOT/configs/realtime.yaml.example $REALTIME_YAML
       For local e2e testing of the legacy voice path only: scripts/launch_stack.sh --legacy"
  fi
  if ! grep -Eq '^[[:space:]]*enabled:[[:space:]]*true[[:space:]]*$' "$REALTIME_YAML"; then
    die "$REALTIME_YAML does not set 'enabled: true', so the hosted lane would never
       be constructed. Set it, or launch the legacy path deliberately with --legacy."
  fi
  # The launcher validated THIS file; hand the runtime the same one rather than
  # letting it re-resolve and possibly pick a different path.
  export PARCEL_REALTIME_CONFIG="$REALTIME_YAML"
  echo "Realtime lane: enabled (production path), config $REALTIME_YAML, credential \$$KEY_ENV present"
else
  # Never silent. The legacy voice path is the E2E TEST baseline, not a product
  # configuration, and a stack running on it must say so unmissably.
  echo "=============================================================================="
  echo "  LEGACY VOICE PATH — E2E TESTING ONLY"
  echo ""
  echo "  The hosted GPT Realtime lane is DISABLED for this launch, so typed and"
  echo "  spoken turns go to the local legacy voice agent. That path exists to keep"
  echo "  the e2e suites honest; it is NOT the production path and its behavior is"
  echo "  not what the owner is testing when they talk to the dog."
  if (( LEGACY_REQUESTED )); then
    echo ""
    echo "  Reason: --legacy was passed."
  else
    echo ""
    echo "  Reason: PARCEL_ENABLE_REALTIME=$ENABLE_REALTIME in the environment."
  fi
  echo ""
  echo "  Drop the flag (or unset PARCEL_ENABLE_REALTIME) to launch the prod path."
  echo "=============================================================================="
fi
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
