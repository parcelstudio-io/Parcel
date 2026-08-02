#!/usr/bin/env bash
# Launch parcel-sim and the button control panel together.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .parcel/bin/activate ]]; then
  echo "Missing .parcel venv. Create it with: python3 -m venv .parcel && source .parcel/bin/activate && pip install -e '.[dev]'"
  exit 1
fi

# shellcheck source=/dev/null
source .parcel/bin/activate

if ! command -v parcel-sim >/dev/null || ! command -v parcel-control >/dev/null; then
  echo "Installing parcel entry points..."
  pip install -e . -q
fi

SOCKET="${PARCEL_SIM_SOCKET:-/tmp/parcel_sim.sock}"
rm -f "$SOCKET"

SIM_PID=""

cleanup() {
  if [[ -n "$SIM_PID" ]] && kill -0 "$SIM_PID" 2>/dev/null; then
    kill "$SIM_PID" 2>/dev/null || true
    wait "$SIM_PID" 2>/dev/null || true
  fi
  rm -f "$SOCKET"
}

trap cleanup EXIT INT TERM

echo "Starting parcel-sim..."
parcel-sim --socket "$SOCKET" &
SIM_PID=$!

# Wait until the sim socket is ready (or the sim process exits).
for _ in $(seq 1 100); do
  if [[ -S "$SOCKET" ]]; then
    break
  fi
  if ! kill -0 "$SIM_PID" 2>/dev/null; then
    echo "parcel-sim exited before becoming ready."
    exit 1
  fi
  sleep 0.05
done

if [[ ! -S "$SOCKET" ]]; then
  echo "Timed out waiting for $SOCKET"
  exit 1
fi

echo "Starting parcel-control..."
echo "Close the control window or press Ctrl+C to stop both."
if ! python -c "import tkinter" >/dev/null 2>&1; then
  echo "tkinter missing — using CLI controls (sudo apt install python3-tk for GUI)."
  parcel-control --socket "$SOCKET" --cli
else
  parcel-control --socket "$SOCKET"
fi
