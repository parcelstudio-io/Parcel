# Acoustic bring-up plan

> **Current reconciliation, 2026-08-22.** This page preserves a 2026-08-07
> virtual-rig experiment and its runbook; its “now” column is historical evidence,
> not current host state. The XVF3800 currently enumerates over USB and Piper's
> artifacts are present, but plain `sounddevice` still cannot open the native
> PortAudio path, PipeWire exposed no usable product source/sink in the recheck,
> and no physical stream, AEC, DoA or through-air gate is commissioned. Consult
> the [engineering handbook](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md) for
> current readiness.

**Status 2026-08-07.** Parcel's audio stack can now be assembled, exercised and
*measured* on this machine without root. What it cannot do is make a sound in
a room: no transducer has ever been attached, every physical capture reads
RMS 0.00, and the HD-Audio analog card sits at profile `Off` with the default
source routed to `auto_null`. Everything below is split accordingly — what was
landed and gated here, and what is waiting on the owner.

The through-line: **no acoustic claim without a gate met on this machine.**
The virtual rig is Tier-1 evidence and says so in every report it writes.

---

## 1. Where the stack actually stands

| capability | before | now |
|---|---|---|
| `sounddevice` can open a device | no (`libportaudio2` absent, no sudo) | **yes** — 12 devices, ALSA + PulseAudio |
| Piper TTS installed | no | **yes** — pinned 2023.11.14-2, voice sha verified |
| whisper.cpp STT reachable | binary present, unused | **yes** — `/health` answers on 127.0.0.1:8178 |
| semantic endpointing | `energy`, weights absent | **yes** — real Silero v6.2 + Smart Turn v3.2 |
| acoustic measurement of any kind | none | **yes** — `acoustic_loop_v1`, 25 cases, deterministic |
| in-process AEC | none | **yes** — NLMS behind a seam, 35.3 dB synthetic ERLE |
| barge-in ducking | none | **yes** — per-block gain, confirm/restore |
| audio heard in a room | no | **no — owner-gated** |

### The four numbers that matter

From `evals/companion/acoustic_loop_v1/results/` (two identical runs):

- **Sink presentation delay 0.54–0.64 s.** The software ledger's
  `audio_first_playback` is an enqueue timestamp. Measured against the first
  genuinely audible sample, it understates the ack by more than half a second
  — comparable to the entire 0.7 s `filler_watchdog_s` budget.
- **Acoustic ack p50 0.80 s** against a 0.70 s bar. Fails.
- **Barge-in acoustic stop p50 0.72 s** against a 0.52 s bar. Detection is
  fast (0.128 s) and the queue flush is free (71 µs); the remaining ~0.6 s is
  audio already handed to PortAudio still draining. *The robot keeps talking
  for half a second after it has correctly decided to stop.*
- **Endpoint commit p50 0.79 s** against a 0.50 s bar, with **zero cutoffs**.
  The config comment implies a ~0.20 s semantic commit; the assembled pipeline
  delivers ~0.8 s.

None of these were tuned to pass. See §6.

---

## 2. Cards landed (gate met on this machine)

### `env-audio-portaudio-prefix` — `scripts/env-audio.sh`
User-space PortAudio via `apt-get download` + `dpkg -x` into
`~/.local/opt/portaudio`. No root anywhere. `libjack-jackd2-0` is fetched too
and is **not optional**: `libportaudio.so.2` has a `DT_NEEDED` on
`libjack.so.0` which this host does not ship. The unversioned
`libportaudio.so` symlink is equally load-bearing —
`ctypes.util.find_library` ignores `LD_LIBRARY_PATH` for its ldconfig lookup
and asks for the unversioned name via its `ld`/`objdump` fallback. Both facts
are recorded in the script header, along with the 3-line monkeypatch to use if
binutils ever disappears.

Sourced from `scripts/launch_sim.sh`, never fatally: a host with no audio must
still boot the simulator.

