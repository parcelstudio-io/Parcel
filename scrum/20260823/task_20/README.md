# Task 20 · PROTO-0 — Unitree living-dog prototype readiness and critical-path review

**Date:** 2026-08-23

**Status:** REVIEW_REQUESTED · NOT DISPATCHED

**Author:** Codex (current-tree readiness assessment)

**Required reviewer:** Claude

## Owner request

Review the current recommendation for reaching a prototype that can be mounted
on a Unitree Go2 EDU/EDU Plus and can eventually:

- sustain seamless, interesting, interruptible conversation;
- navigate indoors and outdoors autonomously;
- localize and map with SLAM;
- perceive people, terrain, objects, places, and changing surroundings;
- learn governed facts and experiences about the owner and world;
- keep observing and choosing behavior without waiting for a command; and
- express lifelike idle behavior through breathing, looking, posture, motion,
  and appropriately initiated conversation.

This card asks Claude to review priorities and evidence. It does **not**
authorize implementation, physical motion, decomposition, a test campaign,
commit, push, or one follow-up card per finding.

## Decision requested from Claude

Return exactly one top-level disposition in `CLAUDE_REVIEW.md`:

1. `ACCEPT_PRIORITY_SEQUENCE`
2. `ACCEPT_WITH_REQUIRED_CHANGES`
3. `REJECT`

The review must either accept the sequence below or replace it with a smaller,
dependency-correct sequence tied to falsifiable prototype outcomes. Architecture
preferences without a measurable physical outcome are not sufficient reasons
to add work.

## Snapshot Claude must confirm or correct

At creation, local `main` was at `43e6cfc` and one commit ahead of
`origin/main`; DEC-IG-2 was a broad dirty in-flight import/barrel migration.
Claude must state the exact commit and dirty overlay it actually reviews.

Two representative guarded desktop campaigns passed 298 and 404 tests. They
support the existence of software mechanisms, not target, moving-body, or
physical-safety claims.

| Capability | Software/simulation estimate | Physical Unitree estimate | Current evidence ceiling |
|---|---:|---:|---|
| Conversation mechanics | 6/10 | 2/10 | Turn authority, cancellation and hosted/local paths; no commissioned through-air lane |
| Interesting natural conversation | 3/10 | 1–2/10 | Machine checks exist; weak current human-quality and acoustic evidence |
| Indoor navigation | 7/10 | 1/10 | Rolling grid, A*, tracking and reactive safety; no physical localization/TF traversal |
| Outdoor navigation | 2/10 | 0–1/10 | No commissioned outdoor localization, terrain/drop-off stack, ODD or field evidence |
| Generalized perception | 3–4/10 | 1/10 | Useful adapters and semantic maps; default oracle/synthetic evidence and uncalibrated target accuracy |
| User/world memory | 5/10 | 2/10 | Durable explicit owner facts and semantic rows; autonomous consolidation and spatial dialogue are incomplete |
| SLAM/localization | 1/10 | 0–1/10 | Typed seam and drift simulation only; no real estimator, loop closure or relocalization |
| Lifelike autonomous behavior | 6/10 | 0–1/10 | 50 Hz simulator expression and bounded initiative; current Go2 expression/motion path does not actuate it |
| Safety/deployment | 7–8/10 software | 2–3/10 commissioned | Strong software refusal/TTL/stop contracts; no complete native writer, independent stop or body measurements |

Working aggregate estimate, to be challenged rather than repeated as fact:

- persuasive simulator prototype: **55–65%**;
- supervised low-speed indoor Unitree prototype: **20–30%**; and
- full indoor/outdoor living-dog objective: **about 10–15%**.

## Current factual concerns

Claude must trace and either confirm or refute these against the reviewed tree:

1. The normal Go2 backend remains observe-only: positive motion, pose, and
   trajectory methods refuse, while expression and stop/e-stop are no-ops
   because that backend never takes command authority.
2. `PoseProvider` remains a seam rather than SLAM: there is no production
   estimator, `map→odom`, covariance-driven health, loop closure,
   relocalization, or physical-origin solution.
3. There is no single synchronized physical observation product joining body
   state, controller feedback, LiDAR, RGB/depth, timestamps, frames,
   calibration/extrinsics, provenance, and health.
4. The default semantic lane still relies on simulator/oracle evidence;
   physical owner, people, terrain/drop-off, and open-vocabulary accuracy are
   not commissioned.
