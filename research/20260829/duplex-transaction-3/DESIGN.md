# DMC-3 — composed executive-to-Model-B event bridge

**Status:** frozen before implementation  
**Date:** 2026-08-29  
**Evidence tier:** product-contract process tests and deterministic replay; no
physics, microphone, hosted-model, gateway, Orin, or robot evidence

## Problem

DMC-2 established that `TaskExecutive.report`, authenticated receipt
reduction, and terminal-claim licensing are individually fail-closed. It also
found that they are not composed: runtime can accept an execution result
without producing a task-lineage-bound fact that Model B can safely narrate.

DMC-3 tests the smallest production correction. A local bridge must delegate
the authoritative transition to `TaskExecutive` and may mint an
`ExecutionNarrativeEventV1` only from the accepted disposition. The event is
read-only and authenticated for a local Model-B consumer. It never grants
motion, never declares an unverified observation, and never lets hosted prose
establish completion.

## Frozen contract

Every event carries:

```text
event_id, event_sequence,
task_id, plan_revision, step_id, attempt,
mission_id, action_id, action_name, plan_sha256,
status, source_epoch, speech_generation,
issued_at_monotonic_ns, claimable_until_monotonic_ns,
verified_facts, evidence_refs, detail_code,
resume_parent_task_id
```

`event_id`, `mission_id`, and `action_id` are content-derived. The authenticated
wrapper is process-local evidence and explicitly cannot authorize actuation.
Model B receives a deterministic tense/constraint frame generated from the
verified event; a hosted model may choose wording only.

Statuses are `accepted|started|progress|blocked|replanned|suspended|resumed|
succeeded|failed|cancelled`. A `succeeded` event must retain at least one
executive-verified fact. Reaching a search location never implies finding the
searched object unless an independent fact says so.

## Frozen hypotheses and gates

### D3-H1 — accepted transition completeness

For 256 independently generated exact task executions, every accepted
executive lifecycle transition emits exactly one authenticated event with the
exact task/revision/step/attempt and authoritative post-transition status.
No event may claim success without the fact that satisfied the plan's frozen
success condition.

### D3-H2 — corruption silence

Across at least 256 fresh corruptions covering unknown task, wrong revision,
wrong step, wrong attempt, late old-step result, post-terminal result, missing
success fact, altered event payload/tag, duplicate event, event-sequence
regression, wrong source epoch, future event, expired event, and old/new speech
generation, all invalid inputs are rejected or converted to an honest failure.
They must mint zero false `succeeded` events and license zero narration frames.

### D3-H3 — interruption stack semantics

At least 128 deterministic door → sofa/keys → resume trials must preserve:

- the door task becomes `suspended`, never succeeded/cancelled;
- the child sofa task starts under a distinct identity;
- sofa arrival and keys observation are separate verified facts;
- no “keys found” content exists when only sofa arrival is verified;
- completion offers the exact suspended parent; and
- resume returns that exact parent task, revision, step, and attempt.

Every lifecycle event must be accepted once in order and rejected on exact
replay. Any old speech-generation event must be rejected after a generation
advance.

### D3-H4 — runtime composition and regression

The product runtime's brain loop must route `submit`, `replace`, `tick`,
`report`, `dispatch_failed`, suspend/interrupt, and resume transitions through
the bridge rather than minting events from snapshots after the fact. A focused
source/behavior test must prove the route, and the existing brain/runtime plus
mount-boundary regression must stay green.

**Promotion gate:** H1–H4 all pass twice with identical normalized trace
digests and an independent verifier that does not invoke the bridge. A pass
promotes only the local transaction seam to continued simulation/HIL use.

## Procedure

1. Implement the pure event/authentication/consumer contract and bridge.
2. Add fail-closed unit and runtime integration tests.
3. Generate a frozen case manifest from seed `20260829`; retain full input,
   disposition, event, consumer result, and before/after state.
4. Run twice in isolated processes and independently recompute inventory,
   identity derivations, ordering, expected accept/reject decisions, and trace
   digest.
5. Run guarded focused and mount-boundary regressions.

## Unsupported claims

Passing DMC-3 does not measure free-form language quality, acoustic duplex,
owner recognition, perception, navigation success, collision avoidance,
locomotion, provider delivery, Orin timing, or robot safety. It closes a data
authority seam; autonomous physical motion remains **NO-GO**.