**Gate output:**
```
env-audio: portaudio PortAudio V19.7.0-devel, revision e1b70d33
env-audio: 12 device(s); hostapis: ALSA, PulseAudio
env-audio: 5 input, 10 output
env-audio: CHECK PASSED
InputStream 16k mono int16: OPENED, read (16000, 1) rms=0.00 overflow=False
OutputStream 22050 int16: OPENED, wrote 100ms silence
```
`rms=0.00` is the owner-gated part, not a software failure.

Pinned snapshot (mirror-served, verified): `libportaudio2`
19.7.0+git20260206.e1b70d33-0ubuntu1 sha256 `2c6290fe…f16d`,
`libjack-jackd2-0` 1.9.22~dfsg-5build1 sha256 `129857d4…fe99`. `--check` warns
loudly on mirror drift rather than silently measuring a different PortAudio.

### `speech-services-nocompile` — `--piper-only`
`scripts/install_speech_services.sh --piper-only` drops the git / cmake /
C++-compiler prerequisites (this host has none of them) and installs only the
prebuilt Piper release plus its voice, reusing the existing PIN BLOCK, staged
`.part` downloads and sha256 verification. STT needed no work at all:
`run_speech_services.sh` already accepts the prebuilt
`third_party/whisper.cpp-bin` tree.

**Gate output:**
```
run_speech_services: OK  whisper.cpp: http://127.0.0.1:8178/health answered
run_speech_services: OK  piper binary / voice / metadata (22050 Hz)
run_speech_services: CHECK PASSED
$ echo ... | third_party/piper/piper --model models/piper/voice.onnx --output-raw
samples=45114 duration=2.046s rms=4475.5 peak=32767
```
Voice sha `5efe09e6…019f` matches the pin exactly.

### `semantic-endpointing-models`
`onnxruntime` 1.28.0 installed; both pinned ONNX models downloaded:

| model | sha256 | size |
|---|---|---|
| `models/endpointing/silero_vad_v6.onnx` | `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3` | 2.33 MB |
| `models/endpointing/smart_turn_v3.onnx` | `2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f` | 8.68 MB |

**Gate output** (with `RuntimeWarning` promoted to an error, so any
degrade-to-energy warning would have failed it):
```
SileroVad.available: True
SileroVad probs: silence=0.0017 noise=0.0770
TurnEndpointer.detail(): smart-turn-v3
first silence frame decision: hold p_complete= 0.8817123174667358
GATE: both real models active, no degrade warning raised
```

**Config note — the flip did NOT edit `configs/robot.yaml`.** That file is
hash-locked by `evals/companion/embodied_plan_v1/manifest.json`
(`locked_inputs.robot_config` = `f6468887…726c`) and `run_embodied_plan_v1.py`
hard-fails on drift. Parcel has no config-overlay mechanism — `ConfigStore`
loads exactly one YAML and never merges — but the CLI, the panel and
`launch_sim.sh` all take `--config PATH`. So the acoustic settings live in a
**derived** sibling file:

```
.parcel/bin/python scripts/make_acoustic_config.py         # writes configs/robot.acoustic.yaml
.parcel/bin/python scripts/make_acoustic_config.py --check # stale?
scripts/launch_sim.sh --config configs/robot.acoustic.yaml --llm
```

It is regenerated from `robot.yaml`, never forked from it, and records the
source sha it was derived from — a hand-maintained copy is exactly the
divergent-config trap the packaged `src/parcel_robot/config/robot.yaml`
already fell into. `robot.yaml`'s sha is unchanged: `f6468887…726c`.

`echo_guard_scale` deliberately stays at 2.5. It drops only after an ERLE
gate passes, and no ERLE has been measured because no echo path exists.

### `acoustic-loop-v1-rig` + the four eval cards
`evals/companion/acoustic_loop_v1/` — see that pack's README for the design
and `results/README.md` for the numbers. Highlights:

