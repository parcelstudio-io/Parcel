# Acoustic evaluator validity rerun — results

Run date: 2026-08-29. Runner:
`virtual-pipewire-rig-v2-measurement-validity`. Frozen cases: 25. Wall time:
223.40 s. Report SHA-256:
`40ac53e3ce5ba277c677cdf381f936c81e5455e43a0dae16a61656f8732244c2`.
The report validates against the committed Draft 2020-12 result schema and
records `teardown_clean: true` with no owned node or child left behind.

## Gate outcome

| gate | result | status |
|---|---:|---|
| endpoint cutoff rate ≤ 0.05 | 0.3077 | **FAIL** |
| endpoint commit-validity failure rate = 0 | 0.3077 | **FAIL** |
| valid endpoint ep50 ≤ 0.500 s | 0.274 s | pass |
| valid endpoint ep90 ≤ 1.000 s | 0.2916 s | pass |
| generic barge-in detection p50 ≤ 0.400 s | 0.0004 s | pass |
| queue flush max ≤ 0.060 s | 0.000057 s | pass |
| acoustic robot-output STOP p50 ≤ 0.520 s | — | **not measured** |
| noise false-barge rate ≤ 0.02 | 0 | pass |
| virtual audible ack p50 ≤ 0.700 s | 0.790 s | **FAIL** |
| audio-transport accent match ≥ 0.80 | 0.9286 | pass |
| physical motion/prosody sync | — | **not measured** |

That is 6 pass, 3 fail, and 2 `not_measured`; `gates_passed` is correctly
false and the runner exits 1.

## What changed in the evidence

Endpoint commits are now recorded at the synchronous commit callback on the
loop sample clock. Nine of 13 cases had a valid latency measurement. Four did
not:

- `pause_01` committed at 2.19 s before the final 4.156 s boundary, then
  committed again at 4.41 s;
- `pause_03` committed at 2.19 s before the final 4.668 s boundary, then
  committed again at 4.95 s;
- `incomplete_02` committed after only 0.266 s rather than the required
  incomplete hold;
- `incomplete_04` committed after only 0.254 s rather than the required hold.

The six complete utterances were valid at 0.238–0.282 s after final speech;
the one valid pause-heavy case was 0.306 s. Fast valid latency therefore does
not compensate for the 4/13 semantic-cutoff/validity failure.

Acknowledgement now retains the source WAV rate and distinguishes queue
attempt, first output-buffer write attempt, and the virtual monitor onset.
Case values were 3.094, 0.790, and 0.752 s virtual-audible; the corresponding
write-attempt values were 2.5953, 0.3103, and 0.3095 s. The first query took
the 2.5 s incomplete-turn branch. The remaining monitor gap includes the
reply fixture's leading silence and must not be called device latency.

All six speech interruptions triggered generic VAD barge-in and queue flush
was at most 57 microseconds. The sink monitor still mixes owner and robot
paths, so mixed-minus-owner residuals (diagnostic p50 1.09 s) are explicitly
barred from the acoustic-STOP gate. This run did not recognize the word STOP
or measure the local emergency latch.

Audio transport preserved 13 of 14 detected source accents within ±150 ms;
median signed lag was -0.9 ms and absolute p95 4.2 ms after aligning each
track to its own first audible sample. No `BeatLayer`, motion command, encoder,
or actuator was observed, so physical prosody sync remains unmeasured.

## Failed first attempt and remediation

The first full attempt was invalidated and stopped because PortAudio could
invoke a callback already in flight after the final callback had raised
`CallbackStop`. The exhausted iterator was then mislabeled as a buffer error;
interrupting the invalid run ended with process status 139 and produced no
report. `SpeakerSink` now makes EOF idempotent: every post-final callback emits
silence and repeats graceful stop. A deterministic regression reproduces the
extra callback. Five focused guarded tests passed, and a real PipeWire
null-sink smoke subsequently observed a write attempt, quiesced playback, and
logged no failure before this retained rerun.

## Commands

```bash
source scripts/env-audio.sh
.parcel/bin/python -m evals.companion.acoustic_loop_v1.run_acoustic_loop_v1 \
  --output research/20260829/acoustic-eval-v2/results.json \
  --node-prefix parcel_sol_20260829_v2b

env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh \
  --label acoustic-eof-fix .parcel/bin/python -m pytest -q \
  tests/test_acoustic_defects.py::test_n16_post_final_portaudio_callback_repeats_graceful_stop \
  tests/test_acoustic_defects.py::test_n16_normal_completion_drains_without_abort \
  tests/test_acoustic_defects.py::test_n16_interrupt_is_prompt_and_portaudio_lifecycle_is_worker_owned \
  tests/test_acoustic_defects.py::test_n16_rt_callback_does_not_take_application_lock_or_call_clock_clip \
  tests/test_acoustic_defects.py::test_n16_callback_epoch_never_revalidates_after_interrupt_begin_aba
```

The evaluator-focused guarded suite separately passed 23 tests. The retained
runner exit code 1 is the expected quality verdict, not an infrastructure
failure.
