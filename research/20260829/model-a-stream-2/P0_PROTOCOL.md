# MA-2-P0 teacher and causality probe protocol

Status: **FROZEN BEFORE IMPLEMENTATION OR ROLLOUT**  
Date: 2026-08-29  
Parent design: [`DESIGN.md`](./DESIGN.md), especially Sections 4, 11, 13,
14, and 17  
Authority: desktop research only; no socket, hardware, hosted-model, or motion
authority

This protocol instantiates only the 300-episode P0 requested by the parent
design. It does not train Model A and cannot satisfy H-MA2a--e. Its controlling
question is whether a causal observation/action/transaction substrate is valid
enough to justify a later corpus run.

## Frozen population

- Root seed: `20260829`, with independent SHA-256-derived namespaces.
- Ten geometry scene IDs: `scene-00` through `scene-09`.
- Five target roles in every scene: `door`, `sofa`, `bench`, `elevator`, and
  `keys`. Every role has one intended entity and two same-class distractors.
- Three task families: `plain`, `interrupt_now`, and `queue_resume`.
- Two independent repeats of the full `scene x target role x task family`
  cross product: exactly **300 episodes**, 20 per role/family stratum.
- The semantic target UUID and candidate order are independently derived and
  permuted. The teacher receives the exact opaque UUID plus an estimated
  relative pose from the observation adapter, never the scorer coordinate.
- The scene is a bounded, obstacle-free kinematic qualification venue. This is
  intentionally a data-path test, not evidence about obstacle avoidance,
  pedestrians, Go2 dynamics, stairs, elevators, or sim-to-real transfer.

## Frozen dynamics and teacher

- Period: 100 ms; maximum 240 frames for `plain`, 500 for interruption families.
- Applied world-frame command: `(vx, vy, vyaw)` with per-axis velocity limits
  `(0.70, 0.70, 1.0)` and acceleration delta limits `(0.12, 0.12, 0.20)` per
  frame. The final command is decimal-quantized to six places.
- The observation's robot pose has a deterministic per-episode localization
  bias bounded by 2 cm. Semantic relative estimates add a deterministic,
  entity-bound bias bounded by 2 cm per axis. No future noise sample is exposed.
- The deterministic teacher consumes only the serialized allow-listed policy
  payload. It applies proportional target-relative velocity, stops inside its
  estimated settle band, and has no import or callable route to simulator truth.
- Exact success is scorer-owned: correct task tuple, exact entity UUID, actual
  distance no greater than 0.30 m, speed no greater than 0.03 m/s, for three
  consecutive frames. Same-class distractors never count.
- Every transition persists requested, selected, admitted, and applied values.
  The primary label is the exact serialized `actuator_applied` mapping passed
  to `world.apply`.

## Frozen transaction sequences

All tasks are validated by the product `PlanValidator` and owned by the product
`TaskExecutive`.

- `plain`: submit -> dispatch -> verified exact-target result -> accepted
  terminal report -> locally signed narrative receipt.
- `interrupt_now`: dispatch parent -> accepted owner steering -> product suspend
  -> submit/dispatch child -> verified child terminal -> resume offer -> later
  explicit owner resume -> champion `request_resume_queued` proposal -> product
  resume/dispatch parent -> verified parent terminal.
- `queue_resume`: dispatch parent -> accepted queue steering -> submit child
  while parent keeps the base -> prove child waits on the product resource lock
  -> accepted owner interrupt -> product suspend -> child dispatch/terminal ->
  resume offer -> later explicit owner resume -> champion resume proposal ->
  product resume/dispatch parent -> verified parent terminal.

The local narrative bridge exists only for this experiment and signs the exact
task/revision/step/attempt, source epoch, sequence, speech generation, evidence
reference, and parent lineage. It is not a shipped production capability.

## Controlling Gate-0 conditions

The P0 result is `PASS_TO_CORPUS_DESIGN` only if every condition below holds:

1. Teacher exact mission success is at least 0.80 overall and at least 0.70 in
   every target-role/task-family stratum, with Wilson 95% intervals reported.
2. Exact-target terminal precision is 1.00; contacts, post-gate unsafe commands,
   and wrong-target terminal acceptances are all zero.
3. Label/application canonical equality is 100% over every transition.
4. Policy payloads contain exactly the frozen allow-list, no future timestamp,
   and no scorer/oracle/private coordinate field. A sentinel taint fixture must
   produce byte-identical payloads.
5. Product-executive transaction order is exact in 100% of episodes. No resume
   occurs without both an accepted child-terminal receipt and a later explicit
   owner-resume event.
6. A composed bridge fixture accepts a valid event and rejects, without consumer
   mutation, each of: wrong task, revision, step, attempt, duplicate, sequence
   regression, wrong epoch, expiry, post-terminal, unrelated evidence, and
   stale speech generation.
7. All 300 episode traces are complete and hash-chained. Thirty frozen episodes
   replay twice with identical normalized per-episode digests.
8. An independent standard-library verifier recomputes the gates, and a
   deliberate trace mutation makes it exit nonzero.
9. Scene/role and scene/task mutual information is at most 0.01 bit and every
   cross cell is present.

Any failure produces `INVALID_PRECONDITION`; no model training follows.

## Non-controlling learnability diagnostic

To answer whether the causal features contain an elementary predictive signal
without violating the parent design's “do not train a neural model” stop rule,
a closed-form ridge diagnostic is fit only after trace finalization:

- fit rows: scenes 00--07; held-out rows: scenes 08--09;
- inputs: current estimated target-relative `(dx, dy)`, the same values clipped
  to the teacher's proportional range, previous applied `(vx, vy)`, and a bias;
- labels: exact current applied `(vx, vy)` from the action ledger;
- report held-out MSE, variance-weighted R2, and velocity-direction agreement;
- never run the diagnostic closed-loop, use it for checkpoint selection, or
  call it Model A.

This diagnostic is evidence of label predictability only. It cannot establish
closed-loop control, temporal memory, executive-head learning, scene/task
generalization, or hardware readiness.

## Reproducibility and claim limits

The manifest must hash this protocol, the parent design, every P0 source/schema,
the imported product executive/contract/validator files, environment facts,
and the generated split inventory. Traces are canonical JSONL compressed with
the host `zstd` binary. The verifier may invoke `zstd -dc` but imports only the
Python standard library and never imports the runner, teacher, simulator, or
product scorer.

A pass permits only the design of the larger MA-2 corpus experiment. Physical
motion and mount readiness remain **NO-GO**.
