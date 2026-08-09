# ACOUSTIC_LOOP_V1 — Tier-1 acoustic evaluation

The first Parcel eval that measures **audio**, not decisions about audio.

`duplex_v1` asserts at the session API: it knows when a chunk was *enqueued*.
This suite asserts at the audio boundary: every timestamp is read off a
null-sink monitor recording, so it knows when sound actually started and
stopped. The gap between those two things is not academic — the first
baseline measured it at **0.54–0.64 s**, and that gap sits entirely inside
the 0.7 s ack budget.

Run it:

```
source scripts/env-audio.sh
.parcel/bin/python -m evals.companion.acoustic_loop_v1.run_acoustic_loop_v1
.parcel/bin/python -m evals.companion.acoustic_loop_v1.run_acoustic_loop_v1 \
    --families endpointing,bargein
```

No root, no physical audio hardware, no sound card. It runs in CI.

### Prerequisites on a fresh checkout

The fixtures are committed; the *models* are not (`models/` and
`third_party/` are gitignored) even though `manifest.json` pins their shas. A
clean checkout therefore needs, once:

```
.parcel/bin/pip install onnxruntime
scripts/install_speech_services.sh --piper-only     # piper binary + voice
mkdir -p models/endpointing && cd models/endpointing
wget -O silero_vad_v6.onnx https://github.com/snakers4/silero-vad/raw/v6.2/src/silero_vad/data/silero_vad.onnx
wget -O smart_turn_v3.onnx https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/smart-turn-v3.2-cpu.onnx
```

A missing pinned file fails loudly (`locked file missing: …`) before anything
is measured, and a *changed* one fails just as loudly — the runner will not
measure against an edited pack. Full bring-up:
[docs/ACOUSTIC_BRINGUP_PLAN.md](../../../docs/ACOUSTIC_BRINGUP_PLAN.md).

## The rig

Two PipeWire null sinks created per run (`pw-cli create-node`, `object.linger`,
destroyed in teardown):

| node | role |
|---|---|
| `<prefix>_sink` | the robot's speaker. `SpeakerSink` opens it through the ordinary `sounddevice` path, so the real player, the real ~50 ms block loop and the real interrupt latch are exercised. Its `.monitor` is recorded. |
| `<prefix>_mic` | the owner's mouth. `pw-play` injects frozen corpus utterances; `pw-record` on its monitor feeds `MicrophoneVoiceLoop` through its `frames` iterable seam. |

`pw-link <mic> <sink>` routes everything the microphone hears into the
speaker's monitor, so **one recording contains both sides on one
sample-accurate clock**. Acoustic intervals are then a subtraction inside a
single file rather than a comparison across two processes with no shared time
base. It is not an echo path — the robot is never fed back into the mic.

Nothing in the audio code was modified to make this work. Every entry point is
a seam that already existed: `MicrophoneVoiceLoop(frames=...)`,
`resolve_audio_device`, `SpeakerSink(device=..., on_chunk_start=...)`.

## What it does NOT prove

Stated in every report as `does_not_prove`, and repeated here because an
acoustic-sounding number is the easiest thing in this repo to over-claim:

- **No room acoustics.** There is no air, no reverberation, no room.
- **No real transducer.** Both endpoints are null sinks. No microphone
  self-noise, no loudspeaker nonlinearity, no placement effects.
- **No echo, therefore no AEC evaluation is possible here at all.** There is
  no acoustic coupling to cancel. ERLE, double-talk curves and the whole
  AEC ladder are Tier-2 and are blocked on a physical transducer.
- **Not human speech.** The corpus is Piper-synthesized.
- **Not an end-to-end product latency.** The duplex family uses a scripted
  responder, deliberately: with an LLM in the loop the number would be a
  statement about Gemma, not about the audio path.

Tier 2 (`acoustic_rig_v1`, through air) and Tier 3 (owner sessions) do not
exist yet. Tier 0 (`duplex_v1`, unit fakes) remains the software-boundary
regression gate and is not replaced by anything here.

## The frozen pack

`manifest.json` pins 30 files by sha256 — every fixture, the corpus metadata,
the result schema, and the four artifacts the measurement actually depends on
(Silero VAD, Smart Turn, the Piper voice and binary, the whisper-server binary
and model). The runner verifies all of them before it measures anything and
refuses to run against an edited pack.

