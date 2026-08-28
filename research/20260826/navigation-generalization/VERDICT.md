# Navigation generalization verdict

## Decision

**Do not mount this software for physical motion yet.** A stationary,
observation-only Stage-0 capture can be considered only under the separate
hardware runbook, Sport disabled, an independent remote stop and secured
robot. Nothing in this research changes the QEV motion, point-goal, Follow or
stairs **NO-GO**.

Simulation is worth substantial investment now. The highest-return path is a
typed hierarchical companion executive, independent completion evidence,
versioned external replay data and a simulator ladder tied to the exact Go2
DDS/gateway boundary. Do not begin with end-to-end VLA-to-joints training.

This design also fits the stated API budget: paid realtime/text calls belong
at human-turn rate for dialogue and occasional mission interpretation. Run
perception, localization, planning, safety, target tracking and locomotion
locally on Orin; never spend network/API tokens at the 10--100 Hz control
rates, and never make Starlink availability a motion dependency.

| Decision | Verdict |
|---|---|
| Preregistered `no_path`-only liveness supervisor | **REJECT** — H1 refuted; it missed 7/24 `goal_blocked` loops |
| Typed supervisor over explicit unroutable planner outcomes | **CARRY FORWARD, NOT PROMOTE** — H1b handled 24/24 blockers and preserved 60/60 nominal outcomes, but was post-hoc |
| Five-tick or higher-confidence arrival confirmation | **REJECT** — 3/3 aliased false arrivals remained 5.21--5.30 m from truth |
| Independent-evidence arrival latch | **REQUIRED** — physical translation/completion must remain disarmed after localization discontinuity until independent evidence restores authority |
| Two-level language/mission and navigation/locomotion architecture | **RECOMMEND** — typed, constraint-checked subgoals; no language model access to velocities or joints |
| Native Unitree MuJoCo SDK2/DDS integration | **START NEXT, UNINTEGRATED** — retain the integrated official Go2 MJCF assets and fake Sport lifecycle tier; bridge the native low-level simulator surface through a simulated `SportPort` or explicit high-level controller |
| Isaac Lab articulated training | **PLAN AFTER THE CONTRACT HARNESS** — train on a compatible GPU host, deploy/profile on Orin |
| MetaUrban/Habitat integration | **SECOND WAVE** — valuable for social/semantic diversity after their real adapters/assets work |
| Physical stairs or Follow | **NO-GO** — no qualifying perception, identity, terrain, stopping or physical evidence |

## Immediate implementation order

### P0 — close the two observed wrong-answer classes

1. Replace planner note-string parsing with a typed `PlannerOutcome` carrying
   `progress`, `reason`, `since`, `retryable`, `evidence_age` and an optional
   safe recovery set. Give every active skill progress/retry/total-time budgets.
2. Generate and freeze a new blocker holdout with doors that reopen, moving
   people, alternate routes, narrow approaches and false transient `no_path`.
   Compare H1b against retry/backoff/replan/ask policies. Require zero silent
   terminals and no nominal or transient-block regression.
3. Make localization discontinuity a latched loss of translation and
   completion authority. Re-arm only from registered independent evidence:
   discriminative place match with runner-up margin, fresh target-relative
   observation, carried reference, or bounded operator reset.
4. Add completion precision and false-transition rate as release gates. A
   single false arrival in the frozen safety holdout is red.
5. Keep Follow, SearchOwner, stairs and self-authored expressive locomotion
   disabled on the physical profile.

### P1 — make simulation exercise the intended robot boundary

1. Retain the integrated official Go2 MJCF assets and integrate the native
   `unitree_mujoco` SDK2/DDS simulator boundary in an isolated pinned
   environment. Keep fake Sport as the separate gateway-lifecycle tier. Bridge
   the low-level simulator surface through a simulated `SportPort` or explicit
   high-level-to-low-level controller, with the gateway still the sole writer,
   a nonphysical domain/interface and startup disarmed.
2. Build deterministic contract campaigns for axis/sign/unit, command rate and
   age, clamp, hold/stop, reconnect refusal, state/scan loss, clock skew,
   delayed command and process restart.
3. Add a versioned scenario generator across scene, instruction, goal modality,
   perception, dynamics, localization, terrain, systems load and dialogue
   correction. Keep train/dev/frozen-test partitions immutable by digest.
4. Run every learned candidate behind the existing deterministic safety shell
   and against minimal failure refuters before aggregate benchmarks.

### P2 — add semantic, social and lifelong capability

1. Introduce a typed `CompanionMission` graph:
   `intent -> constrained subgoal -> metric/relative goal -> skill -> verified
   transition`. Preserve multi-turn amendments, cancel/pause/resume and reasoned
   refusal.
2. Separate the local metric/elevation map, semantic/topological scene graph
   and episodic memory. Semantic retrieval proposes; geometric and fresh
   perceptual evidence authorize.
3. Implement owner tracking as an identity posterior with target lineage,
   last-seen state, covariance, occlusion/distractor margin and bounded search.
   Never switch to the nearest person by default.
4. Add FollowBench/TPT-style occlusion, group crossing, long disappearance,
   formation and distance tests, plus Habitat/MetaUrban interactive scenes when
   the real adapters and licensed assets are present.
5. Store immutable MCAP/rosbag/image/point-cloud artifacts in external object
   storage, metadata and lineage in a relational database, and derived
   embeddings/features as rebuildable indexes. Keep only a bounded encrypted
   upload queue on the dog.

### P3 — learn terrain skills, then qualify them physically

1. Add elevation, slope, step height, roughness, edge/drop, width and uncertainty
   to the planner/locomotion contract.
2. Use Unitree RL Lab/MjLab and Isaac Lab for privileged teacher training,
   actuator/latency/payload/friction randomization and deployment-time
   adaptation. Keep a broad frozen holdout alongside failure-mined curricula.
3. Export pinned policies and benchmark deadline, memory, thermal and power
   behavior on AGX Orin. Use Orin for deployment inference/HIL; do not assume it
   is the large-scale training machine.
4. Qualify flat motion before slopes, slopes before single steps, and controlled
   instrumented stair fixtures before ordinary stairs. Measure fall/abort,
   slip, foot clearance, body attitude, stopping and retreat; simulator success
   alone never advances the physical gate.

## Required physical promotion sequence

1. Same runtime → gateway → sole vendor writer, boot/restart/reconnect disarmed.
2. Independent physical emergency stop and measured stop behavior.
3. Stationary Stage-0 bags with clocks, calibration, extrinsics, dropout,
   thermal and power evidence.
4. Real LIO/scene observations replayed through R3/R4b/no-progress/false-arrival
   refuters.
5. One tethered stand/translation axis with sign, units, clamps, command age and
   stopping envelope measured.
6. Supervised known-point navigation: no false arrivals or contacts and every
   non-arrival typed.
7. Real owner identity, crossing, disappearance and reacquisition evidence
   before Follow.
8. Terrain-specific commissioning before any stair attempt.

## Research interpretation

The fresh experiment establishes a software fact, not a robot fact. Across two
exact repeats, deterministic digests matched and H1b produced the desired
narrow behavior. It does not validate Mid-360 mapping, Go2 dynamics, the AGX
Orin runtime, owner perception, a room with moving people, or physical safety.

The practical lesson is nonetheless strong: put learning where it can improve
generalization—semantic decomposition, risk/cost prediction, social policy,
terrain policy and failure-mined curriculum—and keep state authority,
liveness budgets, identity gates, completion evidence and stops explicit and
testable.
