# Generalized agency and movement for the Go2 companion

Date: 2026-08-28  
Target: Unitree Go2 EDU+, likely Jetson AGX Orin 64 GB, camera, Mid-series
LiDAR, microphone/speaker, and custom Starlink modem  
Evidence available today: repository audit, authored symbolic shadow
evaluation, earlier desktop simulation/replay, and primary-source review  
Physical Go2/Orin evidence available today: **none**

## Executive answer

Yes, the dog can become substantially better at learning, solving, and
planning, but generalized movement will not come from making the conversation
model directly generate more motion. The shortest credible path is a hierarchy
in which:

1. a semantic planner decides *what skill or information is needed*;
2. a terrain-aware dynamics planner decides *what short-horizon body motion is
   feasible*;
3. an adaptive locomotion policy turns that reference into stable movement;
4. deterministic safety and the sole-writer gateway retain final authority.

The companion should learn on three different timescales: replan from observed
outcomes within an episode, adapt a bounded latent state online without
changing weights, and improve weights/maps/skill reliability offline through a
split-disciplined promotion loop. An unconstrained model must never learn by
rewriting the live motor stack.

The current implementation is a foundation for that architecture, not the
result. It now represents reviewed categorical motion intent, contextual skill
outcomes, and bounded semantic plan proposals with an explicit observable-fact
boundary. It does **not** contain a
trained generalized Go2 locomotion policy, a terrain dynamics model, a runtime
caller for the new affordance planner, a native commissioned Unitree motion
path, or physical evidence. Motion-enabled mounting remains **NO-GO**.

## Honest current status

| Capability | What exists | Evidence and decision |
|---|---|---|
| Companion relationship | The prompt says the robot is an ongoing companion friend by default and supports the owner across turns, subject to consent, privacy, quiet, and distance boundaries | Prompt rendering/contract evidence only; personal multi-turn quality was previously 3/13 turns and remains **NO-GO** |
| Semantic execution | `PlanSketch`, deterministic compilation/admission, executive contracts, receipts, and bounded `AffordancePlannerV1/V2` | Existing fresh compound planning was 3/5; both new planners are harness-only and have no runtime caller |
| Symbolic composition | `SIM-PLAN-1` compares bounded search with a fixed-template selector | 18/18 solvable authored missions versus 5/18 baseline; 0 planner-created shadow safety/admission violations; narrow `SUPPORTED_SHADOW` only |
| Correct uncertainty diagnosis | V1 and the additive observable-bound V2 on the same 29 authored missions | V1 scored 26/29 and **H2 was REFUTED**. V2 repaired all three misses for 29/29, but those failures informed the change; this is `SUPPORTED_REGRESSION_SHADOW`, not fresh generalization |
| Outcome learning | Immutable train/dev skill transitions and contextual Beta reliability proposals; frozen-test transitions are rejected; proposals cannot activate anything | Contract/unit evidence only; no runtime learner, learned affordance model, or measured capability improvement |
| Generalized motion | Reviewed categorical gait/style/body targets, legal transition graph, and digest-bound simulator policy-candidate identity | Interface only. It rejects arbitrary language-authored latents/joints/torques and always has `authorizes_motion=false`; no policy has been trained or executed |
| RL training environment | The repository has a small Gymnasium-shaped `Go2Env` wiring stub | `RL-ENV-READINESS-1` passed 2/9 fidelity gates. Joint order is inconsistent, velocity/height/upright/termination are untruthful, and reset leaks action history; do not use it for ROB-GEN-1 |
| Navigation | Existing metric/semantic navigation, Follow and headless simulation paths | Prior NAV_INSTRUCT success was 25/125 (20%) with one false arrival. A commissioned lamppost E2E now grounds correctly but exposes a planner/controller feasibility gap: the final gate stops on a route the grid still calls planned, then recovery blacklists the target. Follow/social-yield remain **NO-GO** |
| Go2 execution | Disarmed runtime -> Unix gateway -> fake Sport composition and official Go2 MJCF mechanics smoke | No native SDK2/DDS bridge in the product path, no Orin profiling, no physical controller or stop envelope; physical motion **NO-GO** |

