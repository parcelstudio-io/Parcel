# Navigation generalization results

**Evaluation date:** 2026-08-26 (America/New_York)
**Repository HEAD exercised:** `f3ecb5cd9e09058c7bc29ba61b63e18f92a308d8`
**Physical hardware exercised:** none
**External-source policy:** primary sources only; see `SOURCES.json`

## Outcome

The navigation stack is useful for desktop research but remains **NO-GO for
physical motion**. The strongest nominal result, 60/60 room arrivals without a
simulated contact or false completion, does not generalize to disturbances:
the prior evidence contains silent no-route loops, confident false arrival
after aliased relocalization, weak instruction success, a Follow/yield contact,
and near-total failure on the BARN PR subset.

This task adds one narrow but useful result. A deterministic liveness
supervisor can turn persistent explicit planner failures into typed outcomes;
however, the preregistered `no_path`-only hypothesis was refuted because the
planner has a second terminal-looking state, `goal_blocked`. An exploratory
two-state arm handled all 24 moved-obstacle cases without changing any of 60
nominal outcomes. That result reproduced exactly, but the state set was learned
from run 1, so it needs a new untouched holdout before product promotion.

Five consecutive arrival confirmations did nothing useful against aliasing:
all 3/3 cases still falsely completed 5.21--5.30 m from the true goal. The
extra ticks share the same incorrect pose/map hypothesis. Completion must
therefore use independent evidence or remain disarmed after a discontinuity.

Simulation is highly feasible for improving this system if it is organized as
a ladder: deterministic fault refuters first; retain the already integrated
official Go2 MJCF assets, then attach the native Unitree MuJoCo low-level DDS
simulator boundary through an explicit simulated `SportPort` or high-level
controller while preserving the gateway boundary; Isaac Lab for articulated
terrain policies and randomization; MetaUrban/Habitat for procedural social
and semantic tasks; and paired real-bag replay once Stage-0 captures exist.
Simulator scores must stay separate from physical commissioning gates.

## Evidence audit

The 2026-08-24 QEV report was measured on an older reviewed commit. Its
artifacts remain the latest broad navigation campaign, so the table below
preserves their provenance rather than presenting them as a fresh HEAD run.
This task freshly reruns only the experiment described later.

| Evidence | Recorded result | What it supports | What it does not support |
|---|---:|---|---|
| NAV-ACCEPT frozen room corpus | shipped 60/60 arrival, 0 false arrivals, 0 contacts, 14.55 s median | A narrow point-goal baseline in generous synthetic rooms | New rooms, dynamics, localization recovery, physical clearance or gait |
| NAV-ACCEPT R3 moved obstacle | shipped 0/3 declared; every row reaches the 900-tick `silent_stall_step_limit`, 4.26--4.50 m from goal | Reproduced liveness defect under a new obstacle | Collision safety; nonmovement makes zero contacts weak evidence |
| NAV-ACCEPT R4b aliased kidnap | shipped 3/3 false arrival, 5.21--5.27 m from truth, confidence 0.988--0.998 | Completion authority can be confidently wrong after a pose discontinuity | A calibrated real-world failure frequency |
| NAV_INSTRUCT v4 full | 32/125 success, SPL 0.1908, 6 false arrivals, 0 contacts | Planning, termination, grounding and search all need work | Real camera/language/noise generalization |
| Follow bench | Follow 7/9, navigate 2/2, 0 contacts | Narrow scripted behavior with oracle-like owner evidence | Identity, long occlusion, distractors or physical following |
| Follow yield extension | STOP-AND-REPORT; 7 misses; one contact; minimum pedestrian surface distance -0.468 m | Current social-yield policy is red | Human safety or comfortable proxemics |
| BARN PR native proxy | 1/10 success, metric 0.04466, 0 collisions; 9/10 travel 0 m | Planner/recovery generalization is poor | Safety: zero collisions is vacuous when the robot does not move |
| Generic five-task proxy | success 0.54, collision 0.46, human collision 0.06 over 50 episodes | A coarse red cross-task signal | An official external leaderboard result |
| Habitat adapter contracts | 30/30 one-step contracts | IPC/action grammar | Habitat episode navigation; assets/runtime were blocked |
| MetaUrban product adapter | `use_metaurban=True` raises `NotImplementedError` | Fail-closed scaffold | A functioning MetaUrban integration |

