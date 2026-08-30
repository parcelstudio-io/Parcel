# ACOUSTIC_LOOP_V1 — virtual audio-boundary evaluation

This Tier-1 suite measures selected audio-boundary behavior through uniquely
owned PipeWire null nodes. It has no air, room, human voice, physical
transducer, acoustic echo, AEC, robot, or actuator. It cannot authorize mounted
audio or motion.

Run:

```bash
source scripts/env-audio.sh
.parcel/bin/python -m evals.companion.acoustic_loop_v1.run_acoustic_loop_v1
```

The runner exits 0 only when every required gate passes and teardown is clean;
1 means a completed red or incomplete measurement; 2 means the rig was
unavailable. Use a unique `--node-prefix` for concurrent research runs.

## Measurement families

- **Endpointing:** records every commit at the synchronous callback on the
  microphone loop sample clock. Complete/pause-heavy cases require exactly one
  commit after final speech. Incomplete cases may remain open but may not
  commit before the full incomplete hold. Invalid cases never enter ep50/ep90.
- **Barge-in:** measures generic VAD detection and queue flush. The current
  monitor mixes owner and robot paths, so mixed-minus-owner subtraction is
  diagnostic only and acoustic robot-output cessation is `not_measured`.
  This is not spoken-STOP recognition or emergency-latch timing.
- **Duplex acknowledgement:** preserves WAV sample rate and reports enqueue
  attempt, first output-buffer write attempt, and virtual monitor-audible onset
  as different clocks. A scripted responder isolates the audio path from LLM
  latency.
- **Prosody:** compares source/captured accents on common utterance-local
  audible origins with monotonic one-to-one matching. It measures audio
  transport only; physical motion sync is a separate `not_measured` gate.

## Frozen pack and rig

`manifest.json` SHA-locks 22 audio fixtures, corpus metadata, result schema,
Silero/SmartTurn models, Piper voice/binary, and Whisper artifacts. The runner
refuses missing or changed inputs. Each run creates owned speaker and microphone
null nodes, resolves exact global port IDs, explicitly links them, and reaps
all child processes/nodes during teardown. `case_verdicts` is the determinism
surface; wall-clock values may jitter.

Required local prerequisites and the user-space PortAudio setup are documented
in [`scripts/env-audio.sh`](../../../scripts/env-audio.sh) and
[`docs/ACOUSTIC_BRINGUP_PLAN.md`](../../../docs/ACOUSTIC_BRINGUP_PLAN.md).

## Current evidence

Historical v1 JSON remains in `results/` for provenance, but its endpoint,
STOP, acknowledgement, and prosody interpretations were invalidated by an
independent measurement audit. The corrected retained run and diagnoses are in
[`research/20260829/acoustic-eval-v2/`](../../../research/20260829/acoustic-eval-v2/).
Do not quote a historical score as current capability evidence.

## Remaining tiers

Tier 2 needs mounted/through-air owner and robot channels on one clock,
physical speaker/microphone, AEC double talk, human speech, device presentation
timestamps, spoken STOP to the local latch, and actual BeatLayer/actuator
observation. Tier 3 needs consented owner sessions and broader accents, pauses,
noise, rooms, and tasks. Neither tier exists yet.
