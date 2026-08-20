#!/usr/bin/env bash
# Owner voice corpus recorder — one WAV per query, reSpeaker array, 16k mono.
# Usage: ./record.sh [start_id]   (resume from a given id after a break)
# For each query: read it, press Enter, speak it once naturally, recording
# stops after 6 seconds. Files land next to this script as NN_category.wav.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$SCRIPT_DIR"
DEV="${PARCEL_MIC_DEV:-plughw:2,0}"
PYTHON="${PARCEL_PYTHON:-$REPO_ROOT/.parcel/bin/python}"
START="${1:-1}"
command -v arecord >/dev/null || { echo "arecord missing"; exit 1; }
[ -x "$PYTHON" ] || { echo "Parcel Python missing: $PYTHON"; exit 1; }
[ -f queries.tsv ] || { echo "queries.tsv missing"; exit 1; }

tail -n +2 queries.tsv | while IFS=$'\t' read -r id category query expected; do
  [ "$((10#$id))" -lt "$START" ] && continue
  out="${id}_${category}.wav"
  echo
  echo "[$id/$(( $(wc -l < queries.tsv) - 1 ))] ($category)"
  echo "    SAY:  \"$query\""
  read -r -p "    Enter to record (6s), s+Enter to skip: " ans </dev/tty
  [ "$ans" = "s" ] && { echo "    skipped"; continue; }
  arecord -D "$DEV" -f S16_LE -r 16000 -c 1 -d 6 "$out" >/dev/null 2>&1
  peak=$("$PYTHON" -c "
import wave, array
w = wave.open('$out'); d = array.array('h'); d.frombytes(w.readframes(w.getnframes()))
print(max(abs(x) for x in d) if d else 0)")
  if [ "$peak" -lt 1500 ]; then
    echo "    ⚠ level low (peak $peak) — re-record? Run: ./record.sh $((10#$id))"
  else
    echo "    ✓ saved $out (peak $peak)"
  fi
done
echo
echo "Done. Recorded WAVs are the corpus; tell Fable and the replay harness takes it from there."