The current source at the tested HEAD improves the sensing seam but retains
decisive ceilings:

- `Go2Backend` is explicitly observation-only. It assembles timestamped Go2
  state and Mid-360-shaped scans, but all motion-producing methods refuse and owner
  perception is honestly emitted as `visible=False`.
- `ScanMatchLocalizer` explicitly has no IMU, loop closure, pose graph or
  descriptor-based place recognition. That matches the R4b mechanism.
- the room harness and headless city place/advance the base kinematically;
  their zero-contact results do not model feet, motors, payload, stairs or a
  real stopping envelope;
- semantic observations in the simulator can originate from scene truth; and
- the real MetaUrban path remains unimplemented.

Local evidence reviewed:

- `scrum/20260824/task_4/QUALITY_EVAL_REPORT.md`;
- `research/20260824/nav-quality/{RESULTS.md,VERDICT.md}` and its persisted
  machine artifacts;
- `research/20260824/nav-accept/{DESIGN.md,RESULTS.md,VERDICT.md}`;
- `research/20260824/nav-core/{DESIGN.md,RESULTS.md,VERDICT.md}`; and
- current navigation, localization, Go2-backend, simulation and external-eval
  source at the HEAD named above.

## Fresh experiment

### Protocol

`DESIGN.md` fixed H1, H2, seeds and thresholds before run 1. The research-only
runner imports the existing NAV-CORE/NAV-ACCEPT harness and changes no product
code, frozen corpus, ledger or baseline.

The primary repeat executes 174 episodes:

- 60 nominal commissioned baseline + 60 nominal H1 arm;
- 24 held-out moved-obstacle baseline + 24 H1 arm; and
- 3 aliased-kidnap baseline + 3 five-tick-arrival arm.

Moved-obstacle seeds 404/505/606 were not in NAV-CORE/NAV-ACCEPT. Four layouts,
two obstacle onset times and deterministically varied start/goal pairs produce
24 rows per arm. The aliased cases use the same three held-out seeds.

H1b was registered only after run 1 exposed its seven survivors. It repeats 60
nominal and 24 blocker episodes with the status set changed from `{no_path}` to
`{no_path, goal_blocked}`. It reuses run-1 baselines and is labelled
`SUPPORTED_EXPLORATORY`, never preregistered confirmation.

### Results

| Arm/scenario | Arrival | False arrival | Contacts | Typed non-arrival | Silent timeout | Median terminal step |
|---|---:|---:|---:|---:|---:|---:|
| nominal baseline | 60/60 | 0 | 0 | 0 | 0 | 146.5 |
| nominal H1 | 60/60 | 0 | 0 | 0 | 0 | 146.5 |
| blocker baseline | 0/24 | 0 | 0 | 0/24 | 24/24 | 900 |
| blocker H1: persistent `no_path` | 0/24 | 0 | 0 | 17/24 | 7/24 | 80 |
| alias baseline | 0/3 true; 3/3 declared | 3/3 | 0 | 0 | 0 | 154 |
| alias five-tick quarantine | 0/3 true; 3/3 declared | 3/3 | 0 | 0 | 0 | 158 |
| nominal exploratory H1b | 60/60 | 0 | 0 | 0 | 0 | 146.5 |
| blocker exploratory H1b | 0/24 | 0 | 0 | 24/24 | 0/24 | 80 |

**H1: REFUTED.** Seventeen blockers emitted persistent `status=no_path` and
became typed `unreachable` after 30 consecutive ticks. Seven instead emitted
persistent `status=goal_blocked` and rotated until tick 900. Their final truth
distances were 0.68--0.98 m, outside the arrival radius. This is a useful
counterexample to supervising one string while treating the planner state
machine as if it had one failure state.