5. The current expression loop makes MuJoCo breathe/look/shift but does not
   provide a verified Unitree-supported physical expression primitive.
6. Conversation plumbing is stronger than its quality evidence: array audio,
   acoustic echo cancellation, endpointing, barge-in, and latency have not
   passed a through-air target campaign.
7. Durable explicit facts exist, but automatic profile distillation, unified
   episodic/spatial retrieval, correction/deletion audit, and world-query
   answers remain incomplete. No recursive model/policy learning exists.
8. The current control behavior refreshes bounded velocity intents and a
   separate expression overlay; it is not a rolling-horizon whole-body
   trajectory system or a persistent behavior executive.
9. `RobotRuntime` and `DirectiveNavigator` remain serious maintainability
   risks. Import/barrel cleanup is legitimate preparation, but it does not by
   itself advance a physical prototype.

## Recommended target architecture

```text
physical sensors + body/controller state
                 ↓
stamped observation join + SLAM/world model
                 ↓
persistent behavior executive and conversation policy
                 ↓
bounded goals / short-horizon motion candidates
                 ↓
local planning, arbitration and safety
                 ↓
native sole-writer gateway + watchdog + independent stop
                 ↓
Unitree Sport gait/balance controller
```

“Continuous motion” means continuously producing a safe full-body intent,
including a stationary hold. It does not mean continuous nonzero movement.
The language model may propose bounded semantic actions but must never own raw
joints, velocity, safety admission, credentials, or stop release. Unitree's
native controller should continue owning gait and balance.

“Recursive learning” should be reframed as governed continual memory and world
model updates: confidence, provenance, consent, correction, expiration,
deletion, and promotion gates. Online self-modification of model weights or
safety/control policy is out of scope unless separately evaluated and
authorized.

## Recommended execution sequence

### 0. Drain the active foundation card, then stop and decide

Finish, verify, and integrate the already-active DEC-IG-2 scope without
broadening it. Do not automatically dispatch DEC-R1, DEC-FS-1, DEC-N1, or a
new decomposition wave. Claude's review must identify which decomposition is a
hard prerequisite for the next physical slice and which can wait for a forced
change.

### 1A. Physical observation spine

Produce one typed, synchronized, recordable/replayable observation containing
Unitree body state, controller feedback, Mid360 scan, D455 RGB/depth,
per-source host receipt and device clocks, sequence/epoch, frames, calibrated
extrinsics, covariance/health, origin, and provenance. Resolve the product-vs-
vendor-process sidecar topology and prove stale/missing/malformed/simulator
evidence cannot become physical-positive evidence.

### 1B. No-credential native gateway bench

In a genuinely disjoint lane, freeze the bridge protocol and bench the smallest
native sole-writer/final-governor artifact against a fake Sport endpoint. It
must own credential, epoch, lease, TTL, watchdog, clamp/veto, restart-disarmed,
and exact-zero stop semantics. This gives no authority to move hardware.

### 2. Physical safety and commissioning

Repeat the same gateway artifact on Orin; establish an independent operator
E-stop; then progress through bench, stand, single-axis pulse, and leashed
low-speed tests. Measure command/feedback timing, stop latency and distance,
fault response, process crash, network loss, stale sensor, overload, restart,
battery, payload, and slope behavior before autonomous translation.

### 3. Real localization and SLAM

Integrate a mature LIO/SLAM implementation behind `PoseProvider` rather than
writing an unbounded custom estimator. Commission `map→odom→base_link`,
covariance, localization loss, relocalization, loop closure, persistent map
reload, and motion refusal while pose is unhealthy.

### 4. One narrow indoor operational design domain

Target a supervised private, flat, dry, mapped indoor space at low speed with
an operator and independent stop. Prove stationary conversation, point-goal
navigation, stop, return/follow, people clearance, loss recovery, and bounded
awareness repeatedly. Public spaces, stairs, crowds, weather, and outdoor
terrain remain excluded.

### 5. Through-air conversation

Commission the real array, speaker, AEC, endpointing, interruption, and
off-control-loop narration. Measure word error rate, false arms, interruption
latency, response latency, control-loop impact, and human-rated naturalness.
Rerun the current conversation corpus before claiming seamless or interesting
conversation.

### 6. Physical perception and spatial memory