`SIM-PLAN-1` is repeatable: two process runs were JSON-identical, the verifier
passed 12/12 checks, and all 87 planner proposals were input-bound,
operator-order invariant, and non-authorizing. Its overall verdict is still
**INCONCLUSIVE for generalized robot planning**. The worlds, facts, operators,
and labels were authored; it did not exercise perception, language grounding,
physics, learned locomotion, or hardware. The intentionally small template
baseline is not a robotics foundation-model comparison. See
[`sim-plan-1/RESULTS.md`](sim-plan-1/RESULTS.md) and
[`sim-plan-1/VERDICT.md`](sim-plan-1/VERDICT.md).

`SIM-PLAN-2` adds an exact externally-observable fact boundary and a bounded
goal-relevance proof. It repaired the three V1 misses, retained 18/18 valid
plans, and produced 0/0 shadow safety/admission violations; two runs were
identical and its verifier passed 12/12. This is deliberately labeled a
regression confirmation because the V1 failures informed V2. Generalized
planning remains **INCONCLUSIVE**. See
[`sim-plan-2/RESULTS.md`](sim-plan-2/RESULTS.md) and
[`sim-plan-2/VERDICT.md`](sim-plan-2/VERDICT.md).

`RL-ENV-READINESS-1` ran against the tracked Go2 MJCF and refuted the current
environment's readiness: only model dimensions and action-to-physics coupling
passed. Seven gates failed, including actuator/observation ordering, truthful
root velocity and height, fall state/termination, reset independence, and
honest offline-stub labeling. Two raw runs were byte-identical and the verifier
passed 14/14. See
[`rl-env-readiness/RESULTS.md`](rl-env-readiness/RESULTS.md) and
[`rl-env-readiness/VERDICT.md`](rl-env-readiness/VERDICT.md).

## Recommended four-layer autonomy stack

```text
conversation + owner goals + semantic world/episode memory
                           |
                           v
  1. semantic planner, event-driven / 0.2-1 Hz
     bounded skill composition, questions, decline, outcome replanning
                           |
              typed subgoal + constraints
                           v
  2. terrain/dynamics planner, 5-10 Hz
     local elevation + perception + learned dynamics + MPPI/search
                           |
             short-horizon body reference
                           v
  3. adaptive locomotion, 50-100 Hz
     gait/motion latent + proprioceptive history + rapid adaptation
                           |
                bounded motor targets
                           v
  4. deterministic safety, 50-200+ Hz
     freshness, limits, collision/contact, fall, stop, e-stop, gateway
                           |
                          Go2
```

The rates above are design targets to profile, not measured Parcel/AGX
performance.

### 1. Semantic planner: think in admitted skills

The language layer may propose a goal, a clarification, and named semantic
skills such as `FindOwner`, `ApproachOwner`, `FollowFormation`,
`TraverseTerrain`, `Greet`, or `Hold`. It should not emit a velocity, joint
target, torque, raw learned latent, or claim of completion.

`AffordancePlannerV2` is now the better bounded-search candidate. It retains
V1's confirmed-fact search, commissioning/reliability suppression and
invariants, then requests an observation only after a bounded proof that an
explicitly observable unknown can enable a complete goal-supporting admitted
chain. Its proposals additionally bind the exact observable-fact set. The next
step is a fresh procedural matrix and a lane beside the current executive with
logging but no dispatch authority.

