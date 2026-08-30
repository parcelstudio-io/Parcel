# Endpoint policy sensitivity study — design

Date: 2026-08-29. Production code is not changed by this experiment.

## Question and declared exploratory grid

Corrected acoustic evaluator v2 found premature or multiple commits in
`pause_01`, `pause_03`, `incomplete_02`, and `incomplete_04`. On those same 13
defect-discovery fixtures, test whether any declared SmartTurn confidence and
short-silence pair is consistent with both:

1. zero internal-pause commits, zero early incomplete commits, and exactly one
   eventual commit per case; and
2. valid complete/pause ep50 <= 0.5 s and ep90 <= 1.0 s.

The exploratory grid is confidence `{0.50, 0.70, 0.80, 0.90, 0.95, 0.98}` by
short silence `{0.20, 0.35, 0.50, 0.75, 0.90}` seconds. The incomplete timeout
stays 2.5 s. Every pair is replayed at four 16 kHz input-frame phases
`{0, 120, 240, 360}` samples. These phase variants are derived from the same
audio and are not a holdout.

The narrow hypothesis is that **no declared grid point** passes all replay
variants. If one or more pass, this study may nominate (not adopt) one in-sample
candidate only if the production-default replay first matches corrected v2.
The fixed tie-break is lowest ep90, then lowest ep50, then highest confidence,
then longest short-silence timeout.

Production currently hardcodes SmartTurn confidence at 0.5. Alternative
confidence values are therefore hypothetical until a separately reviewed
constructor/config field and parity tests exist.

## Replay and validity rules

- Fail closed against the acoustic manifest and all fixture/model pins.
- Use the corpus builder's exact 101-tap windowed-sinc 22.05 kHz -> 16 kHz
  resample, then the production 480-sample input / continuous 512-sample Silero
  buffering and real pinned SmartTurn model.
- Advance the same 30 ms sample clock as `MicrophoneVoiceLoop`. Silence starts
  on the first false frame, so `N` false frames expose `(N - 1) * 30 ms`, not
  `N * 30 ms`.
- Replay all commits, including a second turn after an internal premature
  commit. A case is valid only with exactly one commit, no pre-final commit,
  and—for incomplete fixtures—no commit before ground-truth end + 2.5 s.
- Compute endpoint latency as commit sample clock minus the independently
  pinned corpus speech-end clock. Invalid turns never enter percentiles. All 13
  fixtures (6 complete, 4 incomplete, 3 pause-heavy), all four phases, and all
  36 complete/pause latency cells must be present for a grid point to pass.
- Retain full model probability for decisions and round only JSON presentation.

This grid was written before the retained runs, but it has no independently
timestamped or immutable preregistration receipt. It is therefore a declared
exploratory grid, not a preregistered experiment.

## Baseline parity gate

The direct replay is not the PipeWire rig. Before its sweep can nominate even
an in-sample candidate, the `(confidence=.50, silence=.20, phase=0)` replay must:

- reproduce all 13 per-case validity flags, invalid reasons, defect flags, and
  commit counts; and
- reproduce every commit's offset from its own pinned final-speech clock and
  every applicable valid endpoint latency to within 60 ms. (The direct replay
  and captured rig have different recording-clock origins, so raw absolute
  clock comparison would be invalid.)

If this fails, the artifact is only a direct-fixture sensitivity study. It may
diagnose model/policy behavior but cannot select a production setting.

## Two-stage diagnostics

Separately report, outside grid selection:

- a true unconditional 0.85 s irreversible timer;
- one SmartTurn classification at confidence 0.5 followed by a 0.85 s silence
  timeout (it does not repeatedly reassess semantic stability); and
- an incomplete-fixture-label diagnostic that forces only the four known
  incomplete cases onto the 2.5 s timeout.

Each also records a hypothetical acknowledgement trigger at 0.20 s. It
separates acknowledgements canceled before an endpoint commit from
acknowledgements that survived a commit and were later contradicted by resumed
speech. No provisional audio or task-admission path is implemented here. The
fixture-label diagnostic is neither an opportunity-level nor a general oracle
and can never pass or nominate a production policy.

Latency percentiles are computed only over semantically valid complete/pause
cells. They are survivor-biased diagnostics whenever any such cell is invalid;
they become gateable only when the separately reported latency-completeness
condition is true.

## Evidence ceiling and next required experiment

This is post-selection calibration on Piper audio already used to find the
defect. It has no ASR transcript, human speaker, room/noise/AEC, network,
provisional response implementation, task executive, robot, or hardware.

Any nomination must be frozen before one-shot evaluation on untouched human
speakers, utterances, pause lengths (including >2.5 s), frame phases, SNR/noise,
room impulse responses, and resumed-speech cancellation. Only then should a
candidate enter the corrected virtual rig; mounted mic/speaker/AEC evidence is
still required afterward.