- Per-run PipeWire null-sink pair (`object.linger`, destroyed in teardown).
- `pw-link <mic> <sink>` puts owner audio and robot audio in **one recording
  on one sample clock**, so acoustic intervals are a subtraction inside a
  single file rather than a comparison across two unsynchronized processes.
- Nothing in the audio code was modified to make it work. Every entry point
  already existed: `MicrophoneVoiceLoop(frames=…)`, `resolve_audio_device`,
  `SpeakerSink(device=…, on_chunk_start=…)`.
- 30 files sha-pinned in `manifest.json`, verified before each run.

**Determinism gate: PASS.** Two consecutive runs, identical `case_verdicts`,
identical gate statuses, `teardown_clean: true`, zero orphan nodes. No
physical audio, no root.

### `aec-l1-inprocess` — with a correction to the research
The card named `pywebrtc-audio` as a "prebuilt py3.14 x86_64 wheel". **That is
not true on this machine.** PyPI serves `0.0.1` as a 1.2 kB placeholder whose
`__init__.py` is empty, and `0.1.0` is source-only and dies at
`CMakeDetermineCCompiler` because there is no C compiler here.

Rather than leave the rung empty or ship a stub, `AecStage` in
`voice_audio.py` is a real normalized-LMS adaptive canceller: deterministic,
numpy-only, unit-tested, and sitting exactly where an AEC3 backend would later
plug in. Off by default — with `aec=None` the frame path is byte-identical,
and a test asserts that by spying on every frame reaching the VAD.

**Gate output:**
```
converged synthetic ERLE: 35.3 dB (bar 15 dB)
double-talk: near-end residual 1689 vs echo residual 31 -> ratio 54.0x
25 passed in 0.46s
```
Honest limits, documented in the class: no double-talk detector, no residual
suppressor, no nonlinear processing. It handles a linear echo path and
degrades toward doing nothing on anything else.

### `ducking-l2`
`SpeakerSink.duck(db)` / `restore()`, applied **per ~50 ms output block** so a
duck requested mid-chunk lands within one block. Unity gain by default;
`ducks_applied` / `ducks_restored` / `ducked_for_s` support the ~200 ms
confirm window. A test asserts ducking never touches the interrupt latch —
ducking is explicitly not a teardown, and supersession still requires the
normal commit criteria.

---

## 3. Card partially landed: `ledger-acoustic-clocks`

**Blocked by file ownership, not by difficulty.** Every ledger write in this
repo funnels through `RobotRuntime._voice_stage`, and the stage vocabulary is
a closed `STAGES` frozenset in `observability.py` whose `mark()` raises on an
unknown name. Both files are outside this lane's ownership.

What **is** landed — the measurement surfaces, in files this lane owns:

| clock | where | field |
|---|---|---|
| STT request start / final | `providers.py` `WhisperCppProvider` | `last_metrics` = `{request_start_monotonic, final_monotonic, duration_s, audio_s, real_time_factor, status}` |
| capture speech-end + semantic commit | `voice_audio.py` `MicrophoneVoiceLoop` | `last_turn_clocks` = `{speech_end_monotonic, semantic_commit_monotonic, endpoint_decision_s, utterance_s}` |
| speaker first sample | `voice_audio.py` `SpeakerSink` | `first_chunk_started_monotonic`, `last_chunk_started_monotonic` |

All three mirror `LlamaCppProvider.last_metrics` in shape and are plain data —
nothing reaches into the tracker, so these files stay dependency free.

`MicrophoneVoiceLoop._elapsed_s` was a sample clock with no monotonic anchor,
which is why the existing `on_turn_commit` value could never be compared with
anything else in the ledger. `last_turn_clocks` fixes that at the source.

### Remaining wiring (owner or the runtime lane)

