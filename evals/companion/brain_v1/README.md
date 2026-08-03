# Parcel companion brain-v1 integration suite

This is a frozen, offline contract-boundary suite for Parcel's split
conversation/planning architecture. It runs without a model server, simulator,
network, ROS, or robot. Its purpose is to catch regressions between four
production boundaries:

1. the final transcript becomes a strict `IntentFrame` with exact transcript
   provenance;
2. a strict `PlanIR` is bound to that turn and admitted against a camera/LiDAR
   `ObservationSnapshot`;
3. `TaskExecutive` owns resources, revisions, retries, and interruption timing;
4. `SemanticTaskRuntimeAdapter` dispatches only bounded semantic skills and
   returns typed, controller-owned completion facts.

Run it from the repository root:

```bash
.parcel/bin/python -m evals.companion.run_brain_v1
.parcel/bin/python -m evals.companion.run_brain_v1 --compact
.parcel/bin/python -m evals.companion.run_brain_v1 \
  --case sidewalk_inside_boundary --output /tmp/brain-v1.json
```

The command exits zero only when every selected case matches its frozen
expected boundary outcome. The JSON output follows `report.schema.json` and
contains both per-case outcomes and deterministic count metrics. It deliberately
does not report wall-clock latency: timing a tiny fixture process would not
measure model, perception, control, or speech latency and would invite a false
performance claim.

## Coverage

The 15 integration cases cover:

- semantic `inside` dispatch for a grounded sidewalk;
- semantic `near` dispatch for a grounded lamppost;
- one bounded, local owner orbit;
- five bounded steps away from the owner;
- camera-track-only behind-owner formation;
- a two-step vocalize-and-hold task;
- a correction that replaces an active plan only at a checkpoint and ignores
  the old revision's later terminal report;
- an explicit stop that cancels active base work immediately;
- an optional social reaction that defers while an active task finishes;
- rejection of an ungrounded sidewalk, stale LiDAR, unavailable owner heading,
  and a plan proposed during emergency stop;
- prevention of dispatch when emergency stop arrives after admission but before
  the next executive tick; and
- a failed navigation verifier producing no success fact.

`router_cases.jsonl` remains the smaller frozen grammar/provenance corpus. The
integration corpus starts after routing and exercises admission through typed
runtime feedback. Both corpora are useful: neither silently substitutes for the
other.

## Controller traces are not geometry

The fixtures contain terminal controller states such as `arrived`,
`completed`, and `holding_behind`. For navigation, `navigation_goal` also has to
match the grounded semantic target. These values emulate the *output contract*
of a trusted terminal verifier. They do not generate coordinates, calculate
distance to a lamppost, simulate collision avoidance, or assert that perception
was correct.

Consequently, a passing `sidewalk_inside_boundary` case means:

- the request, grounded snapshot, semantic plan, resources, and invariants were
  admitted;
- no raw velocity, joint target, model-authored priority, or coordinate reached
  the adapter;
- the executive did not accept completion before the adapter supplied an
  `inside(sidewalk)` fact tied to the active revision and attempt.

It does **not** mean a physical or simulated dog reached a sidewalk. That claim
belongs to the headless city task suite, where geometry and collision outcomes
are measured. Dynamic navigation robustness belongs to BARN/Habitat or another
adopted official evaluator. Unitree tracking and balance belong to hardware-in-
the-loop tests. Model generalization belongs to a separately versioned planner
corpus with real model outputs. The tiers should be reported independently.

## Frozen-data policy

`manifest.json` pins SHA-256 digests for:

- `router_cases.jsonl`;
- `integration_cases.jsonl`; and
- `report.schema.json`.

The runner verifies all three before executing any case and verifies both case
counts. Editing a corpus or schema without deliberately updating the manifest
makes the suite fail before evaluation. An expected outcome must never be
changed merely to accommodate a regression. A semantic contract change should
create a reviewed manifest update (or a new suite version), explain why the old
expectation is obsolete, and retain prior run artifacts for comparison.

## Report interpretation

`expected_boundary_outcome_accuracy` is exact expected-vs-actual agreement over
the selected cases. `fail_closed_expectation_accuracy` considers the cases that
are supposed to reject, suppress dispatch, fail without a fact, or cancel. The
remaining counters describe how much of the pipeline was exercised: parsed
contracts, admission decisions, executive submissions, semantic dispatches,
callbacks, polls, typed reports, verified facts, ignored stale reports, and
interrupts. `verified_facts_emitted` counts every adapter fact, including a
fact from an old revision that the executive correctly ignores;
`verified_facts_accepted` counts only facts on accepted step/task-success
transitions.

The report fixes `physical_navigation_episode_count` at zero and
`physical_navigation_success_rate` at null. Treating this suite's pass rate as a
navigation success rate, benchmark percentile, or production-readiness score is
an invalid comparison.
