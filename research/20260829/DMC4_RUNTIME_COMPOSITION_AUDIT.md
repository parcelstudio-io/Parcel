# DMC-4 runtime-composition audit

> **Post-audit update (2026-08-30):** the frame-lineage loss and missing
> drain-time expiry findings below were repaired and regression-tested after
> the fresh Sol Ultra review. Commit-time timestamping, persistent cursors,
> independently authenticated live speech generation, provider/audio delivery,
> acknowledgement, and authoritative separate-child resume lineage remain red.
> See [`POST_ULTRA_REMEDIATION.md`](POST_ULTRA_REMEDIATION.md).

Date: 2026-08-29. Scope: read-only review of the maintained DMC-4 source and
its additive `RobotRuntime` observer. This does not alter the retained DMC-4
result or claim a live provider test.

## Verdict

**The narrow journal-to-process-local-frame seam is credible; production
narration is red.** The code is deliberately non-actuating and fail-closed on
continuity/authentication/capacity errors. It does not yet establish freshness
from authoritative commit to speech, restart delivery semantics, live-session
lineage, or anything audible.

## What is supported

- `TaskExecutive` owns a bounded, contiguous journal and appends immutable
  transition rows under its lock. Cursor gaps/overflow are explicit rather than
  reconstructed from snapshots.
- The journal-only bridge maps owner rows, authenticates them, checks sequence
  and task lifecycle, and emits deterministic `ModelBNarrationFrameV1` values.
- `JournalOnlyNarrativeRuntimeV1` has no provider, socket, audio, or actuator
  handle; any lane fault clears pending frames without stopping or authorizing
  the executive.
- Frozen DMC-4 and post-maintenance verifiers reproduce the source-level trace;
  the focused additive runtime selection covers the composed disarmed seam.

## Blocking production gaps

1. **Commit-to-speech freshness is not represented.**
   `ExecutiveTransitionV1` has no commit timestamp. The bridge sets
   `issued_at_monotonic_ns` when it polls and derives expiry from that later
   time. `ModelBNarrationFrameV1` then drops issue/deadline/session lineage, and
   `drain_frames()` performs no expiry check. A transition delayed before poll
   or a frame delayed after consumption can therefore look fresh.

2. **Restart delivery is undefined.**
   Executive state/journal, bridge read cursor, consumer cursor, queued frames,
   provider submission, and provider/audio acknowledgement are process memory.
   A restart may replay or lose work; there is no persisted outbox or explicit
   read → consume → provider-ack → audible-ack cursor chain.

3. **Live and parent/child lineage are absent.**
   Runtime creates a random process-local source epoch and key and fixes speech
   generation at zero. It bypasses the facade that records optional
   child-to-suspended-parent lineage, so it truthfully advertises that binding
   as false. There is no authoritative `resume_offer` transaction through the
   provider/audio boundary.

4. **Frames are too small for a safe provider contract.**
   They omit plan revision, step, attempt, source/speech epoch, issue/deadline,
   receipt/evidence references, and detail code. Those values exist upstream,
   but the exposed drain surface cannot let a provider or audible-ack ledger
   prove exact lineage or reject a stale frame.

5. **Lifetime bounds need compaction semantics.**
   Consumer state rejects a 257th lifetime task and a 4,097th remembered event.
   Terminal tasks/events are not compacted into a persisted checkpoint, and
   reusing a task ID is rejected. Those are safe local failures, not a durable
   service design.

6. **Future provider work must leave the control critical path.**
   The current non-speaking poll runs before `_dispatch_active()` in the same
   runtime tick. It is bounded local work today, but provider submission,
   persistence, or audio must be supervised asynchronous work after motion
   dispatch; it must never delay motion or STOP.

## Required production transaction

Persist the executive transition at commit with source/process epoch and a
monotonic-plus-boot identity; transactionally append an outbox row containing
the full task/revision/step/attempt/evidence tuple and deadline. Advance
independent read, consume, provider-ack, playback-generation, and audible-ack
cursors idempotently. Expire before each stage, cancel on barge-in/generation
advance, and recover from restart without inventing or silently skipping a
claim. Compact only behind an acknowledged persisted checkpoint. Provider
wording remains unable to mutate the executive or authorize motion.

## Code pointers

- transition schema/journal: `src/parcel_robot/brain/executive.py`
- bridge poll-time issue/TTL: `src/parcel_robot/brain/execution_narrative_bridge.py`
- consumer/frame schema and lifetime bounds:
  `src/parcel_robot/voice/execution_narrative.py`
- process-local observer/drain:
  `src/parcel_robot/voice/execution_narrative_runtime.py`
- runtime ordering: `src/parcel_robot/runtime.py`