1. `observability.py` — add to `STAGES`: `capture_speech_end`,
   `semantic_commit`, `stt_request_start`, `stt_final`,
   `audio_first_sample`. `mark()` raises on anything not in that set.
2. `runtime.py:4886` — `source="text"` is hardcoded; pass `"microphone"` for
   mic turns so `/latency` can distinguish them (`TurnTrace.source` already
   flows to `_trace_row`).
3. `runtime.py:1227` `_audio_chunk_started` — fan `SpeakerSink.
   first_chunk_started_monotonic` into `self.latency.mark(...,
   "audio_first_sample")`. The chunk token is `(track, epoch, emotes)` and
   carries no `turn_id`, so it must be extended.
4. `runtime.py:5044` `_record_turn_commit` — also read
   `loop.last_turn_clocks` and mark the capture clocks.
5. `ui/latency.html:73` — add the new derived latencies to `metricNames`, or
   they appear only inside the per-turn JSON dump column.

**Until this lands, no sub-700 ms ack claim may be made from `/latency`.**
The acoustic tier has now put a number on the gap it hides: 0.54–0.64 s.

---

## 4. Cards PREPARED — not run, not claimed

Each is written and syntax-checked; none has met its gate, because each needs
something this machine does not have.

| card | artifact | blocked on |
|---|---|---|
| `device-activation-snapshot` | runbook §5 below | owner's real desktop session |
| `acoustic-hello-smoke` | `scripts/acoustic_smoke.sh` | a transducer |
| `aec-l0-pipewire` | runbook §5.3 config | node names from the snapshot |
| `doubletalk-operating-curve` | Tier-2, not started | a transducer |
| `stt-upgrade-faster-whisper` | §7 conditional | ledger attribution first |
| `xvf3800-integration` | §8 | hardware attach |

---

## 5. OWNER RUNBOOK

Run these from the real desktop session. **Not from a sandboxed shell** — this
matters more than it sounds: three different shells on this machine saw three
different PipeWire views during bring-up, and an AEC `target.object` captured
outside the owner's session silently produces a dead source.

### 5.1 Activate the analog endpoints  (`device-activation-snapshot`)

```bash
wpctl status && pw-link -i                 # snapshot BEFORE
wpctl set-profile 48 1                     # HD-Audio Generic -> Analog Stereo Duplex
wpctl status                               # a real analog sink AND source should appear
wpctl set-default <source-id>              # replace the auto_null default source
```

Card 48's profile 1 is `Analog Stereo Duplex`, enumerated via `pw-dump`; the
card currently sits at profile 0 (`Off`). Profile activation needs no root.

Then confirm signal:

```bash
source scripts/env-audio.sh
.parcel/bin/python -c "
import numpy as np, sounddevice as sd
d = sd.rec(int(3*16000), samplerate=16000, channels=1, dtype='int16'); sd.wait()
print('RMS', float(np.sqrt(np.mean(np.square(d.astype(float))))))"
```

**If RMS stays 0.00 with the profile active, nothing is physically plugged
into the jacks.** That is the single item gating every remaining card in this
document. A $10 analog mic and speaker unblocks Tier 2; the already-purchased
XVF3800 + CQRobot unblocks Tier 2 *and* hardware AEC.

Record the result into `docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md`'s
audit section: `wpctl status`, `pw-link -i`, and
`sounddevice.query_devices()`. **The AEC node names in §5.3 must come from
this snapshot**, not from any shell used during bring-up.

### 5.2 First acoustic turn  (`acoustic-hello-smoke`)

```bash
scripts/run_speech_services.sh
scripts/acoustic_smoke.sh              # speech.mode auto — degrades loudly
scripts/acoustic_smoke.sh --fail-closed  # speech.mode audio — once, to prove it
```

Gate: audible TTS on the real sink; capture RMS > 0; one completed acoustic
turn; a latency-ledger row for it. The script checks the first three itself
and exits 3 with a pointer back here if capture is digital silence.