This follows the useful division in [SayCan](https://say-can.github.io/):
language-level usefulness should be combined with grounded skill feasibility,
and execution feedback should close the loop. [Inner
Monologue](https://arxiv.org/abs/2207.05608) provides a complementary precedent
for feeding environment and success feedback back into a high-level planner.
Neither source makes a legged skill safe or available by naming it.

### 2. Terrain-aware dynamics planner: reason before committing the body

Build a receding-horizon planner over the local elevation/traversability map
and a learned forward-dynamics model. It should compare candidate body
trajectories, model uncertainty, and choose a short reference or return a typed
blocker. A learned score is advisory; stale localization, hard clearance,
contact, tilt, and command limits remain deterministic.

[FDM](https://github.com/leggedrobotics/fdm) is the most relevant architectural
challenger: it combines a learned forward-dynamics model with sampling-based
planning for perceptive legged navigation. Its public evidence is for ANYmal,
not Parcel's Go2 or AGX deployment, so its results are a hypothesis and
implementation reference—not transferable evidence.

### 3. Adaptive locomotion: a vocabulary, not one brittle gait

Start from a stable Go2 locomotion baseline, then learn adaptation to friction,
payload, center-of-mass shift, actuator weakness, latency, sensor noise, and
terrain. [Rapid Motor Adaptation
(RMA)](https://arxiv.org/abs/2107.04034) motivates a base policy plus a rapidly
inferred environment latent. [MoE-Loco](https://moe-loco.github.io/) provides a
simulation-and-physical precedent for a compact mixture of locomotion experts,
while [Robot Parkour](https://robot-parkour.github.io/) motivates specialist
teachers distilled into a recurrent generalist. These systems demonstrate
task-bounded locomotion research; none establishes Go2 transfer or open-ended
dog intelligence.

For expressive motion, [VIM](https://rchalyang.github.io/VIM/) suggests a
learned motion latent and broad motion prior. Parcel should expose only
reviewed named regions of such a latent—walk, careful-step, crouch, bow,
head-tilt, settle, recovery—and a reviewed directed transition graph. Language
selects the name; the motor stack owns interpolation and execution.

### 4. Deterministic safety: never a learned reward term only

The final layer independently checks observation age, localization health,
joint/torque/velocity/body envelopes, collision clearance, contact/fall state,
policy timeout, permitted operating mode, and stop/e-stop. It is the only path
to the sole-writer gateway. Every learned layer may propose `slow`, `replan`,
`ask`, `decline`, or a bounded reference; none may bypass this layer or
activate itself.

## Three learning timescales

### A. Within an episode: observe, revise, and try another admitted plan

Every skill attempt produces an authenticated terminal receipt and a newer
world observation. Success applies only observed facts—not predicted effects—
and replans the remaining goal. Failure records the blocker, excludes the
failed grounded instance when appropriate, and chooses another admitted chain,
asks for information/help, or holds. This loop runs in seconds and changes no
weights.

This is where the dog appears to “think”: it notices that the door is closed,
that the owner moved, or that a route failed, then revises the plan rather than
repeating a memorized sequence.

### B. Within seconds: adapt a bounded hidden state, not the live software

The locomotion policy continuously infers a short-lived latent from
proprioceptive history and prediction error. That latent can compensate for a
slippery floor, a carried payload, or motor weakness within the trained
envelope. It resets under defined conditions, is clamped/out-of-distribution
checked, and does not persist as a policy update. This is the RMA-style loop.

### C. Across days: persistent, offline, split-disciplined improvement

Store immutable episodes off-robot with at least:

- observation/map/body-model/policy/config digests;
- dialogue goal and semantic plan proposal;
- admitted skill instance and context hierarchy;
- progress, blocker and terminal receipts;
- safety interventions and counterfactual shadow predictions;
- owner feedback/consent/revocation lineage; and
- train/dev/frozen-test split and leakage-group identity.

Aggregate train/dev outcomes into calibrated contextual skill reliability,
mine procedural curricula, train challengers, and run frozen evaluations.
Frozen test never trains a candidate. A signed human-reviewed proposal may
advance to simulation shadow, but promotion/commissioning is a separate
operation with rollback. [Eurekaverse](https://github.com/eureka-research/eurekaverse)
is useful precedent for generating and validating increasingly difficult
terrain curricula; an LLM should generate curriculum candidates, never motor
commands or its own pass labels.

## Preregistered next evaluations

These experiments should be frozen before training. Report aggregate and
worst-quartile results with bootstrap confidence intervals; never promote from
the mean alone.

### ROB-GEN-1 — adaptive Go2 locomotion generalization

**Hypothesis.** Under equal observations, command envelope, simulator steps,
and training budget, a recurrent rapid-adaptation policy or compact
mixture-of-experts policy generalizes better than domain-randomized PPO.

**Arms.** (A) official Go2 PPO baseline; (B) PPO plus RMA-style adaptation
module; (C) compact 4–6-expert locomotion mixture with a recurrent gate. Start
from [Unitree RL Lab](https://github.com/unitreerobotics/unitree_rl_lab) in
Isaac Lab, then run the frozen policies through the official
[unitree_mujoco](https://github.com/unitreerobotics/unitree_mujoco) boundary.
Do not tune on MuJoCo frozen-test failures.

**Frozen test.** Unseen combinations of terrain seed/type, stair dimensions,
friction, payload/COM, actuator strength, command latency, observation noise,
sensor dropout, and recovery perturbation. Keep single-factor slices plus
compositional out-of-distribution slices. Log falls, hard-limit interventions,
goal completion, velocity/yaw tracking, energy, foot slip, recovery time, and
uncertainty/abstention.

**Promotion gates.** Against arm A, require:

- at least 25% relative reduction in worst-quartile fall rate;
- no safety/intervention rate worse by more than 5 percentage points;
- no regression larger than 5% in nominal tracking or energy-normalized
  progress; and
- Isaac-to-MuJoCo per-scenario success-rank Spearman correlation at least 0.70.

Passing creates only a digest-bound `sim_candidate`; it does not commission a
policy.

### MOTION-COMP-1 — safe composition of navigation and expression

**Hypothesis.** Specialist teachers distilled into a recurrent generalist with
a bounded residual can execute unseen named motion sequences more reliably
than switching independent policies or using the current sparse fixed
gestures.

**Teachers.** Train 4–6 specialists covering flat walk/trot, careful terrain,
crouch/low-clearance, expressive bow/head-tilt/settle, and recovery. Distill
them into one history-conditioned student. Restrict language to the reviewed
categorical motion catalog and require every state transition to occur on the
reviewed graph.

**Frozen test.** Hold out complete sequences—not merely terrain seeds—such as
approach -> slow -> bow -> settle, search -> stair -> reacquire -> approach,
and follow -> doorway yield -> resume. Randomize phase, commanded speed,
terrain, payload and interruption timing. Score every transition, not only the
final pose.

**Promotion gates.** Require:

- at least 90% transition survival across every named family;
- at least 20% relative gain in full-sequence completion over hard switching;
- zero joint, torque, collision, fall, transition-graph or command-envelope
  violations; and
- STOP/HOLD entry within the simulator's preregistered time/distance envelope
  under interruption and policy timeout.

### PLAN-SAFE-1 — terrain dynamics planning in shadow

**Hypothesis.** An uncertainty-aware learned forward-dynamics + MPPI
challenger improves terrain progress over the current local planner without
increasing collisions or false-safe proposals.

**Method.** Replay the same perception snapshots and body states through both
planners. The challenger may emit only a scored short-horizon proposal and
uncertainty/blocker; the existing controller remains in charge. Evaluate
unseen clutter, slopes, stairs, deformable/slippery surfaces, narrow passages,
dynamic occlusion, localization drift, stale elevation, and body-model shift.
After desktop qualification, profile the exact artifact on AGX Orin in shadow.

**Promotion gates.** Require:

- at least 25% reduction in terminal pose error;
- at least +15 percentage points in goal success;
- no increase in collision/contact/fall rate, with zero hard-safety violations;
- zero false-safe proposals on authored hard-negative and fault-injection
  cases; and
- AGX shadow p99 planning latency below 140 ms while sustaining at least 7 Hz.

These gates qualify only a planner challenger for a later supervised
simulation rung.

## 30/60/90-day implementation path

### Days 0–30 — establish the learning instrument

1. Keep the completed `SIM-PLAN-2` regression frozen, then generate a fresh
   procedural matrix with stale/noisy observations and outcome-driven replans.
2. Wire `AffordancePlannerV2` into proposal-only runtime shadow. Persist exact
   state/problem/manifest/reliability digests, chosen plan, current executive
   action, receipt, and replan outcome; never dispatch the shadow proposal.
3. Add a persistent world-belief snapshot and skill-transition writer on the
   isolated research plane. Collect at least 600 paired episodes spanning
   success, recoverable failure, unknown, contradiction and safety failure.
4. Stand up reproducible Go2 training in Unitree RL Lab and frozen evaluation
   in unitree_mujoco. Record the body, sensor, action, policy, terrain and
   simulator digests for every episode.
5. Freeze ROB-GEN-1 splits and reproduce the PPO baseline twice before adding
   adaptation.

Exit: deterministic two-simulator baseline, complete lineage, no frozen-test
leakage, and no new actuation authority.

### Days 31–60 — train generalists and procedural missions

1. Train RMA and compact mixture challengers; run ROB-GEN-1 without moving the
   gates.
2. Grow to at least 5,000 procedural semantic missions and terrain episodes
   with leakage-grouped train/dev/frozen splits. Use generated curricula only
   after deterministic validation and novelty checks.
3. Build versioned metric/elevation, semantic/topological, and episodic memory
   layers. A semantic match proposes a region; fresh geometry and localization
   retain traversal/arrival authority.
4. Calibrate contextual skill-outcome estimates with minimum support,
   uncertainty and safety-failure preservation. Compare against global and
   nearest-context baselines.
5. Freeze the reviewed named motion catalog and MOTION-COMP-1 sequences.

Exit: one repeatable adaptive-locomotion result and one procedural
planning/replanning corpus. A failed gate is recorded, not tuned away.

### Days 61–90 — integrate terrain planning and motion composition

1. Run PLAN-SAFE-1 with an FDM/MPPI challenger in desktop shadow, then profile
   the exact artifact on AGX Orin only after desktop gates pass.
2. Distill the motion specialists and run MOTION-COMP-1, including
   interruption, recovery and expressive transitions during navigation.
3. Run Isaac Lab -> MuJoCo cross-simulator replay for all surviving motor
   candidates and fault-inject stale perception, localization resets, model
   mismatch, policy timeout and gateway disconnect.
4. Package the survivor as a signed, digest-bound simulation candidate with
   explicit stop/fallback/termination contracts and rollback lineage.
5. Write a separate physical commissioning plan. Do not infer permission to
   stand, walk, follow, climb stairs or use expressive motion from simulation.

Exit: at most a **signed simulation candidate**. Physical motion remains
NO-GO until native transport, stationary/tethered rungs, stop envelopes and
supervised hardware tests independently pass.

## Monthly model-budget allocation

The owner's stated envelopes should remain separate ledgers:

| Envelope | Allocation | Purpose |
|---|---:|---|
| Realtime API | $210 | Owner-facing multi-turn voice sessions and barge-in |
| Realtime API | $45 | Frozen conversational/acoustic evaluation and selected replay |
| Realtime API | $30 | Deliberately sampled difficult multimodal/tool turns |
| Realtime API | $15 | Hard stop reserve; alert rather than silently borrow |
| Text model | $60 | Deliberative semantic planning, failure analysis and curriculum proposals |
| Text model | $20 | Frozen plan/conversation evaluation and adjudication |
| Text model | $20 | Reserve for regression investigation; alert rather than silently borrow |

Total: **$300/month Realtime + $100/month text**. Starlink service is a
separate operating cost and must never be required for STOP, HOLD, local
planning, locomotion, safety, or owner-loss behavior.

These API budgets improve dialogue, semantic plan proposals, test generation,
and offline analysis. They do not buy gait intelligence. Locomotion training,
dynamics learning, map building, safety, and ordinary execution should run
locally/offline on the development GPU and later AGX Orin. Hosted APIs stay
outside every control loop and every completion authority.

## Immediate recommendation

The next engineering dollar and week should go to replacing the refuted RL
stub with the same-contract Go2 two-simulator loop and reproducing the
ROB-GEN-1 baseline. In parallel, shadow V2 so every semantic decision is paired
with an observed outcome, and repair navigation's blocked-route semantics so a
locally infeasible segment is forbidden and replanned before the grounded
target is discarded. That combination creates the missing bridge:

```text
conversation goal -> bounded semantic plan -> feasible terrain reference
-> adaptive named motion -> observed receipt -> replan / learn offline
```

Success means a dog that can choose another method when an attempt fails,
adapt its gait inside a known envelope, compose navigation with expression,
and improve from auditable experience. It does not mean unconstrained online
self-modification or general intelligence in the human sense.

## Primary sources

- [Unitree RL Lab — official Isaac Lab training and deployment
  framework](https://github.com/unitreerobotics/unitree_rl_lab)
- [unitree_mujoco — official MuJoCo/SDK2 simulation
  boundary](https://github.com/unitreerobotics/unitree_mujoco)
- [Rapid Motor Adaptation for Legged Robots](https://arxiv.org/abs/2107.04034)
- [MoE-Loco](https://moe-loco.github.io/)
- [Robot Parkour Learning](https://robot-parkour.github.io/)
- [Generalized Animal Imitator: Agile Locomotion with Versatile Motion Prior
  (VIM)](https://rchalyang.github.io/VIM/)
- [FDM: perceptive locomotion with forward dynamics models](https://github.com/leggedrobotics/fdm)
- [Eurekaverse](https://github.com/eureka-research/eurekaverse)
- [SayCan](https://say-can.github.io/)
- [Inner Monologue](https://arxiv.org/abs/2207.05608)
