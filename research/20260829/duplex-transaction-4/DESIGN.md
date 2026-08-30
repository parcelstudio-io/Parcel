# DMC-4 preregistration: authoritative executive transition journal

Date frozen: 2026-08-29  
Status: **DESIGN FROZEN BEFORE IMPLEMENTATION**  
Physical authority: none; this experiment may not publish motion commands or
change the physical readiness verdict.

## Question

Can the production `TaskExecutive` expose every accepted state mutation as an
immutable, ordered transition recorded under the executive's own lock, so the
execution-to-Model-B bridge never infers an event by comparing snapshots and
never silently loses a timeout, retry, precondition wait, resource wait,
empty-plan terminal, dispatch, interruption, suspension, resumption,
replacement, result, or dispatch-failure transition?

DMC-3 composes the public-call outcomes that already carry enough lineage. It
deliberately does not narrate silent `tick()` mutations because snapshot
comparison outside the authority owner is not an acceptable provenance source.
DMC-4 tests the missing owner-authored journal rather than weakening that rule.

## Frozen architecture

1. `TaskExecutive` owns a bounded append-only in-memory journal and increments
   one process-local transition sequence while holding its existing `RLock`.
2. Each journal item is immutable and contains the exact task, plan revision,
   plan digest, step, attempt, skill, prior state, resulting state, accepted
   disposition, detail code, and any verified facts/evidence that licensed the
   transition. It contains no prose and no actuator handle.
3. Every accepted mutation is appended at the mutation site. Rejected, stale,
   or no-op requests append nothing. Repeated unchanged wait observations do not
   create event spam.
4. A consumer reads by exact sequence/cursor. If its cursor predates the oldest
   retained item, overflow is explicit and consumption fails closed. It may not
   recover by inspecting a task snapshot.
5. `NarratingTaskExecutiveV1` maps owner-authored journal items one-for-one to
   authenticated `ExecutionNarrativeEventV1` records. It does not compare
   before/after snapshots to decide that a transition happened.
6. The existing deterministic Model-B consumer remains the only component that
   licenses a wording frame. Invalid success input that the executive converts
   to failure advances the authenticated stream silently and licenses no prose
   from the bad success claim.
7. The journal and narration surfaces remain proposal/fact only. They expose an
   explicit `authorizes_actuation == False` property and import no Unitree,
   gateway, controller, socket, Realtime, or provider client.

## Frozen transition inventory

The acceptance test must exercise all of these mutation families:

| family | required owner-authored outcomes |
|---|---|
| submission | accepted queued task; capacity/prior-active rejection emits none |
| replacement | immediate activation; deferred replacement; checkpoint activation; after-step activation |
| tick | dispatch; timeout-to-retry; timeout-to-failed; first precondition wait; first resource wait; empty/all-steps completion if constructible |
| report | progress; step success; task success; retry; failure; cancellation; pending interruption; invalid-success-to-failure |
| dispatch failure | retry and terminal failure |
| interruption | immediate cancel; checkpoint wait; suspend; no-op/overlap emits none |
| explicit lifecycle | suspend; queued resume; running resume; rejected resume emits none |

If validation makes an empty executable plan impossible, the result must say
`NOT_CONSTRUCTIBLE` with the enforcing code pointer; the evaluator may not
manufacture an invalid plan or silently omit the row.

## Hypotheses and gates

### H1 — completeness and exact-once lineage

For every constructible family above, run at least 64 independently identified
cases (at least 1,024 accepted mutations overall). The independently generated
expected-transition ledger must equal the journal ledger by exact sequence,
task/revision/step/attempt/plan digest, before/after state, disposition, detail,
fact/evidence identity, and multiplicity.

**Pass:** zero missing, extra, duplicate, reordered, or lineage-mismatched
transitions; zero journal rows for rejected/no-op calls.

### H2 — bridge composition

Consume all H1 journal rows through the production authentication and Model-B
reducer, including parent interruption, child task, child completion, resume
offer context, and parent resume.

**Pass:** every eligible owner transition yields exactly one authenticated event
and one accepted consumer transition; expected silent rows yield no wording
frame but advance continuity; zero false terminal/progress frames; exact replay
is rejected; every event preserves task/revision/step/attempt/epoch/speech
generation and parent lineage.

### H3 — gap, overflow, and corruption fail closed

Exercise at least 256 cases covering skipped cursor, overwritten cursor, queue
overflow, duplicate, reordered, stale epoch, stale speech generation, expired,
future-issued, tag corruption, task/revision/step/attempt/plan/action mutation,
fact/evidence mutation, and post-terminal transition.

**Pass:** all are rejected or reported as an explicit non-narratable gap/overflow;
consumer state is unchanged for unauthenticated/corrupt input; no snapshot-based
recovery and no wording frame.

### H4 — concurrency and boundedness

Run at least 32 producer threads over disjoint tasks while one consumer drains by
sequence. Repeat with a deliberately undersized journal to force overflow.

**Pass:** normal-capacity sequence is unique and contiguous with exact expected
cardinality; bounded capacities are respected; forced overflow is detected
before any post-gap event is narrated; no deadlock; normalized trace and chain
root match across two fresh runs; peak RSS is reported.

### H5 — non-actuation and regression

Static-import and object-surface checks must find no actuator/gateway/vendor/
network/provider handle reachable from journal, authenticator, bridge, or frame.
Run the focused executive/narrative tests and the broader guarded brain/runtime
selection.

**Pass:** all non-actuation checks pass and no prior test regresses.

## Methodology controls

- Freeze implementation and evaluator hashes before either evidence run.
- Use a separately authored oracle ledger; never score by rereading the journal
  and declaring it correct.
- Run twice from fresh processes; normalize only documented nondeterministic
  clock/RSS fields; compare trace and hash-chain roots.
- An independent verifier recomputes counts, sequence continuity, transition
  legality, event identity/authentication, exact-once mapping, resource bounds,
  and digests from raw artifacts.
- A tamper test must modify at least one result scalar, one raw journal row, one
  authenticated event, one source file, and one manifest hash; every mutation
  must be detected.
- Preserve all failed/aborted attempts with an amendment. Do not tune against an
  evidence set after it has been opened.
- All pytest execution uses the Parcel guard and avoids the live owner stack.

## Decision rule

`DMC4_COMPOSED_PASS` requires H1–H5 and both fresh-run/verifier/tamper checks.
Any missing transition family, inferred snapshot event, unreported overflow,
false terminal/progress frame, sequence discontinuity, test regression, or
actuation/network dependency yields `DMC4_REFUTED`.

Even `DMC4_COMPOSED_PASS` establishes only a desktop software transaction
property. It does not establish conversation quality, navigation competence,
physical sensing, Go2/Orin timing, braking, human safety, or mount readiness.
