#!/usr/bin/env bash
# Run the four pre-registered H4 states back to back against a PRIVATE sim.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
SOCK="${1:-$HERE/h4_sim.sock}"
SECONDS_PER_STATE="${2:-600}"
cd "$HERE"
for state in idle_hold idle_look navigating estop; do
  echo "=== $state $(date -Is) ==="
  "$REPO/.parcel/bin/python" harness.py \
    --state "$state" --seconds "$SECONDS_PER_STATE" \
    --socket "$SOCK" --out "$HERE/results" > "$HERE/logs/state_$state.log" 2>&1 \
    && echo "--- done $state $(date -Is) ---" \
    || echo "--- FAILED $state $(date -Is) ---"
done
echo "ALL STATES COMPLETE $(date -Is)"
