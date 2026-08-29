# 2026-08-28 — generalized agency and movement

This research day separates two questions that are easy to conflate:

1. can the companion compose and revise semantic skills; and
2. can the Go2 execute a broad, robust, expressive movement vocabulary on
   terrain it did not see during training?

The first received narrow authored-symbolic evidence in `sim-plan-1/`. The
second remains unimplemented and unproven. Nothing in this directory
authorizes physical motion.

## Artifacts

- `GENERALIZED_AGENCY_REPORT.md` — current capability boundary, proposed
  four-layer architecture, three-timescale learning loop, frozen next
  experiments, 30/60/90-day implementation path, and budget allocation.
- `sim-plan-1/` — deterministic proposal-only comparison of the bounded
  affordance planner with a fixed-template baseline on 29 authored held-out
  symbolic missions.
- `sim-plan-2/` — additive observable-bound planner regression: 29/29 exact
  dispositions on the V1 matrix, explicitly not a fresh generalization test.
- `rl-env-readiness/` — executable Go2 MJCF audit that refuted the current
  `Go2Env` as a generalized-locomotion training/evaluation substrate (2/9
  gates passed).
- `LIVING_BEHAVIOR_MODEL_REPORT.md`, `SIM_TRAINING_PLAN.md`, `literature/`, `behavior-model-1/`, `feedback-learning-1/`, `humor-signal-1/`, `duplex-speech-local-1/` — parcel-0e's 12-hour wave on a trainable full-duplex voice-steerable behavior model (learn chuckle-if-funny / look-back-when-lost from the state of the world) and the sim/training plan; physical motion still NO-GO.

## Decision

Continue with V2 in **runtime shadow mode only** after a fresh procedural
evaluation. Replace the refuted RL stub with the official Go2 Isaac Lab ->
MuJoCo loop, then run the preregistered adaptive-locomotion,
motion-composition, and terrain-planning evaluations described in the report.

Physical/general locomotion status: **NO-GO**.
