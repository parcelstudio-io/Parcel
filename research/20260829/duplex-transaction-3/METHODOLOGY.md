# DMC-3 methodology

## Scope and frozen inputs

This experiment implements and evaluates only the local transaction seam in
`DESIGN.md`. It uses Parcel's production `TaskExecutive`, the production
`ExecutionNarrativeEventV1` bridge contract, a process-local HMAC channel, and
the deterministic Model-B constraint consumer. It makes no hosted-model,
gateway, simulator, owner-data, or robot calls.

The case manifest was frozen at seed `20260829` before the retained runs. It
specifies 256 exact H1 executions, 256 H2 corruptions (16 occurrences of each
of 16 corruption classes), and 128 H3 interruption-stack trials. A fixed
monotonic clock, source epoch, speech generation, and event lifetime remove
wall-clock variation.

## Production contract under test

The bridge holds one lock around delegate and mint. It calls the executive
first and mints only for an accepted typed disposition or a returned dispatch.
Rejected and exceptional calls mint nothing. Event, mission, and action IDs are
content-derived. Success retains the exact `VerifiedFact` tuple supplied to
the accepted executive report. The authenticated wrapper, consumer frame, and
bridge all explicitly report `authorizes_actuation == False`.

The consumer is an immutable reducer. It verifies authentication, source
epoch, speech generation, event ID, global sequence, freshness, task lineage,
parent lineage, and lifecycle order before committing state. Invalid input
returns the identical state object and no frame. Under the frozen continuity
amendment, a bad success claim already converted by the executive to the
authenticated, contiguous `unverified_success_claim` failure is consumed into
the task/sequence state but produces no frame. Exact replay is then a duplicate;
the next contiguous valid event remains consumable.

## Trials

- H1 submits and dispatches a one-step task, records progress, then reports the
  frozen `motion_stopped` success fact. The trace retains every input,
  disposition, event, consumer frame, and before/after state.
- H2 rotates evenly through unknown task, wrong revision/step/attempt, late
  old-step, post-terminal, missing success fact, payload/tag alteration,
  duplicate, sequence regression, source epoch, future/expiry, and old/new
  speech-generation cases. Each corruption has a fresh task/event identity.
  Every missing-success trial additionally replays the silently consumed event
  and submits a distinct valid task at the next sequence to prove continuity.
- H3 suspends a door task, creates a distinct sofa/keys child with the exact
  parent link, records sofa arrival and keys observation in separate progress
  events, completes the child, and resumes the original door lineage. Every
  event is consumed once, replayed once, then the final old-generation event is
  retried after an explicit generation advance.

## Oracle separation and repeatability

`run.py` records observations but contains no pass/fail oracle. The stdlib-only
`verify_results.py` imports no Parcel code. It independently rebuilds the case
inventory, SHA-256 identity derivations, lifecycle expectations, fact
separation, corruption outcomes, replay decisions, trace-chain root, and
normalized trace digest. `tests/test_duplex_transaction_v3.py` tampers with a
retained success fact and proves the independent oracle rejects it.

The original two full suites are retained unchanged. Two amended full suites
are run under distinct artifact names in separate Python processes. Promotion still
requires H4; identical H1-H3 replay is necessary but not sufficient.

## Known architectural gap

`TaskExecutive.tick` can mutate timeout, recovery, precondition, resource-wait,
and empty-plan completion state without returning a typed transition. DMC-3
forbids minting from snapshots after the fact. The bridge therefore emits only
for a returned dispatch and labels H4 `PARTIAL_RED`; it does not pretend the
silent branches are covered.