### 5.3 Software AEC  (`aec-l0-pipewire`)

Every library is already installed and verified present: PipeWire 1.6.2,
`libpipewire-module-echo-cancel.so`, `libspa-aec-webrtc.so`. Write
`~/.config/pipewire/pipewire.conf.d/99-parcel-aec.conf`:

```
context.modules = [
  { name = libpipewire-module-echo-cancel
    args = {
      library.name  = "aec/libspa-aec-webrtc"
      monitor.mode  = true
      node.latency  = "512/48000"
      aec.args = {
        webrtc.gain_control      = false
        webrtc.noise_suppression = true
        webrtc.high_pass_filter  = true
      }
      capture.props = {
        node.passive  = true
        target.object = "<ALSA INPUT NODE NAME FROM §5.1 — placeholder>"
      }
      source.props = {
        node.name        = "parcel_aec_source"
        node.description = "Parcel AEC Source"
      }
    }
  }
]
```

```bash
systemctl --user restart pipewire wireplumber
```

`monitor.mode = true` takes the far-end reference off the default sink's
monitor, so `SpeakerSink`, the chunk tokens and the playback clock are all
untouched. An unpinned `target.object` is the known silent-source failure —
fill it from the §5.1 snapshot.

Then set `speech.input_device: parcel_aec_source` (regenerate the derived
config; do not edit `robot.yaml`).

**Gate:** ERLE ≥ 20 dB after 3 s convergence, raw mic vs `parcel_aec_source`
recorded simultaneously over far-end-active frames; Silero fires on owner
speech at normal level over normal-volume TTS. Exclude the first 2 s —
convergence takes ~2–3 s and AEC3's residual suppressor tends to clip the
first syllable of a barge-in. **Only on pass** may `echo_guard_scale` drop
from 2.5 toward ~1.3.

Interactive tuning without editing files: `pw-cli load-module` from a
long-lived shell (the module dies with the `pw-cli` process). `pactl` is
absent; extract it with the same `apt-get download` + `dpkg -x` trick
(`pulseaudio-utils`; `libpulse.so.0` is already installed).

### 5.4 Tier-2 rig  (`acoustic_rig_v1`, not yet created)

Everything above is a prerequisite. Per-run preflight: noise-floor measurement
plus a reference-chirp round trip (delay and level calibration, subtracted
before any lag metric); room metadata into the results JSON; runs breaching
the noise/delay thresholds are **quarantined — recorded, not gated**. Acoustic
runs are not bit-reproducible and the README must say so. Encode quarantine in
the runner, not in judgement calls.

---

## 6. Honest failures from the first baseline

Five gates failed. Nothing was tuned, no threshold moved, no code changed to
turn a number green after seeing it. Two are genuine product defects the
software tier structurally could not have found.

**D1 — post-interrupt audio drain (~0.6 s).** `duplex_v1` correctly asserts no
chunk tokens leak after `interrupt()`. True — and the audio keeps playing
anyway, because `SpeakerSink.interrupt()` stops *writing* at the next ~50 ms
block but samples already handed to PortAudio still present. Fix is to abort
the output stream, not merely cease writing it. Backlog N-item.

**D2 — echo guard fragments the neural VAD's input.** Both noise-only
injections triggered a barge-in (false rate 1.00 vs a 0.02 bar). Silero is not
at fault: probed directly it rates those fixtures at max p = 0.21/0.23 against
a 0.5 threshold, and real interrupt speech at 1.00. The cause is ordering — in
`_handle_frame` the echo guard runs *before* the neural VAD and `return`s on
suppressed frames, so Silero sees only surviving loud fragments with
artificial onsets rather than a continuous stream. Backlog N-item.

The other three (endpoint commit ~0.79 s, acoustic ack 0.80 s, nod-sync
64.3 %) are recorded as the baseline to improve against.

---

## 7. `stt-upgrade-faster-whisper` — CONDITIONAL, NOT INSTALLED