**H1b: SUPPORTED_EXPLORATORY.** The two-state supervisor produced 24/24 typed
non-arrivals, split 17 `no_path` and 7 `goal_blocked`; 12 terminated at step 65
after the 3-second-onset obstacle and 12 at step 95 after the 6-second-onset
obstacle. Every one used the registered 30-tick persistence bound. All 60
nominal rows were paired-identical. This validates a design direction, not the
specific state set or threshold. A moving person or temporarily blocked door
may clear, so a product executive should report `blocked`, back off/replan,
ask, or retry under a budget rather than blindly convert every three-second
blockage into a permanent mission failure.

**H2: SUPPORTED (negative result).** The five-tick arm retained 3/3 false
arrivals at truth distances 5.2116, 5.2528 and 5.2987 m. Each terminal carried
arrival confidence 1.0 and a five-tick streak. It merely added 0.4 seconds to
the median, with 0.4--0.7 seconds added per episode. Confidence thresholds,
debouncing and same-frame temporal voting cannot resolve this class of error.

**H3 and H4: UNTESTED.** Their task-graph and paired-residual protocols remain
pre-registered future experiments. H4 cannot be run honestly until paired
Stage-0 physical/replay scenarios exist; H3 first needs the held-out
compositional corpus specified in `DESIGN.md`.

### Reproducibility

Both experiment families were executed twice through the repository process
guard. Full JSON artifacts differ in timestamp/wall-clock metadata, as they
should; the deterministic payload digests match:

| Family | Run 1 | Run 2 | Match |
|---|---|---|---|
| preregistered H1/H2 | `95726bddf90466c81c4a859ff479e00cd18daba96f8e3e60039f934abc7100e6` | same | yes |
| exploratory H1b | `f5ade5d0407bf9f04d7db5743775e27e77e979a87f8230a014047657a8faeece` | same | yes |

The verifier recomputed both digests, checked canonical/run-1 equality,
validated all acceptance facts and checked the source manifest. It reports 13
checks passing, 516 total episode executions and 31 primary sources.

Commands:

```text
~/.cache/parcel-guard/pytest_guard.sh --label nav-generalization-run1 -- \
  .parcel/bin/python research/20260826/navigation-generalization/experiment.py \
  --out research/20260826/navigation-generalization/results-run1.json
~/.cache/parcel-guard/pytest_guard.sh --label nav-generalization-run2 -- \
  .parcel/bin/python research/20260826/navigation-generalization/experiment.py \
  --out research/20260826/navigation-generalization/results-run2.json
~/.cache/parcel-guard/pytest_guard.sh --label nav-generalization-h1b-run1 -- \
  .parcel/bin/python research/20260826/navigation-generalization/experiment_h1b.py \
  --out research/20260826/navigation-generalization/results-h1b-run1.json
~/.cache/parcel-guard/pytest_guard.sh --label nav-generalization-h1b-run2 -- \
  .parcel/bin/python research/20260826/navigation-generalization/experiment_h1b.py \
  --out research/20260826/navigation-generalization/results-h1b-run2.json
~/.cache/parcel-guard/pytest_guard.sh --label nav-generalization-verify -- \
  .parcel/bin/python research/20260826/navigation-generalization/verify_results.py
```

Ruff and Python byte-compilation also pass for all three scripts. Startup logs
include the existing point-goal-fallback warning on observations without a
calibrated scan. This experiment is consequently evidence about the exposed
planner/supervisor behavior in this harness, not a new mapping-quality claim.

Machine artifacts:

- `results.json`, `results-run1.json`, `results-run2.json`;
- `results-h1b.json`, `results-h1b-run1.json`,
  `results-h1b-run2.json`; and
- `verification.json`.

## Research synthesis and proposed system

Source identifiers below refer to `SOURCES.json`. Literature-reported gains
and hardware demonstrations are not presented as Parcel results.

