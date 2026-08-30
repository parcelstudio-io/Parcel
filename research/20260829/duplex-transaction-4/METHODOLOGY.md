# DMC-4 methodology

Date: 2026-08-29  
Status: completed offline against the frozen preregistration  
Authority: non-actuating desktop software only

## Implementation under test

`TaskExecutive` owns a bounded `deque` of immutable
`ExecutiveTransitionV1` records and assigns their process-local sequence while
holding the same `RLock` that owns the task mutation. Exact-cursor reads return
`ok`, `overflow`, `cursor_ahead`, or `gap`; a non-`ok` read never returns a
guessed suffix. The mutation sites cover submit/replace, tick dispatch and
wait/timeout arms, report outcomes, dispatch failures, interruptions, and
explicit suspend/resume operations.

`NarratingTaskExecutiveV1` has an explicit facade API and one wrapper lock
around each owner call plus journal mapping. It derives events only from
`ExecutiveTransitionV1`, authenticates an entire suffix before committing it,
and advances its cursor only after the bounded event queue can accept the whole
suffix. Journal or event-queue discontinuity latches a visible fault. There is
no snapshot recovery. Exact child-to-parent mapping is accepted only when the
parent is already known from owner-journal state to be suspended.

The existing Model-B consumer consumes the authenticated invalid-success
failure silently: task state and event sequence advance to `failed`, no wording
frame is licensed, and exact replay rejects as already consumed.

## Oracle and populations

The runner authored its expected transition ledger independently at each
scenario action; it did not derive the expectation by rereading the journal.
It ran 64 named cases for each of seven transition families (448 cases), 64
parent/child interruption cases, 256 corruption cases across 20 classes, and
two 32-producer concurrency cases. Negative-call metadata separately retained
capacity/prior-active rejection, stale dispatch replay, overlap, and lifecycle
no-op journal deltas so equality could not conceal an unexercised rejection.

The independent verifier uses only the Python standard library. It recomputes
case inventory, exact expected-versus-observed ledger equality, transition and
event identities, one-to-one mapping, parent lineage, consumer continuity,
replay rejection, corruption reasons, boundedness, hash-chain roots, source
hashes, and normalized trace hashes. Two runs were launched from fresh Python
processes. Only environment and RSS were excluded from the normalized trace;
no scenario or semantic field was normalized.

The five-part tamper check resealed altered evidence before verification where
appropriate. It changed a population scalar, raw journal row, authenticated
event, manifest hash, and a copied frozen source file. This tests semantic
detection instead of relying only on the outer result digest.

## Frozen files and commands

`source_manifest.json` was frozen and validated before `run_a.json` or
`run_b.json` was opened. Its SHA-256 is
`f5519d19248c1fe54a7f8ccd4c33516ea1051a24daf58cedf8df263f5ab74699`.
All pytest commands used Parcel's required guard. Focused coverage was the
DMC-4, execution-narrative bridge, and executive test set. The broader
selection covered brain compiler/contracts/executive/observations/router/
adapter/safety/validator, prior duplex tests, companion brain evaluation,
motion seam, preemption, runtime activation/assets/backend/brain/voice wiring,
and social-progress runtime tests.

No network, provider, Realtime, owner-service, runtime-motion, Unitree, gateway,
or physical-robot call was made. Provider calls: 0. Experiment cost: $0.

## Non-constructible row

`tick_empty_all_steps_completion` is retained as `NOT_CONSTRUCTIBLE` because
`PlanIR.__post_init__` requires at least one step and `TaskExecutive.report`
commits final accepted success terminally. `TaskExecutive.tick` now treats a
non-terminal record without a step as a defensive invariant violation rather
than manufacturing a success transition.

