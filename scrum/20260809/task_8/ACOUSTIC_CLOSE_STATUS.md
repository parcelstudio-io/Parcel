# acoustic-close — N16 / N17 / N19

**Date:** 2026-08-09 · **Card:** acoustic-close (land N16, N17, N19).
**Owner files touched:** `voice_audio.py`, `observability.py`, `tests/test_acoustic_defects.py` (new). `runtime.py` NOT touched (owned by another lane). Frozen acoustic pack NOT edited (only a new results row written).

## The one-line outcome, stated honestly

All three **code** changes are landed and are the changes the card asked for.
**The two barge-in rig gates did not move**, and a full investigation shows
**why the frozen virtual rig cannot move them**: both failures are dominated by
rig/environment artifacts that the null-sink rig produces and that no
`voice_audio.py` change can remove — not by the defects as originally
diagnosed. No gate was weakened, no threshold moved, the frozen pack was not
edited, and `runtime.py` was not touched. The evidence is below so the next
person does not have to re-derive it.

Fresh frozen run: `results/acoustic-loop-v1-20260809-190213.json` — **4 / 9
gates pass**, identical to the 2026-08-07/09 baselines. `teardown_clean: true`,
zero orphan nodes.

| gate | baseline | this run | limit | status |
|---|---|---|---|---|
| bargein_acoustic_stop_p50_s (N16) | 0.78 | **0.78** | ≤0.52 | FAIL |
| bargein_false_rate (N17) | 1.00 | **1.00** | ≤0.02 | FAIL |
| duplex_acoustic_ack_p50_s (N19-adjacent) | 0.80 | 0.80 | ≤0.70 | FAIL |
| endpointing_ep50_s (not in scope) | 0.772 | 0.784 | ≤0.50 | FAIL |
| prosody_apex_within_window_rate (not in scope) | 0.643 | 0.643 | ≥0.80 | FAIL |
| the other 4 | pass | pass | — | pass |

---

## N16 — abort the OutputStream on barge-in

**Fix (landed).** `SpeakerSink._play` (`src/parcel_robot/voice_audio.py`): on
the interrupt latch, call `stream.abort()` before returning, instead of letting
the `with sounddevice.OutputStream(...)` context manager exit through `stop()`.
`sounddevice==0.5.5` `__exit__` calls `stop()` (which **drains** buffered
frames) then `close()`; `abort()` discards the already-queued frames
immediately. This is the correct fix for real hardware, where a `latency='high'`
OutputStream buffers hundreds of ms and `stop()` plays them out after a correct
barge-in decision.

**Why the rig gate does not move — it is not the fix, it is the rig.**

1. **The null sink has no drain to abort.** Measured `OutputStream.latency` on
   the rig sink = **0.0000 s** (default device 0.0348 s). With and without the
   `abort()` change, the robot's audio on the sink monitor stops **0.02 s**
   after `interrupt()` (`probe_beforeafter`, chunked enqueue identical to the
   rig). There is no ~0.6 s output-buffer drain on a zero-latency null sink for
   `abort()` to remove. The card's premise ("~0.6 s of already-buffered audio
   draining out of the output stream") does not reproduce on this rig.
2. **The 0.72–0.78 s that the gate reports is owner-interrupt residual, not
   robot audio.** `run_bargein` computes `acoustic_end` from
   `robot_only_envelope`, a power subtraction that removes the owner's injected
   interrupt from the sink monitor. Frame-by-frame (`probe3`): the robot's
   `robot_only` envelope goes to **0 at interrupt-onset + ~0.12 s** (the robot
   really has stopped), then the subtraction leaves **spurious 1-frame spikes**
   (e.g. 6396 RMS) at interrupt-onset + 0.5–0.7 s where the owner's audio is
   loudest and the subtraction cancels imperfectly. Those spikes set
   `acoustic_end`, so the gate reads 0.72–0.78 s regardless of when the robot
   actually stopped.

So on the virtual rig `bargein_acoustic_stop` measures owner-residual and null
sink presentation, neither of which `abort()` touches. **`abort()` needs a real
output device with real latency to validate** → `does_not_prove` on this tier.

