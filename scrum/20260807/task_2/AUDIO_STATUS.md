# Acoustic bring-up — lane status

**Date:** 2026-08-07 · **Lane:** audio / speech seams · **Plan:**
[../../../docs/ACOUSTIC_BRINGUP_PLAN.md](../../../docs/ACOUSTIC_BRINGUP_PLAN.md)

Parcel went from "cannot open an audio device" to "measures its own audio" in
one pass, without root and without touching a single file outside this lane's
ownership. It still has not made a sound in a room — that is owner-gated and
labelled as such everywhere.

---

## Cards landed — gate met on this machine

| card | gate | evidence |
|---|---|---|
| `env-audio-portaudio-prefix` | sounddevice enumerates from the venv | 12 devices, ALSA+PulseAudio, PortAudio V19.7.0-devel rev e1b70d33; 16 k input + 22050 output streams both open |
| `speech-services-nocompile` | `run_speech_services.sh --check` exits 0 | whisper `/health` OK, piper 22050 Hz OK, piper emits 2.046 s / rms 4475.5 of PCM |
| `semantic-endpointing-models` | real Silero + Smart Turn, no degrade | `TurnEndpointer.detail()` = `smart-turn-v3`, p_complete 0.8817, suite green |
| `acoustic-loop-v1-rig` | deterministic double run, zero orphans | **three** runs, identical `case_verdicts` and gate statuses each time, `teardown_clean: true`, 25 cases, no root, no hardware |
| `endpointing-acoustic-eval` | gates as written | ep-cutoff **0.00 pass**; ep50 0.792 **FAIL**; ep90 0.840 **pass** |
| `bargein-teardown-eval` | gates as written | detection 0.128 **pass**; flush 71 µs **pass**; acoustic stop 0.720 **FAIL**; false rate 1.00 **FAIL** |
| `duplex-acoustic-eval` | acoustic ack p50 ≤ 0.7 s | 0.800 **FAIL** — and the enqueue/audible gap measured at 0.54–0.64 s |
| `prosody-nod-sync-eval` | ≥ 80 % apexes within ±150 ms | 64.3 % **FAIL**; median signed lag 0.04 s, \|lag\| p95 0.47 s |
| `aec-l1-inprocess` | ≥ 15 dB synthetic ERLE, flag-off identical | **35.3 dB**; near-end preserved 54× over echo residual; 25/25 tests |
| `ducking-l2` | gain change within one ~50 ms block | per-block gain read, confirm/restore counters, interrupt latch untouched |

## Card partially landed

**`ledger-acoustic-clocks`** — the three measurement surfaces landed in files
this lane owns (`WhisperCppProvider.last_metrics`,
`MicrophoneVoiceLoop.last_turn_clocks`,
`SpeakerSink.first_chunk_started_monotonic`). The fan-in did not: every ledger
write goes through `RobotRuntime._voice_stage` and `STAGES` in
`observability.py` is a closed vocabulary whose `mark()` raises on unknown
names — **both files are on this lane's do-not-touch list.** The exact
five-step diff is written up in the plan §3 and filed as backlog N19. Its own
gate ("`/latency` shows the new stages on a real mic turn") is in any case
unreachable here: there is no mic.

## Cards PREPARED — written, not run, not claimed

