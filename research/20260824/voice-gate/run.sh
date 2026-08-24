#!/usr/bin/env bash
# VOICE-GATE v2 — the whole study, in the order it was run.
#
#   research/20260824/voice-gate/run.sh /path/to/scratch
#
# Every step is $0 hosted. The only hardware step is the ambient tape and the
# speaker probe; both need `source scripts/env-audio.sh` for PortAudio and both
# hold the XVF3800 exclusively, so nothing else may touch the array while they
# run.
set -Eeuo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FOLDER="$REPO/research/20260824/voice-gate"
SCRATCH="${1:?usage: run.sh <scratch-dir>}"
PY="$REPO/.parcel/bin/python"
export PYTHONPATH="$REPO/src"
mkdir -p "$SCRATCH" "$FOLDER/logs"

run() { echo "=== $*"; ( cd "$FOLDER" && env -u TMPDIR "$PY" -u -m "$@" ); }

# 0. the local ASR the STOP matcher and the wake arm speak to (private port)
#    LD_LIBRARY_PATH=third_party/whisper.cpp-bin/whisper-bin-ubuntu-x64 \
#      third_party/whisper.cpp-bin/whisper-bin-ubuntu-x64/whisper-server \
#      -m models/whisper/ggml-base.en.bin -t 8 --host 127.0.0.1 --port 8099
# 1. the real room, through the real array (2 h; needs env-audio.sh)
#    "$PY" "$FOLDER/harness/record_ambient.py" "$SCRATCH/ambient_tape.raw" \
#      --seconds 7200 --device 4
run harness.corpus --out "$SCRATCH/stimuli" --manifest "$FOLDER/results/corpus_manifest.json"
run harness.run_identity --scratch "$SCRATCH" --tape "$SCRATCH/ambient_tape.raw"
run harness.run_identity_roc --scratch "$SCRATCH" --tape "$SCRATCH/ambient_tape.raw"
run harness.run_arms --scratch "$SCRATCH" --tape "$SCRATCH/ambient_tape.raw"
run harness.run_stop --tape "$SCRATCH/ambient_tape.raw"
run harness.run_content --tape "$SCRATCH/ambient_tape.raw"
run harness.run_ambient --scratch "$SCRATCH" --tape "$SCRATCH/ambient_tape.raw"
# The speaker probe holds the array exclusively, so it is deliberately last.
# It needs `source scripts/env-audio.sh` in the calling shell:
#   run harness.speaker_path --device 4 --transcribe \
#     --tts-wav "$SCRATCH"/stimuli/self_tts_*.wav \
#     --out "$FOLDER/results/speaker_path.json"
run harness.summarize