### 1. Keep cognition above a typed, constraint-checked mission layer

NaVILA provides useful primary evidence for a two-level design: a
vision-language layer emits mid-level language/spatial actions while a
real-time locomotion layer executes them [`navila_paper`]. CA-Nav separately
supports decomposing instructions and checking sub-instruction completion
[`ca_nav`]. The safe adaptation for Parcel is not “VLM directly drives Go2.”
It is:

```text
conversation + owner context
          |
          v
typed CompanionMission and ordered subgoal graph
          |
          v
grounding/constraint check --> ask/clarify/decline
          |
          v
metric goal or bounded skill --> navigation executive
          |                           |
          |                           +--> typed blocked/lost/timeout/retry
          v
deterministic safety shell --> sole vendor gateway --> Go2 Sport/skill API
```

The conversation model may select intent, relation, formation and a bounded
expression. It must not choose joint targets, assert physical arrival, or
override a lost/blocked/identity latch. Example composition:

1. “Find me” becomes `SearchOwner(identity=owner, radius, time_budget)`.
2. A fresh identity observation verifies that transition.
3. “Come close enough to ask” becomes `ApproachOwner(target_band_m,
   approach_side)` with a person-space constraint.
4. Speech is released only after a verified stable hold, not an LLM claim.
5. “Walk with me to the door” becomes `FollowFormation` plus a semantic door
   goal, with owner-loss and doorway-yield branches.

H3 in `DESIGN.md` makes this falsifiable on held-out compositions. Score every
transition; final success alone hides false subgoal completion.

### 2. Separate semantic memory from geometric authority

VLMaps demonstrates open-vocabulary spatial features fused with a 3D
reconstruction [`vlmaps`]. Hydra demonstrates an incremental metric-semantic
scene graph with topology and hierarchical loop closure [`hydra_paper`,
`hydra_code`]. GOAT-Bench and HM3D-OVON provide useful task structures for
lifelong, multimodal and held-out-vocabulary navigation [`goat_bench`,
`hm3d_ovon`]. Together they suggest three memories, not one overloaded map:

- a local metric/elevation map for collision and traversability;
- a topological/semantic scene graph for rooms, objects, routes and language;
- an episodic store for observations, owner interactions, outcomes and replay.

The semantic graph proposes candidate regions. The local metric map determines
whether motion is currently possible. Neither may independently declare
arrival after localization discontinuity. Arrival should require a
mission-specific evidence tuple such as `(pose continuity, local geometry,
fresh target/landmark observation, identity where relevant)` and expose why a
component is absent.

This directly addresses R4b: an embedding retrieved from the same aliased map
is not independent evidence. Useful independent options are a globally
discriminative place signature with a calibrated runner-up margin, a fresh
owner/door observation localized relative to the robot, a carried fiducial or
UWB observation, or an operator reset. Until one is present, translation and
completion stay latched.

### 3. Make liveness and failure prediction first-class

Failure-prediction work shows how a learned risk score can be calibrated for
selective autonomy under stated statistical assumptions
[`failure_prediction`]. Certifiably correct mapping motivates shrinking the
claimed safe region as odometric uncertainty grows [`certifiable_mapping`].
STEP supplies a risk-aware traversability pattern based on uncertainty and
tail risk rather than a single mean cost [`step`].

Use these as design patterns, not imported guarantees:

- deterministic hard conditions own stop, stale data, lost localization,
  command bounds, contact and failure budgets;
- a calibrated predictor may recommend slow/replan/ask/decline, but its
  calibration is evaluated on frozen environment and fault splits;
- every active skill has progress, evidence freshness, retry and total-time
  budgets; and
- failure is typed by stage: `ungrounded`, `target_lost`, `pose_lost`,
  `path_blocked`, `terrain_unsupported`, `social_yield`, `execution_timeout`,
  or `completion_unverified`.

The H1/H1b probe shows why the supervisor should consume a typed planner enum
and transition contract, not parse human-readable note strings.