`device-activation-snapshot`, `acoustic-hello-smoke`, `aec-l0-pipewire` (full
`99-parcel-aec.conf` drafted with the `target.object` placeholder that must
come from the owner's snapshot), `doubletalk-operating-curve` (Tier-2),
`stt-upgrade-faster-whisper` (documented conditional, **not installed**),
`xvf3800-integration` (owner-gated). Runbook: plan §5.

`scripts/acoustic_smoke.sh` is not merely syntax-checked — it was executed to
its owner-gated boundary and behaved exactly as designed:

```
run_speech_services: CHECK PASSED — stt=whisper.cpp, tts=piper
acoustic_smoke: enumerating devices and measuring capture level
  12 device(s) ... * 7 default  in=128 out=128 ALSA
  speak now - measuring capture for 3s ...
  capture RMS 0.0  peak 0
  GATE FAILED: capture is digital silence.
  Nothing is plugged into the analog jacks, or the card profile is Off.
  See the OWNER RUNBOOK in docs/ACOUSTIC_BRINGUP_PLAN.md (step S0).
=== RC=3 ===
```

Everything up to the transducer works. The transducer is the gate.

---

## First-ever acoustic-tier numbers

Two runs, `evals/companion/acoustic_loop_v1/results/`. Virtual PipeWire rig:
Tier-1 evidence.

```
endpointing_ep_cutoff_rate         0.0      <= 0.05    pass
endpointing_ep50_s                 0.792    <= 0.5     FAIL
endpointing_ep90_s                 0.8404   <= 1.0     pass
bargein_detection_p50_s            0.1284   <= 0.4     pass
bargein_flush_max_s                0.0001   <= 0.06    pass
bargein_acoustic_stop_p50_s        0.72     <= 0.52    FAIL
bargein_false_rate                 1.0      <= 0.02    FAIL
duplex_acoustic_ack_p50_s          0.8      <= 0.7     FAIL
prosody_apex_within_window_rate    0.6429   >= 0.8     FAIL
```

**Five gates failed and none was tuned.** No threshold moved; no code changed
to make a number go green after seeing it. Two are genuine product defects the
software tier structurally could not find, and both are now backlog items:

- **N16 — post-interrupt drain.** `duplex_v1` correctly asserts no chunk-token
  leakage. True, and the audio keeps playing anyway: `interrupt()` stops
  *writing* but PortAudio's already-buffered samples still present. ~0.6 s of
  the robot talking over the owner after it decided to stop.
- **N17 — echo guard fragments the neural VAD.** The guard runs before Silero
  and `return`s on suppressed frames, so Silero sees loud fragments with
  artificial onsets instead of a continuous stream. Silero itself rejects the
  noise cleanly when probed directly (max p 0.21 vs threshold 0.5).

The headline measurement: **the software ledger's enqueue-time
`audio_first_playback` understates the acoustic ack by 0.54–0.64 s** — as
large as the whole 0.7 s filler budget. `docs/AUDIO_LATENCY_AND_SPATIAL_
INTELLIGENCE.md` already warned the dashboard could not support a sub-700 ms
claim; this is the first number on how big the gap is.

---

## What must NOT be claimed from this work

Stated in every report's `does_not_prove`, and repeated here:

- **No room acoustics.** No air, no reverberation, no room.
- **No real transducer.** Both rig endpoints are null sinks. Every physical
  capture on this machine still reads **RMS 0.00**.
- **No AEC evaluation of any kind.** There is no acoustic coupling to cancel.
  The 35.3 dB ERLE is against *synthetic* echo in a unit test — it says the
  filter works, not that the robot can be interrupted in a room.
- **Not human speech.** The corpus is Piper-synthesized.
- **Not end-to-end product latency.** The duplex family uses a scripted
  responder deliberately, so the number is about audio and not about Gemma.
- **Sink presentation latency on a null sink is not a sound card's.** What is
  established is that the enqueue/audible gap is not negligible and must be
  measured, never assumed.

---

## Test suite

Full default suite:

```
3 failed, 2774 passed, 14 skipped, 3 xfailed, 5 warnings in 893.16s (0:14:53)
```

Targeted sweep over every test file importing the modules this lane touched
(`voice_audio`, `providers`, `prosody`, `duplex`, `speech` — 33 files):

```
3 failed, 566 passed, 6 skipped in 13.67s
```

The same three failures, all `tests/test_duplex_v1.py`, and they are **not
from this lane**. Diagnosed to the sub-check:

```
follow_bench_unchanged: false      <- the failing one
embodied_unchanged:     true
embodied freeze agrees: True
```

`run_duplex_v1.py`'s nav-regression gate pins `follow_success: 8/9` from
`follow-bench-v1-20260804104134Z-d1adc373.json`. The navigation lane, running
concurrently in this same working tree, has just produced
`follow-bench-v1-20260808005037Z-c3b3b2e7.json` reporting **9/9** — an
improvement that correctly trips their own pin until they re-freeze it. Three
concurrent full-suite runs were observed in flight during this work.

Nothing in that gate path touches audio: `tests/test_duplex_v1.py` contains
zero references to `voice_audio`, `WhisperCppProvider`, `AecStage` or
anything acoustic. The audio-owned files are green — `tests/test_voice_audio.py`,
`tests/test_voice_aec_ducking.py` (29 new), `tests/test_endpointing.py` and
`tests/test_voice_streaming.py` all pass.

**Ruff: clean** across `scripts/`, `evals/companion/acoustic_loop_v1/`,
`voice_audio.py`, `providers.py` and the new test file. (The repo carries ~61
pre-existing ruff findings elsewhere under ruff 0.16.1's default rules; this
lane added none and left those alone.)

---

## Defect caught in this lane's own work

`env_audio_install` is invoked as `env_audio_install || return 1`, and bash
disables `set -e` for the entire left-hand side of `||`. A failed `mkdir` /
`cd` therefore went unnoticed and `apt-get download` ran in the **caller's**
working directory — observed dropping two `.debs` into the repo root when the
prefix path was unwritable. Fixed with explicit `|| exit 1` guards inside the
subshell and an explicit `mkdir` check; both paths retested:

```
env-audio: ERROR: cannot create the prefix directory /proc/definitely-not-writable
env-audio: WARNING: audio prefix unavailable; speech will degrade to text
rc=0                       <- still non-fatal, degrade contract preserved
no strays: fixed           <- CWD is clean
env-audio: CHECK PASSED    <- happy path unaffected
```

---

## Corrections to the research synthesis

- **`pywebrtc-audio` is not installable here.** The synthesis called it a
  "prebuilt py3.14 x86_64 wheel". PyPI serves `0.0.1` as a 1.2 kB placeholder
  with an empty `__init__.py`, and `0.1.0` is source-only and fails at
  `CMakeDetermineCCompiler` — no C compiler on this host. The L1 rung shipped
  as a real numpy NLMS canceller behind the same seam instead of a stub.
- **`configs/robot.yaml` could not be edited.** It is hash-locked by
  `embodied_plan_v1`'s manifest (`f6468887…726c`) and the runner hard-fails on
  drift. Parcel has no overlay mechanism, so acoustic settings went into a
  *derived* `configs/robot.acoustic.yaml` regenerated by
  `scripts/make_acoustic_config.py`. `robot.yaml`'s sha is unchanged.
- **`endpointing: semantic` needed no code change** — `vad_model` /
  `turn_model` were already in `providers.py`'s allowlist.
- Enumeration showed hostapis **ALSA + PulseAudio** (not ALSA/OSS/PulseAudio).

---

## Files touched

**New:** `scripts/env-audio.sh`, `scripts/acoustic_smoke.sh`,
`scripts/build_acoustic_corpus.py`, `scripts/make_acoustic_config.py`,
`configs/robot.acoustic.yaml` (derived), `evals/companion/acoustic_loop_v1/**`
(runner, rig, manifest, schema, README, 22 fixtures + corpus.json, 2 results),
`tests/test_voice_aec_ducking.py`, `docs/ACOUSTIC_BRINGUP_PLAN.md`, this file.

**Modified:** `scripts/install_speech_services.sh` (`--piper-only`),
`scripts/launch_sim.sh` (source `env-audio.sh`, never fatally),
`src/parcel_robot/voice_audio.py` (`AecStage`, ducking, capture + speaker
clocks), `src/parcel_robot/providers.py` (`WhisperCppProvider.last_metrics`),
`backlog/NEXT.md` (N16–N19), `backlog/BLOCKED.md` (B1 demoted, B2 landed, B3
now the only real audio blocker).

**Downloaded (gitignored):** `third_party/piper/`, `models/piper/`,
`models/endpointing/` (both ONNX models, shas recorded), `onnxruntime` 1.28.0.

**Not touched:** `runtime.py`, `observability.py`, `navigation/**`,
`instructnav/**`, `brain/**`, `core/**`, `evals/nav_instruct/**`,
`test_voice_nav_e2e.py`, `authority`/`pose`, and `configs/robot.yaml`.