`fixtures/` is 22 Piper-synthesized utterances built by
`scripts/build_acoustic_corpus.py` with `--noise_scale 0 --noise_w 0`:

| kind | n | purpose |
|---|---|---|
| `complete` | 6 | turns that genuinely end |
| `incomplete` | 4 | trail off mid-clause; must NOT be cut off |
| `pause_heavy` | 3 | a real 0.75 s mid-utterance silence to ride through |
| `robot_long` | 1 | 17 s reply for barge-in |
| `interrupt` | 2 | the owner cutting in |
| `expressive` | 1 | prosody / nod-sync material |
| `query` | 3 | duplex ack material |
| `noise` | 2 | shaped non-speech, the false-barge-in negative control |

Ground truth (`speech_end_s`) is the end of the last Silero v6.2 speech frame,
computed offline against the pinned model. It is an **acoustic tail marker,
not a linguistic turn boundary** — endpointing latency is measured against it
because the alternative (waveform end) includes the synthesizer's trailing
silence and would flatter every number.

## Metric definitions

`ep50`/`ep90` are defined over turns that **actually ended** (`complete` +
`pause_heavy`). An incomplete turn is *supposed* to be held for
`incomplete_silence_s`; folding that deliberate 2.5 s wait into a latency
percentile would measure the design rather than the implementation. Incomplete
turns are judged by `ep_cutoff` (did the endpointer wrongly cut the owner
off) and their hold time is reported separately as `incomplete_hold_p50_s`.

The duplex family reports `acoustic_ack_s` alongside `enqueue_ack_s` — the
number the software ledger would have reported for the same turn — and their
difference as `sink_presentation_s`. Reporting the pair is the point: it is
what makes the ledger's blind spot a measurement rather than an assertion.

Barge-in decomposes into `detection_s` (interrupt onset → VAD fires),
`flush_s` (interrupt call → queue drained) and `acoustic_stop_s` (interrupt
onset → last sample the sink actually emitted). The owner's own injected audio
is removed from the monitor envelope by power subtraction before the stop time
is read, so the robot is not charged for the owner's interrupt tail.

## Gates

Frozen in `run_acoustic_loop_v1.py:GATES`. An eval whose thresholds move with
its results measures nothing, so these do not get edited to make a run green.

| gate | limit |
|---|---|
| `endpointing_ep_cutoff_rate` | ≤ 0.05 |
| `endpointing_ep50_s` | ≤ 0.500 |
| `endpointing_ep90_s` | ≤ 1.000 |
| `bargein_detection_p50_s` | ≤ 0.400 |
| `bargein_flush_max_s` | ≤ 0.060 |
| `bargein_acoustic_stop_p50_s` | ≤ 0.520 |
| `bargein_false_rate` | ≤ 0.02 |
| `duplex_acoustic_ack_p50_s` | ≤ 0.700 |
| `prosody_apex_within_window_rate` | ≥ 0.80 |

Four of these fail on the first baseline. They were recorded, not tuned —
see `results/README.md` for the numbers and the diagnosis of each.

## Not implemented yet

**Self-WER** — transcribing the robot's own captured output with the pinned
whisper-server and scoring it against the known text, as a synthesis-integrity
check. The rig makes it straightforward (the captured audio is already on
disk) but it would make the suite depend on a running whisper-server, which
today it does not. Worth adding behind a graceful skip.

**FD-Bench duplex vocabulary** (IRD, FSED, SIR, EIR, NIR, SRR) and filler
audibility against the 0.7 s watchdog. These need turn outcomes from a live
`DuplexVoiceSession`; the current duplex family uses a scripted responder to
keep the number about audio rather than about the language model.

**Noise / RIR variants.** The corpus has a shaped-noise negative control but
no SNR sweep and no room-impulse convolution. Those are report-only tiers in
the plan and are not built.

## Determinism

`case_verdicts` (name → verdict) is the determinism contract: two consecutive
runs on the frozen pack must produce an identical object. Latency *values*
jitter run to run and are not part of that contract. Teardown must leave zero
nodes carrying the run's prefix; `teardown_clean: false` invalidates a run.