### 4. Treat following and owner search as identity-conditioned navigation

Habitat 3.0 supplies find/follow tasks and safe-distance measurements in
interactive human environments [`habitat3`]. SocNavBench grounds social
scenarios in recorded pedestrian motion [`socnavbench`]. FollowBench varies
target path, crowd flow, corridor/door/intersection geometry, formation and
distance, and explicitly tests occlusion/search [`follow_bench`]. TPT-Bench
targets long disappearance and distractor-heavy identity tracking
[`tpt_bench`]. Adaptive conformal crowd work supplies a current way to measure
uncertainty under distribution shift [`conformal_crowd_safety`].

A production target state should contain identity posterior, bearing/range
covariance, last-seen pose/time, occlusion hypothesis, distractor margin and
track lineage. The policy then chooses among `follow_back`, `follow_side`,
`yield`, `hold`, `reacquire_from_last_seen`, `bounded_search`, and `ask_owner`.
Never silently switch to the nearest person. Search should stop on radius/time,
stairs/door constraints, depleted identity margin or owner cancellation.

The next evaluation should cross these factors rather than add more straight
line episodes:

| Axis | Required held-out values |
|---|---|
| owner motion | stop/start, turn, reverse, speed change, stairs boundary |
| formation | back, left/right side, owner-selected distance |
| visibility | short/long occlusion, exit/re-entry, camera dropout |
| identity | similar clothing, crossing distractor, group merge/split |
| geometry | corridor, doorway, intersection, clutter, dead end |
| social dynamics | oncoming individual/group, overtaking, stationary group |
| mission dialogue | pause, “closer/farther,” correction, cancel, resume |

Primary metrics are identity switches, unsafe target swaps, time/distance in
the requested band, minimum surface distance and exposure below threshold,
collision/contact, jerk, reacquisition time, search area, false reacquisition,
typed termination and owner-command latency. Report formation and scene cells,
not only an aggregate success rate.

### 5. Add a terrain stack before learning stairs

ArtPlanner supports reachability-aware planning with learned motion costs and
explicit concern for negative obstacles [`artplanner`]. STEP supports
uncertainty-aware terrain risk [`step`]. Vision-guided locomotion and RMA
support privileged simulation followed by deployment-time visual/adaptive
policies [`egocentric_locomotion`, `rma2021`]. Classic sim-to-real quadruped
work emphasizes actuator modelling, command latency, identification and
physics randomization [`tan2018simtoreal`].

For Go2, keep two contracts:

- the navigation layer produces a route corridor annotated with slope, step
  height, roughness, edge/drop risk, width, uncertainty and supported skill;
- the locomotion layer accepts a bounded velocity/terrain-skill command and
  returns achieved motion, slip, attitude, foot/contact and abort state.

Near term, use the vendor Sport interface only for supported flat/low-risk
skills and refuse unsupported terrain. For research, train an articulated
terrain policy in the official Unitree/Isaac paths, export it, and keep it
behind the same supervisor. Stairs need 2.5D elevation/traversability,
downward-looking perception or equivalent negative-obstacle coverage, stair
edge/landing detection, a dedicated ascent/descent skill, and fail-safe retreat
or hold. No source reviewed here, and no desktop experiment, proves this
prototype can climb a physical stair.

### 6. Use residual-driven randomization, with a frozen broad holdout

The Unitree repositories provide the lowest-risk articulated integration
starting points [`unitree_mujoco`, `unitree_rl_lab`, `unitree_rl_mjlab`]. Isaac
Lab exposes modular randomization/curriculum machinery and documents important
determinism limits [`isaac_lab_mdp`, `isaac_lab_reproducibility`]. Tan and RMA
support randomizing dynamics and learning/adapting latent environment effects.
Sim2Val supports paired simulator/real measurements when correlation is
actually measured [`sim2val`].

Do not randomize every parameter uniformly. Maintain two sets:

1. a broad frozen holdout that prevents overfitting to known defects; and
2. a curriculum weighted by observed failure clusters and, after Stage-0,
   measured sim/real residuals.

