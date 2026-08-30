# DMC-2 independent verdict

## Verdict

**PASS for the three individual production seams; NOT EVALUABLE / RED for
their end-to-end composition; NO-GO for physical motion.**

The PASS is appropriately narrow. Parcel's executive rejects stale/wrong
execution tuples and fails unverified success closed. Its dialogue reducer
rejects unauthenticated, mismatched, out-of-order, stale, and replayed
receipts. Its terminal-claim license rejects fabricated or unrelated evidence.
Those conclusions survived two complete deterministic runs and a verifier
that did not call the product implementations.

This corrects DMC-1's false truthfulness inference, but it does not prove that
Model B is truthful in production. There is no shipped bridge from executive
results to authenticated dialogue receipts, and the current receipt schema
cannot represent the full task identity or interruption lifecycle. A model
can only narrate what the local system exposes; today that exposure is
incomplete.

## Required production change before Model-B promotion

Add one local `ExecutionNarrativeEventV1` minted at the executive/runtime
boundary with at least:

```text
event_id, task_id, plan_revision, step_id, attempt,
mission_id, action_id, status,
source_epoch, speech_generation,
issued_at, evidence_refs, resume_parent_task_id
```

Statuses must include accepted, started, progress, blocked, replanned,
suspended, resumed, succeeded, failed, and cancelled. The reducer must support
an explicit task stack rather than one pending action. Model B may propose
wording, but terminal and resume claims must be licensed only from this event.

Then repeat DMC-2 through the actual bridge with restart replay, late old-step
results, barge-in generation changes, suspend/resume, parent/child task stacks,
and transport loss/reorder. Until that passes, keep hosted speech advisory and
keep all learned control heads proposal-only.