Do **not** adopt this until the ledger clocks (§3) show STT actually
dominating the ack budget. `WhisperCppProvider.last_metrics` now reports
`duration_s` and `real_time_factor` per request, which is the evidence to
gather first.

If it is warranted: a ~40-line HTTP shim exposing whisper.cpp's exact
`/inference` contract (multipart `file` / `response_format=json` / `language`
in, `{"text": …}` out) on the same 127.0.0.1:8178, backed by
`faster_whisper.WhisperModel("small", device="cuda",
compute_type="int8_float16")`, plus `nvidia-cublas-cu12` and
`nvidia-cudnn-cu12==9.*` with their lib dirs on `LD_LIBRARY_PATH` (scoped to
that service's launch path only — see the LD_LIBRARY_PATH hygiene note in
`scripts/env-audio.sh`). Wheels verified resolvable and cached under the
session scratchpad. Zero changes to `providers.py` or the config.

Gate before adoption: STT wall-time p50 at least halves against the prebuilt
CPU baseline; VRAM ≤ 1.5 GB alongside Gemma; `WhisperCppProvider` round-trips
unmodified. Do **not** adopt speaches / OpenAI-shaped servers — that is a seam
change.

---

## 8. `xvf3800-integration` — OWNER-GATED, LAST

The ReSpeaker XVF3800 and CQRobot speaker are purchased and have never
enumerated. Attach with playback routed through the array's **own amp/DAC
reference path** — a separate speaker defeats the hardware AEC entirely.

Once enumerated as a UAC device (ASR channel = capture), integration is
config-only on seams that already exist: `speech.input_device` /
`output_device` set to a `ReSpeaker` substring (`resolve_audio_device` handles
name matching), delete `99-parcel-aec.conf`, `echo_guard_scale` → 1.0, and
budget the array's ~50 ms output delay in the ack ledger.

Gate: the full acoustic suite green on the array; its double-talk curve
dominates the frozen pre-AEC baseline; acoustic ack p50 ≤ 0.7 s *including*
device delay. Only then is hardware AEC the shipped path. The pre-AEC curve
must be frozen first — that is what makes the purchase measured rather than
assumed.

---

## 9. Standing risks

- **Transducer existence gates everything physical.** Profile activation
  needs no root, but with nothing in the jacks every capture stays RMS 0.
- **PipeWire session views differ per shell.** Any `target.object` or
  default-device assumption captured outside the owner's session silently
  produces a dead source.
- **`apt-get download` serves whatever the mirror has.** `env-audio.sh
  --check` warns on drift from the verified snapshot; it does not fail, so a
  bump is visible rather than silent.
- **`LD_LIBRARY_PATH` hygiene.** The PortAudio prefix, whisper.cpp's ggml
  `.so` directory and any future cublas/cudnn dirs are three separate
  injections for three separate processes. Keep each scoped to its own launch
  path; a global export invites ABI collisions.
- **Config drift.** `configs/robot.acoustic.yaml` is derived and carries the
  source sha; run `make_acoustic_config.py --check` after touching
  `robot.yaml`. The packaged `src/parcel_robot/config/robot.yaml` remains a
  divergent fallback with stale keys and is still unreconciled.
- **Software AEC physics.** Expect ~2–3 s convergence and a clipped first
  syllable on barge-in; exclude the first 2 s from ERLE gates and let the
  endpointer tolerate a chopped onset.
- **Tier-2 runs are not bit-reproducible.** Without preflight-and-quarantine
  the nightly gates will flake and erode trust in the honest gates.
- **Utterance-level STT caps perceived responsiveness.** No partials means the
  ack bar is met by fillers, not full replies; streaming partials and
  speculative generation stay open regardless of these gates.
- **Bluetooth headsets are not a valid stopgap** for barge-in or AEC work —
  HFP mono plus no shared reference. Playback smoke tests only.