**Landed code proof:** `test_acoustic_defects.py::test_n16_interrupt_aborts_the_output_stream`
(interrupt in flight → `abort()` is called, and before the draining `stop()`)
and `::test_n16_normal_completion_drains_without_abort` (an un-interrupted reply
plays to its end via `stop()`, `abort()` never fires). Chunk-token/epoch
atomicity, the drain-window fix and the `begin_utterance` latch are untouched
(existing `test_voice_audio.py` speaker-sink tests stay green).

---

## N17 — echo guard on the decision, not the VAD input

**Fix (landed).** `MicrophoneVoiceLoop._handle_frame` /
`_handle_frame_semantic` (`voice_audio.py`): the echo guard no longer `return`s
on suppressed frames. Every frame now reaches the neural VAD (Silero sees a
**continuous** stream); the guard computes `echo_suppressed` and gates the
**decision** (`is_speech = raw_is_speech and not echo_suppressed`), so a frame
below the echo-guard level cannot start a barge-in or advance the endpointer,
but Silero's input is never fragmented. The legacy energy-VAD path keeps its
historical swallow (it is not a continuous neural model). This is exactly the
change the card specified and is the correct design for a real, **attenuated**
acoustic echo.

**Why the rig gate does not move — the original diagnosis was wrong, and the
real cause is a rig capture artifact this lane cannot fix.**

- The baseline diagnosis said Silero rates the noise fixtures at p=0.21/0.23 and
  the false positives came from fragmentation. Directly measured
  (`probe_silero_offline`): fed the raw fixtures continuously, Silero rates
  **noise_01 max p=0.287, noise_02 max p=0.170** (both reject at 0.5) and real
  speech at **1.0**. Fed the noise as clean frames through the full loop, **both
  the OLD (swallowing) and the NEW (continuous) code reject every noise fixture
  at every gain 1×–10×** (`probe_gain`). Fragmentation is not what makes the rig
  noise cases fail.
- What actually fails: **the robot's own audio is present in the loop's mic
  capture at full scale.** With the robot playing and **no owner injected at
  all**, `MicrophoneVoiceLoop` still fires a barge-in (`probe_leak`: capture RMS
  mean 2570, peak 32767, 2 false barge-ins over 6 s). Silero correctly rates
  that (it is real speech), and an energy echo guard cannot suppress a
  full-scale echo. This is present in both old and new code and is why every
  noise case reads `false_barge_in`.
- Root cause of the contamination (`probe_graph`, `pw-link -l` during
  playback): `capture_frames` runs `pw-record --target <mic>`, but WirePlumber
  connects that capture to **`<sink>:monitor`** — which carries both the owner
  (mic→sink link) and the robot (`python:output → sink`). The `--target` hint is
  overridden (`--target <mic>.monitor` routes there too), and it survives
  `systemctl --user restart wireplumber` and a full `pipewire` restart. It is a
  degraded routing state of this PipeWire session; the frozen rig's
  single-clock design (`link_mic_into_sink`) is what exposes it. The baselines
  were produced in a session where the capture routed cleanly.

The same contamination also explains the uniform **0.128 s** barge-in
"detection" in every interrupt case (2 fixtures × 3 offsets): it is a fixed
latency from robot-onset-in-capture to Silero firing on the robot's own echo,
not owner-response latency.

Because the loop hears the robot at full scale, `bargein_false_rate` stays 1.00
and `bargein_acoustic_stop`'s owner reference is itself contaminated. **A clean
mic capture is required to measure either gate; that is a rig/environment fix
this lane is barred from (`append/new only`), and it would flip the gates
independently of this code change (old code also rejects clean noise).** →
`does_not_prove` on this tier.

**Landed code proof:** `test_acoustic_defects.py` —
`test_n17_neural_vad_sees_quiet_frames_during_playback` (the VAD is scored on
suppressed frames now: continuity, not fragmentation),
`test_n17_loud_owner_speech_over_tts_still_barges_in` (real owner over TTS still
barges in), `test_n17_energy_path_still_swallows_suppressed_frames` (legacy path
unchanged — mirrors the existing `test_microphone_loop_triggers_barge_in_over_echo_guard`).

---

## N19 — acoustic-ack clocks into the ledger

**Landed (owned half):** the five stages the ledger needs are added to the
closed `observability.STAGES` vocabulary — `capture_speech_end`,
`semantic_commit`, `stt_request_start`, `stt_final`, `audio_first_sample`.
`LatencyTracker.mark` raises on unknown names, so registering them is the
keystone that unblocks the fan-in, and it is the one registry that validates
stage names (searched: `duplex/*`, the panel, the session-log schema — every
other consumer name-matches and ignores the rest, same as U35 found).

