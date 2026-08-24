#!/usr/bin/env bash
# The ONE paid entry point for H1 (DESIGN.md step 5, rows C9/C10).
#
# Loads the credential exactly the way scripts/launch_stack.sh does — the
# documented mechanism — and hands it to the harness through the environment.
# The value is never echoed, never written to a file, and never passed on a
# command line. `set +x` is unconditional so a caller's shell tracing cannot
# leak it either.
set -euo pipefail
set +x

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${PARCEL_REALTIME_ENV:-$HOME/.config/parcel/realtime.env}"

[[ -f "$ENV_FILE" ]] || {
  echo "live.sh: no credential file at $ENV_FILE" >&2
  exit 2
}

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

[[ -n "${OPENAI_API_KEY:-}" ]] || {
  echo "live.sh: OPENAI_API_KEY is not set by $ENV_FILE" >&2
  exit 2
}

export PARCEL_H1_LIVE=1
export PYTHONPATH="$ROOT/src:$ROOT:$HERE${PYTHONPATH:+:$PYTHONPATH}"
exec "$ROOT/.parcel/bin/python" "$HERE/run_live.py" "$@"
