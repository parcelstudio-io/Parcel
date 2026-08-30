# Runtime journal composition hardening

Date: 2026-08-29  
Evidence tier: guarded desktop software tests; no provider, audio, gateway,
robot, or motion call.

## Change

`RobotRuntime` now keeps its existing bare `TaskExecutive` as the authoritative
task API and constructs a `JournalOnlyNarrativeRuntimeV1` observer beside it.
Every runtime control tick polls the executive's bounded owner-authored journal,
authenticates the exact transition tuple with a process-local key, runs the
deterministic Model-B reducer, and queues bounded `ModelBNarrationFrameV1`
values. A journal gap, authentication/lifecycle failure, or capacity overflow
latches this optional lane closed and clears pending wording frames; it cannot
stop or authorize the executive, planner, control manager, gateway, or body.

The frames are available only through
`RobotRuntime.drain_execution_narrative_frames()`, and the disarmed lane's
status is exposed in the runtime snapshot. Nothing sends those frames to
Realtime or a speaker.

## Guarded verification

```text
26 passed in 2.29 s
```

The selection covered the new journal-only runtime unit tests, the DMC-4
bridge, product runtime brain integration, and adjacent executive tests. It
checks exact accepted/started/succeeded ordering, verified terminal facts,
non-actuation, one-shot drain, visible status, bounded overflow, and that a
narration fault does not block an authoritative task from succeeding.

## Remaining red seams

- no live-session authentication or binding to the actual speech-generation
  epoch;
- no persisted journal cursor or restart recovery;
- no provider/context injection, utterance policy, cancellation/backpressure,
  or audio output;
- no runtime binding for DMC-4's optional separate-child-to-suspended-parent
  resume lineage (current same-task suspend/resume transitions are journaled);
- no multiprocess trust boundary or production key service; and
- no Go2/Orin, network, or hardware evidence.

This closes the former “runtime never drains the journal” source gap only up to
deterministic, disarmed Model-B frames. It does not make conversational motion
fluid or physically mount-ready.
