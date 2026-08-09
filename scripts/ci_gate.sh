#!/usr/bin/env bash
# Thin wrapper around scripts/ci_gate.py so CI and humans invoke one command.
#
# Why a wrapper and not nox/tox/make: this repo has no nox/tox/Makefile and its
# convention is plain scripts under scripts/ run with the in-repo venv
# (.parcel/bin/python) — see scripts/mutation_panel.py. A wrapper adds no new
# dependency, pins the interpreter, and sets the headless MuJoCo default so the
# commit tier is offline and deterministic.
#
# Usage:
#   scripts/ci_gate.sh            # commit tier (default)
#   scripts/ci_gate.sh commit
#   scripts/ci_gate.sh nightly
#   scripts/ci_gate.sh commit --json
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PY="$REPO_ROOT/.parcel/bin/python"
[ -x "$PY" ] || PY="python3"

# Headless, offline defaults. Overridable by the caller/CI.
export MUJOCO_GL="${MUJOCO_GL:-egl}"

TIER="commit"
if [ "${1:-}" = "commit" ] || [ "${1:-}" = "nightly" ]; then
  TIER="$1"
  shift
fi

exec "$PY" "$REPO_ROOT/scripts/ci_gate.py" --tier "$TIER" "$@"