Randomize independently and in combinations:

- payload mass/center of mass, joint gains, friction, restitution and actuator
  strength;
- command and observation delay, jitter, dropped/reordered samples, clock
  skew and process restart;
- LiDAR sparsity, reflective/absorptive surfaces, self-occlusion, rain/dust-like
  outliers and extrinsic error;
- camera lighting, blur, exposure, field of view, obstruction and calibration;
- odometry bias, discontinuity, false loop candidate and repeated geometry;
- terrain slope, compliance, step/edge/gap geometry and low-clearance routes;
- people, groups, speed, intent ambiguity, occlusion and identity distractors;
  and
- language paraphrase, relation, correction, ellipsis and multi-turn context.

H4 pre-registers an equal-compute comparison between uniform broad
randomization and residual-prioritized curriculum once paired bags exist.

## Generalization evaluation program

Every release candidate should have a versioned train/dev/frozen-test split,
an intervention holdout and, eventually, paired real replay. Preserve seeds,
scenario generators, asset/license versions, model and prompt hashes, software
containers and all authority decisions.

Recommended evaluation layers:

| Layer | Test unit | Required headline metrics |
|---|---|---|
| instruction/mission | multi-turn typed task graph | grounding accuracy, clarification quality, unsupported-action rate, subgoal completion, false transition |
| semantic navigation | held-out scene/object/relation | success, SPL/soft-SPL, distance-to-goal, coverage, semantic false arrival |
| localization/completion | dropout, drift, symmetry, kidnap, restart | lost-detection delay, wrong-map commit, false arrival, selective-risk coverage, recovery type |
| planner liveness | new obstacles, doors, narrow routes, crowds | progress, no-progress duration, replans, typed blocked rate, unsafe retry, latency p95/p99 |
| owner follow/search | identity/occlusion/social matrix above | target swap, reacquisition, formation-band exposure, proxemics, contact, jerk |
| terrain/locomotion | procedural slopes/steps/gaps/friction/payload | fall/contact, slip, foot clearance, body attitude, energy, abort success, corridor tracking |
| systems | load, network, process and clock faults | snapshot age, command age, deadline misses, stop path, restart disarm, thermal/power margins |

Use conditional gates so a stationary or failed-to-start agent cannot earn a
safety pass: first require minimum progress/task coverage, then evaluate
contacts and social clearance. Report confidence/calibration by slice; do not
pool unseen stairs with nominal rooms into one flattering average.

For completion authority, add a dedicated false-positive-first score:

```text
completion precision = verified true completions / all declared completions
```

Any declared completion after a known discontinuity without the registered
independent evidence is an automatic gate failure, regardless of SPL.

## Simulator ladder and feasibility

| Tier | Feasibility | Immediate purpose | Exit criterion | Evidence ceiling |
|---|---|---|---|---|
| Current deterministic harness | high / now | Generate minimal refuters for liveness, aliasing, instruction and Follow state machines | all frozen fault cells typed and reproducible | Kinematic/synthetic only |
| Official Unitree MuJoCo + SDK2/DDS | medium-high; official Go2 MJCF assets integrated, native simulator control unintegrated | Exercise its low-level DDS/articulated Go2 surface through a Parcel simulated `SportPort` or high-level bridge; keep fake Sport for gateway lifecycle | deterministic boot/disarm/reconnect, bridge, and command-contract campaign | Not a drop-in high-level Sport emulator; no physical stop, payload or sensor proof |
| Isaac Lab + Unitree RL Lab | medium | Train/evaluate terrain locomotion, privileged teacher, adaptation and dynamics randomization | frozen terrain/mutation suite plus export parity | Simulator dynamics only |
| MetaUrban IPC environment | medium | Procedural crowds, crossings, occlusions and morphology-conditioned social navigation | functioning pinned adapter and unseen-scene campaign | Social simulation, not owner identity hardware |
| Habitat/GOAT/HM3D | medium after assets | Semantic/lifelong goals and human interaction tasks | licensed assets, real episode execution, Go2-shaped action/sensor contract | Different physics/embodiment |
| Stage-0 MCAP/rosbag replay + paired sim | highest value after capture | Stationary clocks, freshness/dropout, calibration plumbing, and pose stability first; LIO/residual work only after controlled-motion recordings | frozen paired scenarios and measured sim-real correlation | Replay cannot validate actuation |

