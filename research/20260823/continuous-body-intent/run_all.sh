#!/usr/bin/env bash
# Everything H4 measured, in order, against a PRIVATE simulator.
# The owner's stack on /tmp/parcel_sim.sock and :8765 is never touched.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
PY="$REPO/.parcel/bin/python"
SOCK="$HERE/h4_sim.sock"
cd "$REPO"

# 1. private simulator (own socket, static city so the scene is reproducible)
rm -f "$SOCK"
nohup "$PY" -m parcel_robot.sim --socket "$SOCK" --static-city \
  > "$HERE/logs/sim.log" 2>&1 &
SIM_PID=$!
trap 'kill "$SIM_PID" 2>/dev/null || true; rm -f "$SOCK"' EXIT
sleep 20

# 2. the four pre-registered states, 10 minutes each (rows B1-B7)
"$HERE/run_states.sh" "$SOCK" 600

# 3. loop cost, three arms, 5 minutes each + microbenchmark (row B9)
cd "$HERE"
"$PY" loop_cost.py --seconds 300 --socket "$SOCK" --out "$HERE/results/loop_cost.json"

# 4. offline probes: jitter-free limiter (B3), COM (B5), portability (B8)
"$PY" limiter_bench.py --seconds 600 --out "$HERE/results/limiter_bench.json"
cd "$REPO" && "$PY" "$HERE/com_probe.py" --trace "$HERE/results/trace_idle_hold.json" \
  --out "$HERE/results/com_probe.json"
cd "$HERE" && "$PY" portability_audit.py --out "$HERE/results/portability_audit.json"

# 5. the pre-registered table
"$PY" summarize.py --results "$HERE/results" --out "$HERE/results/rows.json"