Calibrate and shadow-evaluate owner/person continuity, obstacles, terrain and
drop-offs, open-vocabulary objects, and semantic-map promotion on physical
recordings. Connect conversation/profile/episodic/spatial stores through a
governed retrieval layer able to answer world queries while preserving
consent, provenance, correction, expiry, and deletion.

### 7. Physical lifelike behavior

Enable one vendor-supported, tightly bounded expression primitive first.
Then add safe body-yaw awareness, idle posture, gaze proxies, curiosity, and
behavior-scoped rolling goals. Every layer must yield immediately to owner
speech, safety, low battery, privacy/quiet-hours policy, and unhealthy inputs.

### 8. Outdoor expansion

Only after repeated indoor success, add a defined outdoor ODD and the missing
terrain/drop-off, global-localization/GNSS where appropriate, slope, lighting,
weather, route, recovery, and field-evaluation capabilities.

## Evidence gates Claude should review

For every accepted stage, specify a positive-path test, a disconnected/stale/
crash refuter, the exact evidence tier, and what remains unproved. At minimum:

- one synchronized target snapshot and replay with visible clocks/frames;
- exact-zero on gateway kill, client death, stale lease, network loss, stale
  observation, localization loss, overload, and restart;
- measured stop latency/distance and independent E-stop evidence;
- repeated leashed indoor runs with contacts, interventions, goal success,
  localization-loss, clearance, and timing reported—not only pass/fail;
- through-air acoustic and human conversation-quality evidence;
- physical perception precision/recall/abstention by relevant class and ODD;
- memory correction/deletion/provenance tests and world-query quality; and
- physical expression proof with the same safety/preemption refuters.

Simulator, replay, desktop, mock, aarch64 build, Orin process, HIL, stationary
body, and moving-body evidence must remain separately labeled.

## Questions Claude must answer

1. Is the readiness snapshot materially accurate? Correct each disputed row
   with file/line or measured evidence.
2. What is the smallest first physical prototype outcome, and what is its
   explicit ODD?
3. Which parts of tasks 17–19 are hard prerequisites for that outcome, and
   which should be deferred?
4. Does the observation-spine/native-gateway split preserve one writer and
   allow useful parallel work without shared ownership?
5. Which established SLAM/localization provider and process topology should be
   evaluated first? State selection criteria rather than inventing certainty.
6. What exact gates authorize the first pulse, first translation, first
   autonomous indoor run, and first outdoor run?
7. Which existing simulator mechanisms are retained unchanged, and which are
   currently scaffolds that must not be counted as physical progress?
8. What single next implementation card produces the greatest physical
   readiness gain after DEC-IG-2? Do not create that card during this review.
9. What spend, WIP, full-suite, documentation, and follow-up-card limits keep
   the sequence efficient?

## Required review output

Create only `scrum/20260823/task_20/CLAUDE_REVIEW.md` containing:

- the exact reviewed commit and dirty-overlay boundary;
- one required disposition;
- confirmed facts and evidence-backed corrections;
- accepted/revised first prototype ODD and milestone sequence;
- `COMPLETE_NOW`, `DEFER`, and `DROP/REFUTE` dispositions for tasks 17–19;
- the one smallest recommended next implementation card, without creating it;
- physical/eval gates and stop/continue criteria;
- an explicit spend/WIP/follow-up admission policy; and
- a non-empty `Does not prove` section.

Batch related findings in this one review. Do not create one task, agent, or
document per concern. Stop after the review and return it for owner approval.

## Ownership and collision boundary

**OWNS:** `scrum/20260823/task_20/**` only.

**MUST NOT TOUCH:** active task 16 files; tasks 17–19; `src/**`, `tests/**`,
`scripts/**`, `tools/**`, `examples/**`, `evals/**`, `configs/**`, `deploy/**`,
other `scrum/**`, Git state, running services, the live robot, or the owner
memory store.

No full test suite is required for this docs-only review. Read-only targeted
inspection may be used to verify a disputed fact. Claude must not dispatch
work or infer owner authorization from this card.

## What this task does not prove

This is a current-tree architecture and priority review. It proves no target
installation, sensor calibration, localization accuracy, stopping distance,
conversation quality, memory quality, autonomous-navigation success, outdoor
fitness, physical safety, or readiness to move a Unitree. Passing desktop
tests, finishing decomposition, or accepting this recommendation cannot be
promoted into any of those claims.
