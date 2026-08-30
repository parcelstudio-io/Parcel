# Acoustic-loop v1 independent audit and remediation — 2026-08-29

Status: completed code/evaluator audit; retained virtual rerun is red. This is
not Go2, Orin, room, human-speech, AEC, physical STOP, or actuator evidence.

## Bottom line

The historical 5/9 score was not a valid capability score. Endpointing sampled
the loop clock after the whole WAV, mixed-channel power subtraction could not
isolate robot STOP, the acknowledgement reply lost its 22.05 kHz WAV rate, and
prosody compared different origins with reusable matches while observing no
motion. The revised runner fails closed on those defects.

The retained v2 rerun is
[`acoustic-eval-v2/results.json`](acoustic-eval-v2/results.json): 25 cases,
223.40 s, clean teardown, 6 pass / 3 fail / 2 `not_measured`. It found 4/13
endpoint-validity failures, virtual-audible acknowledgement p50 0.790 s,
audio-transport accent match 0.9286, and no valid acoustic-STOP or physical
motion-sync measurement. See the
[`results`](acoustic-eval-v2/RESULTS.md) and
[`verdict`](acoustic-eval-v2/VERDICT.md).

## Independent source findings

### Endpointing

The old runner called `rig.play_file()` synchronously and then read
`loop._elapsed_s`; trailing fixture silence therefore inflated its ~0.79 s
number. It stopped observing after the first commit and classified only
`ep < 0` as cutoff, allowing a commit inside a real pause to disappear when
speech resumed.

V2 records every synchronous commit on the loop sample clock. Six complete
cases were valid at 0.238–0.282 s, but `pause_01` and `pause_03` each committed
prematurely and then committed again. `incomplete_02` and `incomplete_04`
committed roughly 0.25 s after their final speech instead of holding. The
valid ep50 therefore passes while the 0.3077 cutoff and commit-validity rates
correctly fail.

### Barge-in and STOP

The old `sqrt(mixed²-owner²)` estimate assumes synchronized unit-gain,
identically filtered paths. PipeWire routing/resampling violates that model;
the retained residual followed owner-utterance duration. It also tested generic
VAD interruption, not recognition and latching of the spoken word STOP.

V2 retains the subtraction only as a named diagnostic. Because the rig has no
isolated robot-output channel, acoustic cessation is `not_measured`. Detection
and queue-flush measurements remain separately reported.

### Acknowledgement

The old runner stripped a 22.05 kHz reply WAV header and sent the PCM through a
16 kHz raw default, stretching its leading silence. V2 retains the header and
labels three clocks: enqueue attempt, first output-buffer write attempt, and
virtual monitor onset. The virtual-audible p50 is 0.790 s and fails. The first
query takes the 2.5 s incomplete-turn branch; the warm monitor gap includes
reply leading silence and is not a device-latency claim.

### Prosody

The old runner removed leading silence from captured audio but not source
accent timestamps, permitted multiple expected accents to reuse one observed
accent, and never constructed `BeatLayer`. V2 aligns each track to its first
audible sample and uses maximum-cardinality monotonic one-to-one matching.
The 13/14 result measures audio transport only; physical motion sync is
`not_measured`.

## SpeakerSink remediation

The source audit also found independent playback races:

- cross-thread PortAudio lifecycle calls and a shared interrupt latch allowed
  unsafe ownership and old-generation ABA behavior;
- the legacy callback lost the generation and captured clock;
- callback work included application locks/queueing/logging/time/allocation;
- abort and re-entrant close failure paths could drain or strand workers;
- the first full real-rig attempt exposed a post-EOF callback that exhausted
  the buffer iterator and was mislabeled as a device failure.

`SpeakerSink` now uses a one-way cancellation event per generation; a small
callback copies prebuilt blocks and the ordinary worker owns construct/start/
abort/stop/close. A frozen `SpeakerWriteAttempt` carries generation, token, and
captured write-attempt clock to a separate observer thread. EOF is idempotent
for callbacks already in flight. The runtime uses that new hook, binds the
generation to the owning turn, serializes begin/barge-in/effect delivery, rejects
stale events, and uses the captured clock for both the latency trace and beat
anchor. The clock is explicitly a buffer-write attempt, not device acceptance,
DAC presentation, or audibility.

Focused guarded coverage passed for the callback race/lifecycle set, runtime
generation/timestamp boundary, and evaluator-validity rules. A real PipeWire
null-sink smoke after the EOF repair observed a write attempt, reached inactive,
and logged no playback failure. Full selection and commit-gate results are
recorded in the final August 29 assessment rather than inferred here.

## Honest remaining limits

The callback still runs Python under the GIL, calls `Event.is_set()`/`next()`,
performs bounded preallocated NumPy copies, and uses PortAudio callback
exceptions. It is not hard real time. Cancellation can leave the already
in-flight ~50 ms device block, streams still open per synthesized chunk,
injected players cannot be preempted inside their callable, and no physical
presentation or actuator clock exists.

Before mounting audio, run human pause/resumption and SNR cases; an isolated
same-clock owner/robot capture; through-air spoken STOP to the local latch;
mounted AEC double-talk tests; warm/cold device-presentation latency; and
speaker-to-motion timing with encoder/video evidence.