The three measurement surfaces the fan-in reads were already landed in owned/
adjacent files and are verified present:
`MicrophoneVoiceLoop.last_turn_clocks` (`speech_end_monotonic`,
`semantic_commit_monotonic`), `WhisperCppProvider.last_metrics`
(`request_start_monotonic`, `final_monotonic`),
`SpeakerSink.first_chunk_started_monotonic`.

**Residual — the fan-in itself is in `runtime.py`, which is DO NOT TOUCH.**
Every ledger write funnels through `RobotRuntime._voice_stage`; the four marks
the card names live at `runtime.py:1303` (`_audio_chunk_started`, also the
gesture/emote lane's beat-arming method), `runtime.py:5353` (`source="text"`
hardcoded), `runtime.py:5511` (`_record_turn_commit`), and the STT
`last_metrics` read. `DuplexVoiceSession` (owned) does not hold the
`LatencyTracker`, the sink, the recognizer, or the turn_id-bearing token, so the
fan-in cannot be relocated into an owned file without a `runtime.py` signature
change. With `STAGES` now populated, the remaining diff is the four marks in
§3 of `docs/ACOUSTIC_BRINGUP_PLAN.md` plus `ui/latency.html:73`; it is a
4-line, one-owner change for the runtime lane. **Until it lands, no sub-700 ms
ack claim may be made from `/latency`** (the bring-up plan already says this;
the acoustic tier measured the hidden gap at 0.54–0.64 s and this run reproduces
it: duplex `sink_presentation_s` 0.54–0.64).

**Landed code proof:** `test_acoustic_defects.py::test_n19_*` — the five stages
are in `STAGES`; the tracker marks and reports them (with `source="microphone"`
and `audio_first_sample` later than `audio_first_playback`); an unknown stage
still raises.

---

## does_not_prove (this tier / this session)

- N16's post-interrupt drain fix: **needs a real output device with real
  latency.** The null sink has 0 s latency; the fix is a no-op here and the
  0.78 s the gate reports is owner-residual, not drain.
- N17's decision-gating fix: **needs a real, attenuated acoustic echo.** The
  rig has either no echo (clean frames — both old and new reject noise) or a
  full-scale echo (this session's capture contamination — neither can suppress
  it). The attenuated middle the fix targets cannot be created here.
- The rig capture contamination (`pw-record --target mic` → sink monitor) is an
  environment/rig issue outside this lane's ownership; correcting it would flip
  N16 and N17 independently of these code changes.
- Everything the pack already lists: no room, no transducer, no real echo, Piper
  speech, scripted duplex responder.

## Verification

- `tests/test_acoustic_defects.py` (new): **9 passed**.
- targeted battery (voice audio/streaming/AEC, observability, system-utterance,
  endpointing, duplex ×3, K6 voice lanes, yield): **249 passed, 1 skipped**.
- `ruff check` on every touched file: **clean**.
- full default suite `MUJOCO_GL=egl .parcel/bin/python -m pytest tests/ -q`:
  **3088 passed, 19 skipped, 2 xfailed, 0 failed, 0 errors** (821 s). The
  nav-lane import errors that were red in the U35 run have since resolved; this
  tree is clean.
- frozen rig fresh run `results/acoustic-loop-v1-20260809-190213.json`: 4/9,
  `teardown_clean: true`, zero orphans; endpointing/duplex/prosody unchanged
  from baseline, confirming the N17 change does not touch the no-playback paths.

## Files touched

| file | change |
|---|---|
| `src/parcel_robot/voice_audio.py` | N16 `SpeakerSink._play` `stream.abort()` on interrupt; N17 echo guard moved from VAD input to decision (`_handle_frame`, `_handle_frame_semantic(..., echo_suppressed=)`) |
| `src/parcel_robot/observability.py` | N19 five acoustic-ack stages added to `STAGES` |
| `tests/test_acoustic_defects.py` | **new**, 9 cases (N16 abort path, N17 continuity + decision gate, N19 stages) |
| `evals/companion/acoustic_loop_v1/results/acoustic-loop-v1-20260809-190213.json` | new frozen-rig run (append-only) |

**Not touched:** `runtime.py`, the frozen acoustic runner/rig/fixtures/schema/
manifest, everything else on the DO-NOT-TOUCH list.