Use the AGX Orin 64 GB as the deployment/inference and hardware-in-the-loop
target. Do not assume it is the mass parallel training host. Run large Isaac
Lab/MetaUrban training on a compatible discrete-GPU workstation or bounded
cloud job; export a pinned policy to Orin and benchmark end-to-end deadlines,
memory, thermals and power there. Unitree's official ROS 2 and MuJoCo repos are
the source of truth for DDS environment setup [`unitree_ros2`,
`unitree_mujoco`].

## Navigation research data design

Keep bulk history outside the dog. The robot should retain a bounded encrypted
upload queue and the maps/model versions needed to operate offline, not the
only copy of research evidence.

- Immutable object storage: MCAP/rosbag2, images, point clouds, audio where
  consented, simulator states, maps and model artifacts, addressed by digest.
- Relational catalog: `mission`, `episode`, `run`, `event`, `transition`,
  `failure`, `metric`, `artifact`, `model_version`, `map_version`,
  `scenario_version`, `consent_and_retention`.
- Derived feature store: target tracks, localization hypotheses, traversability
  tiles, semantic nodes and embeddings. Embeddings are indexes, never the sole
  record.
- Lineage: every outcome links commit/container, policy/prompt/model digest,
  calibration/extrinsics, simulator/asset version, seed, robot configuration
  and raw artifact digests.

Log proposed command, safety-modified command and achieved feedback separately.
Log every evidence component behind a subgoal transition or arrival. Mine
failures into candidates, deduplicate by mechanism, review/redact them, then
place them into train/dev; keep the frozen holdout write-protected. A learned
policy never self-promotes: training may be recursive, deployment remains a
versioned gated release.

Treat Starlink as an opportunistic API/synchronization link. Local stop,
snapshot health, owner-loss behavior, navigation, logging queue and the
currently commissioned conversation fallback must survive total link loss.
Evaluate bandwidth collapse, multi-second jitter, reorder, disconnect and
reconnect explicitly; never route the physical stop path or velocity loop
through the modem.

The recursive learning loop should be explicit and auditable:

1. ingest an immutable episode and compute privacy/consent policy;
2. classify the failure stage and cluster by mechanism;
3. generate minimal deterministic refuters plus randomized neighbors;
4. train or tune a candidate offline against train/dev only;
5. run frozen safety, unseen-composition and simulator-regression gates;
6. review and sign a versioned promotion, then deploy in shadow or the lowest
   authorized physical tier; and
7. compare paired replay/real residuals and feed only reviewed examples into
   the next training set.

The dog learns continuously in the research sense—its evidence continuously
improves later candidates—but no online policy or prompt is allowed to rewrite
the active safety or motion stack by itself.

## Limitations

- No Unitree, AGX Orin, camera, Mid-360, microphone, speaker, Starlink modem,
  stairs or person was used.
- The fresh experiment uses a deterministic kinematic harness and synthetic
  scans. It tests supervisor logic, not locomotion, perception quality or real
  time.
- Repeated identical digests establish software reproducibility, not external
  validity. The held-out seeds share the same generator and map fixture.
- H1b is post-hoc and needs a newly frozen scenario family. Its 30-tick value
  is not calibrated for dynamic people or doors.
- Literature performance is the respective authors' evidence. NaVILA's public
  repository still exposes implementation TODOs; Habitat assets have access
  conditions; and none was installed or benchmarked in this task.
- Reported zero contacts are simulator predicates. They cannot establish body,
  foot, payload, leash, stair or human-contact safety.
