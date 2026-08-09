#!/usr/bin/env bash
# First acoustic turn: speak to Parcel, hear it answer.
#
# STATUS: PREPARED, NOT YET EXECUTED. This script is complete and syntax
# checked, but it has never completed its gate on this machine because no
# transducer has ever been attached — every capture reads RMS 0.00 and the
# HD-Audio analog card sits at profile "Off" with the default source routed to
# auto_null. Running it is step S4 of docs/ACOUSTIC_BRINGUP_PLAN.md and it
# requires the owner to have completed S0 (device activation) first.
#
# WHAT IT DOES
#   1. Sources scripts/env-audio.sh          (user-space PortAudio, no root)
#   2. Verifies whisper + piper               (run_speech_services.sh --check)
#   3. Reports what PortAudio can see and measures the capture RMS
#   4. Plays one fixed Piper utterance through the configured output
#   5. Hands off to scripts/launch_sim.sh for the live mic->STT->LLM->TTS turn
#
# SPEECH MODE
#   Launches with the shipped speech.mode: auto. Audio that cannot come up
#   degrades loudly to text mode, which is the behaviour we want to keep: a
#   half-up audio stack is worse than no audio stack. Pass --fail-closed to
#   use speech.mode: audio instead, which refuses to start without both
#   speech roles - useful precisely once, to prove audio really is live.
#
# GATE (all four, none of which have been met yet)
#   - audible TTS through the real sink
#   - capture RMS > 0 from the default source while speaking
#   - one completed acoustic turn
#   - a latency-ledger row recorded for that turn

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PARCEL_PYTHON:-$ROOT/.parcel/bin/python}"
CONFIG="${PARCEL_ACOUSTIC_CONFIG:-$ROOT/configs/robot.acoustic.yaml}"
FAIL_CLOSED=0
CAPTURE_SECONDS="${PARCEL_SMOKE_CAPTURE_S:-3}"
LAUNCH=1

log() { echo "acoustic_smoke: $*"; }
die() {
  echo "acoustic_smoke: ERROR: $*" >&2
  exit 1
}

usage() {
  sed -n '2,32p' "${BASH_SOURCE[0]}"
  cat <<EOF

Options:
  -h, --help         Show this help and exit
      --fail-closed  Launch with speech.mode: audio instead of auto
      --no-launch    Run the checks and the playback probe, then stop
EOF
}

while (($#)); do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --fail-closed) FAIL_CLOSED=1 ;;
    --no-launch) LAUNCH=0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
  shift
done

[[ -x "$PYTHON" ]] || die "missing $PYTHON"

# --- 1. user-space PortAudio ------------------------------------------------
log "activating the user-space PortAudio prefix"
# shellcheck source=scripts/env-audio.sh
source "$ROOT/scripts/env-audio.sh"

# --- 2. speech services -----------------------------------------------------
log "verifying speech services"
"$ROOT/scripts/run_speech_services.sh" --check \
  || die "speech services are not ready; run scripts/run_speech_services.sh first"

# --- 3. what can PortAudio see, and is anything actually connected? ---------
log "enumerating devices and measuring capture level"
"$PYTHON" - "$CAPTURE_SECONDS" <<'PY'
import sys

import numpy as np
import sounddevice as sd

seconds = float(sys.argv[1])
devices = sd.query_devices()
print(f"  {len(devices)} device(s):")
for index, device in enumerate(devices):
    api = sd.query_hostapis(device["hostapi"])["name"]
    marker = "*" if index in tuple(sd.default.device) else " "
    print(
        f"   {marker}{index:2d} {device['name'][:44]:44s} "
        f"in={device['max_input_channels']:3d} out={device['max_output_channels']:3d} {api}"
    )
print(f"  default input/output: {sd.default.device}")

print(f"  speak now - measuring capture for {seconds:.0f}s ...")
recording = sd.rec(int(seconds * 16000), samplerate=16000, channels=1, dtype="int16")
sd.wait()
rms = float(np.sqrt(np.mean(np.square(recording.astype(np.float64)))))
peak = int(np.abs(recording).max())
print(f"  capture RMS {rms:.1f}  peak {peak}")
if rms <= 0.0:
    print(
        "  GATE FAILED: capture is digital silence.\n"
        "  Nothing is plugged into the analog jacks, or the card profile is Off.\n"
        "  See the OWNER RUNBOOK in docs/ACOUSTIC_BRINGUP_PLAN.md (step S0).",
        file=sys.stderr,
    )
    raise SystemExit(3)
PY

# --- 4. one fixed Piper utterance through the real sink ---------------------
log "playing one Piper utterance through the configured output device"
PIPER_BIN="$ROOT/third_party/piper/piper"
PIPER_VOICE="$ROOT/models/piper/voice.onnx"
echo "Hello. Parcel can hear you, and you can hear Parcel." \
  | "$PIPER_BIN" --model "$PIPER_VOICE" --output-raw 2>/dev/null \
  | "$PYTHON" - <<'PY'
import sys

import numpy as np
import sounddevice as sd

pcm = np.frombuffer(sys.stdin.buffer.read(), dtype=np.int16)
if pcm.size == 0:
    print("  GATE FAILED: piper produced no audio", file=sys.stderr)
    raise SystemExit(4)
rate = 22050  # models/piper/voice.onnx.json audio.sample_rate
print(f"  playing {pcm.size / rate:.2f}s at {rate} Hz")
sd.play(pcm, samplerate=rate)
sd.wait()
print("  playback returned - you should have HEARD that")
PY

if ((LAUNCH == 0)); then
  log "--no-launch: stopping before the live turn"
  exit 0
fi

# --- 5. the live turn -------------------------------------------------------
[[ -f "$CONFIG" ]] || die \
  "missing $CONFIG - generate it with: $PYTHON scripts/make_acoustic_config.py"
"$PYTHON" "$ROOT/scripts/make_acoustic_config.py" --check \
  || die "$CONFIG is stale; regenerate it with scripts/make_acoustic_config.py"

if ((FAIL_CLOSED == 1)); then
  log "launching with speech.mode: audio (fail-closed)"
  CONFIG_TO_USE="$(mktemp /tmp/parcel-acoustic-failclosed.XXXXXX.yaml)"
  "$PYTHON" - "$CONFIG" "$CONFIG_TO_USE" <<'PY'
import sys

import yaml

source, target = sys.argv[1], sys.argv[2]
data = yaml.safe_load(open(source, encoding="utf-8"))
data["speech"]["mode"] = "audio"
with open(target, "w", encoding="utf-8") as handle:
    yaml.safe_dump(data, handle, sort_keys=False)
PY
else
  log "launching with speech.mode: auto (degrades loudly to text)"
  CONFIG_TO_USE="$CONFIG"
fi

log "speak a turn; you should hear the reply"
log "afterwards, check /latency for the turn's ledger row"
exec "$ROOT/scripts/launch_sim.sh" --config "$CONFIG_TO_USE" --llm
