# Sprint 2026-08-05 · task_1 — production navigation and companion behavior

**Type:** implementation-oriented research plan.

**Scope:** navigation, camera/LiDAR perception, owner following, behavior
planning, voice-to-behavior integration, latency, simulation, and evaluation.

**Starting commit:** `4cc2585`.

**Detailed workstreams:** [A — navigation and perception](A-navigation-perception.md),
[B — voice and behavior](B-voice-behavior.md), and
[C — evaluation and delivery](C-evaluation-delivery.md).

## Outcome and recommendation

Parcel should become a **layered companion autonomy stack**, not a single model
that predicts the dog's next velocity. The production baseline should combine:

1. Unitree Sport for balance, gait, posture, and body-velocity execution;
2. ROS 2/Nav2 for map-frame planning, forward-preferred local control,
   replanning, recovery, following, and an independent collision monitor;
3. calibrated camera/LiDAR perception for geometry, semantics, people, and
   enrolled-owner identity;
4. Parcel's typed `PlanSketch`/`PlanIR`, validator, `TaskExecutive`, resource
   arbitration, and semantic task predicates;
5. separate real-time conversation, task-planning, and social-reaction lanes;
6. learned navigation or VLA models only as **bounded goal/waypoint proposers**
   behind freshness, feasibility, costmap, executive, and collision gates.

```text
streaming audio/text                         camera + LiDAR + robot state
  -> deterministic intent/reflex lane           -> calibrated observations
  -> conversation lane                           -> localization/traversability
  -> task-planning lane                          -> owner/dynamic/semantic tracks
  -> social-cue lane                                      |
             |                                             v
             +--> typed PlanSketch / behavior request -> world model
                                      |                    |
                                      v                    v
                             trusted compiler + validator
                                      |
                              TaskExecutive / BT skills
                                      |
                         semantic GoalRegion / OwnerTrack
                                      |
                 GoalArbiter -> Nav2 planner/controller/follower
                                      |
                    independent collision and stale-data gates
                                      |
                        one ControlManager command authority
                                      |
                          Unitree Sport closed locomotion
```

This design does not give up state-of-the-art learning. It makes learned
components replaceable, measurable challengers while keeping the fast safety
and execution loops deterministic. It also follows the useful hierarchy in
[NaVILA](https://navila-bot.github.io/), which emits mid-level spatial actions
above a real-time locomotion policy, and the feasibility-grounded skill
selection pattern in [SayCan](https://say-can.github.io/).

## Current truth: why this is not yet a model-selection problem

The repository already has strong structural foundations:

- `IntentFrame -> PlanSketch/PlanIR -> validator -> TaskExecutive`;
- semantic goal regions, safe approach poses, terminal relation verification,
  owner-relative behaviors, a `GoalArbiter`, and a single velocity arbiter;
- controller feedback, TTLs, watchdogs, stop confirmation, and Unitree Sport
  behind `ControlManager`;
- a deterministic MuJoCo/headless city, dynamic-track costs, TTC/proximity
  gates, latency traces, and append-only evaluation ledgers.

But the evidence says the intelligence and physical seams are incomplete:

- the latest committed `NAV_INSTRUCT_V1` candidate rows are **0/25** and
  **0/8** success, so semantic instruction navigation is not currently a
  credible product capability;
- the current follow benchmark is 8/9 with zero hard collisions, but owner
  reacquisition still gave up in its difficult corner case;
- semantic detections and owner tracks come from simulator metadata, not a
  physical camera model;
- there is no commissioned camera/LiDAR calibration, SLAM/localization stack,
  Nav2 bridge, or physical Go2 run from this workstation;
- `VoiceAgent` is sequential: direct follow/navigation paths bypass the common
  plan lifecycle, deliberative task turns do not concurrently produce natural
  conversation, and social gestures are deferred with a coarse whole-body
  busy flag;
- the pure `StimulusBus` and `ReactionArbiter` exist but are not wired into the
  runtime.

Therefore the first milestone is a reproducible geometric/perception baseline
with frozen contracts and evidence. Downloading a larger VLA first would hide
failure attribution and add latency without fixing calibration, localization,
identity, or collision authority.

## Non-negotiable design rules

1. **One motion writer.** Every planner, learned policy, voice command, UI
   command, and recovery enters the existing arbitration/control boundary.
2. **No model-authored velocity or priority.** Models may propose semantic
   skills, relations, or short-lived goals. Trusted code supplies resources,
   priority, timeouts, recovery, interruptibility, and success predicates.
3. **Camera and LiDAR are the environmental sensors.** IMU, joint state,
   odometry, and controller feedback remain necessary internal state for
   closed-loop localization and locomotion; they are not extra semantic
   authorities.
4. **Semantics do not make space safe.** A label such as `sidewalk` must be
   supported by geometry/traversability and a collision-free approach region.
   Open-vocabulary confidence never clears an obstacle or road keepout.
5. **Identity is explicit.** Losing the owner never falls back to following the
   nearest person. The state is `confirmed -> ambiguous -> lost -> bounded
   search/stop`.
6. **Freshness is data, not convention.** Every observation, track, goal,
   plan, and callback carries source time, local monotonic time, frame,
   covariance/confidence, TTL, scene revision, task revision, and provenance.
7. **Forward is preferred, lateral is legal.** Normal goal travel turns toward
   the route and moves forward. Bounded `vy` remains available for manual
   control, formation adjustment, avoidance, and recovery.
8. **Simulation truth is scorer-only.** Adapters may translate observations
   and actions, but production behavior cannot read privileged poses, semantic
   IDs, collision truth, or shortest paths.
9. **No benchmark-only behavior fork.** External eval adapters wrap the same
   dog interfaces; they do not change Parcel behavior to gain a score.
10. **A safety metric cannot be traded for an average score.** A candidate
    with better SPL but a new collision, false-owner follow, road entry, unsafe
    plan admission, or stale command is not promotable.

## Phased development order

Phases are promotion gates, not calendar promises. Work from later phases may
run in research/shadow mode once its input contracts are frozen, but it cannot
enter the default runtime before the preceding gate passes.

| Phase | Deliverable | Parallel work | Exit evidence |
| --- | --- | --- | --- |
| P0 — contracts and evidence | Version observation/track/goal/behavior/action contracts; TF and clock ownership; calibration files; record/replay; fault injection; frozen baselines | contracts, simulator adapter, rosbag/replay, metrics, scenario authoring | one writer; deterministic replay; stale inputs stop; every physical action traces to an admitted request; baseline stored by run ID |
| P1 — geometric backbone | ROS 2 boundary; camera/LiDAR ingestion; odometry/localization A/B; 2-D/2.5-D traversability; Nav2 adapter; forward-preferred controller; collision monitor; Unitree Sport adapter | localization, terrain map, controller tuning, hardware bridge, headless tests | PointNav/route tasks pass across fixed seeds; zero hard collisions; map/odom/base TF ownership proven; controller deadlines met |
| P2 — correct-owner following | owner enrollment, person detector/tracker, re-identification, LiDAR-associated metric state and covariance, following/reacquisition skill | detector/tracker, ReID gallery, 3-D association, FollowObject comparison, adversarial crowd cases | false-follow and ID-switch gates pass; ambiguity causes safe slow/stop; occlusion/reacquisition scenarios pass |
| P3 — dynamic/social navigation | pedestrian tracks and uncertainty, 0.5–2 s occupancy prediction, proxemic costs, passing/deadlock policy, predictive MPPI critic challenger | prediction, social costmap, dynamic simulation, social metrics | zero collision/TTC regression; fewer freezes; bounded personal-space violations; planner p99 within budget |
| P4 — semantic grounding and active inspection | dedicated road/sidewalk/curb segmentation; open-vocabulary landmarks; OCR/shop enrichment; semantic memory; `GoalRegion`; bounded scan/search | segmentation, open-vocabulary detection, OCR, 3-D fusion, semantic memory, active-perception skills | semantic goal recall/localization and final relation success pass; absent targets end in honest bounded failure; no false-safe region |
| P5 — companion behavior integration | three-lane voice brain, common PlanIR path for physical intents, per-track reaction leases, pause/resume, controller checkpoints, truthful concurrent acknowledgement | voice refactor, executive/arbitration, personality policy, behavior eval, GPU QoS | emergency/manual always win; barge-in affects speech but not motion; social reactions never wrongly preempt base; stale tasks cannot resume |
| P6 — persistent indoor/outdoor operation | place/route graph, loop closure/relocalization, semantic route metadata, keepouts and speed zones, indoor/outdoor mode transitions; external maps remain a disabled sidecar | mapping, route authoring, change detection, long-session tests | multi-session relocalization and route-change recovery; controlled mapped outdoor route completion |
| P7 — learned challengers | NoMaD/LeLaN/VLFM/NaVILA-style waypoint proposers in replay, then shadow, then gated low-speed trials | model adapters, inference optimization, paired A/B eval, license audit | statistically significant held-out gain with no safety/latency regression; every proposal remains bounded and disposable |
| P8 — physical commissioning | stationary -> stand-only -> fenced slow motion -> indoor people -> supervised mapped sidewalk -> restricted city pilot | hardware, QA/safety operator, telemetry review | explicit commissioning record per device/environment; independent E-stop; no claim generalized past tested envelope |

## Parallel workstreams and dependency graph

| ID | Workstream | Main ownership boundary | Depends on | May start |
| --- | --- | --- | --- | --- |
| F | contracts, time, provenance, replay | new versioned DTOs/adapters; no policy | — | immediately |
| N | localization, maps, Nav2, Unitree | ROS 2 service/package boundary plus existing `control/*` and `navigation/*` adapters | F for production wiring | immediately as isolated spike |
| O | owner/person perception | detection, ReID, LiDAR association, `OwnerTrack` publisher | F | on recorded/sim data immediately |
| S | scene semantics | region segmentation, open-vocabulary objects, OCR, semantic memory | F | on recorded/sim data immediately |
| B | voice and behavior | `agent.py`, `brain/*`, `attention/*`, activities/resume; no nav internals | F | immediately with fake tracks/actions |
| D | dynamic/social planning | prediction and Nav2 cost/critic plugins | F + initial N/O contracts | after track schema freeze |
| E | simulation and evaluation | scenario adapters, scorers, fault injector, ledger, CI | F only | immediately and continuously |
| L | learned proposer research | sidecar inference adapters only | F + frozen N/S/O baselines | replay spike now; promotion after P6 |
| H | hardware commissioning | launch/config/calibration and evidence; no feature invention | P1–P6 gates | last |

```text
                 +--> O owner tracking -----+
F contracts -----+--> S scene semantics ----+--> D social/semantic nav --> H
  |              +--> B voice behavior -----+          ^
  |              `--> N geometric nav -------+----------+
  +------------------> E eval (continuous) --+----------+
                                   L learned proposers --'  (shadow first)
```

The first integration slices are deliberately narrow:

1. voice -> typed orbit task -> simulator predicate verification;
2. voice -> social cue -> audio-only overlap or safely deferred body gesture;
3. voice -> sidewalk query -> `GoalRegion` -> Nav2 -> `inside(sidewalk)`;
4. enrolled `OwnerTrack` -> follow -> ambiguity -> search -> verified reacquire;
5. all lanes concurrently under camera load, model load, TTS, barge-in, and
   injected stale/dropped observations.

## Technology decisions to validate, not assume

| Layer | Baseline to build | Challengers / reason for spike | Decision gate |
| --- | --- | --- | --- |
| body control | Unitree Sport through existing `ControlManager` | future custom controller behind `LocomotionController` | physical feedback, stop, fault, and body-frame commissioning |
| navigation | Nav2 with MPPI, rotation shim/forward preference, route/keepout/speed metadata | Graceful Controller; current `grid_v1` remains deterministic CI reference | paired route success, collision, path, jerk, CPU and deadline results |
| localization | KISS-ICP as permissive simple baseline | Unitree Point-LIO/FAST-LIO family and RTAB-Map; Point-LIO GPL implications | identical recorded bags, drift/relocalization/CPU, exact license audit |
| terrain | Nav2 costmaps plus 2.5-D elevation/traversability | Elevation Mapping CuPy; NVIDIA nvblox when target GPU permits | curbs, low obstacles, slopes, overhangs, latency and VRAM |
| owner tracking | person detector + ByteTrack + enrolled FastReID + LiDAR association | SAM 2 propagation or MASA association as helpers, never identity truth | HOTA/IDF1, false-follow/hour, pose covariance, occlusion |
| sidewalk/road | compact dedicated closed-set segmenter | CAT-Seg/open-vocabulary segmenter for labeling/discovery | road/sidewalk/curb IoU and false-safe-region rate on dog-height video |
| landmarks | OmDet-Turbo or original local Grounding DINO benchmark | SAM 2 masks; query-driven alternatives | recall/precision, metric localization, target-device p95, license |
| shop/brand | PaddleOCR plus storefront geometry and optional logo retrieval | Florence-2 asynchronous enrichment | end-to-end named-place precision and honest abstention |
| semantic memory | Parcel v2 entity/region store first | Hydra, ConceptGraphs, DualMap/OVO sidecars | query benefit, stale-memory harm, compute, dependency/weight licenses |
| human prediction | Kalman/IMM constant-velocity with uncertainty inflation | licensed learned predictor only in shadow first | collision prediction recall, calibration, 0.5/1/2 s latency |
| learned nav | NoMaD/ViNT and LeLaN are the first deployable spikes | VLFM pattern; NaVILA/Qwen-RobotNav only when exact weights/license/runtime exist | same `SE2Goal` contract, paired seeds, no gate increase |

Useful primary references include Nav2's
[MPPI controller](https://docs.nav2.org/configuration/packages/configuring-mppic.html),
[dynamic following server](https://docs.nav2.org/tutorials/docs/navigation2_dynamic_point_following.html),
[Collision Monitor](https://docs.nav2.org/tutorials/docs/using_collision_monitor.html),
[keepout filters](https://docs.nav2.org/configuration/packages/costmap-plugins/keepout_filter.html),
and [speed filters](https://docs.nav2.org/tutorials/docs/navigation2_with_speed_filter.html).
The [CMU Go2 autonomy stack](https://github.com/jizhang-cmu/autonomy_stack_go2)
is a valuable hardware reference but explicitly reports L1 noise, weak
sub-0.3 m obstacle handling, SLAM drift, and unsynchronized camera timestamps;
benchmark it as a baseline instead of importing it as an unquestioned product
dependency.

## Simulation portfolio

No simulator covers all required evidence. Keep a portfolio behind stable
observation/action adapters:

| Environment | Use | Does not prove |
| --- | --- | --- |
| Parcel MuJoCo/headless | fast deterministic task logic, arbitration, semantic predicates, CI and fault injection | physical camera recognition, dense crowds, realistic gait/contact |
| [MetaUrban](https://metadriverse.github.io/metaurban/) | procedural outdoor streets, sidewalks, objects, vehicles, pedestrians, PointNav/SocialNav | real Go2 sensing, identity, actuator dynamics, human behavior validity |
| [Habitat 3.0](https://aihabitat.org/habitat3/) | indoor human following/social navigation and interactive human-in-loop cases | outdoor cities or Unitree dynamics |
| [iGibson](https://svl.stanford.edu/igibson/) | indoor interactive/social navigation regression and comparison with the cited Stanford example | current production stack or Go2 embodiment out of the box |
| [URBAN-SIM](https://metadriverse.github.io/urbansim/) / [Isaac Lab](https://github.com/isaac-sim/IsaacLab) | articulated Go2 physics, procedural urban learning and sim-to-sim stress | sim-to-real safety without physical commissioning |
| recorded camera/LiDAR/robot-state replay | real sensor timing, calibration, model accuracy and deterministic regressions | closed-loop consequences |
| supervised hardware courses | final motion, acoustic, identity and system evidence | unrestricted autonomous city operation outside the tested envelope |

MetaUrban is the first dynamic-city adapter because it procedurally composes
urban layouts and moving agents and already defines PointNav/SocialNav metrics.
URBAN-SIM/Isaac is the later articulated-physics/training lane. iGibson remains
valuable for indoor social and interactive tasks, not as the one universal
simulator.

## Evaluation and latency gates

The complete protocol is in [C-evaluation-delivery.md](C-evaluation-delivery.md).
Headline rules:

- score final task predicates, not planner self-reports or arrival at one
  magic coordinate;
- retain SR, OSR, SPL/soft-SPL, distance, failure layer, collisions, TTC,
  clearance, road exposure, jerk, deadline misses, and resource use;
- separately score semantic perception, owner identity/tracking, social
  comfort, voice/behavior correctness, and verified-success precision;
- use paired frozen seeds, hidden held-out scenarios, Wilson/bootstrap
  intervals, and per-change immutable reports/ledger rows;
- keep external metrics disaggregated. BARN measures constrained metric
  navigation; Habitat measures embodied indoor navigation; MetaUrban measures
  urban/social navigation; Parcel's product suite measures companion tasks.
  A higher external score never authorizes a product regression.

Provisional design targets—**not current claims**—include:

| Path | Gate |
| --- | ---: |
| safety/control loop | 50–100 Hz; P99 deadline miss rate reported; stale data fails to zero |
| local planning/control | 20–50 Hz; P95 <= 50 ms |
| owner camera -> metric track | 15–30 Hz where hardware permits; P95 <= 150 ms |
| compact segmentation | 5–15 Hz; P95 <= 200 ms |
| open-vocabulary/OCR | 1–5 Hz or on demand; latest-frame queue and TTL |
| final text -> deterministic route | P95 <= 10 ms |
| query end -> first acknowledgement text | P50 <= 150 ms, P95 <= 300 ms |
| query end -> first audible/logged response | P50 <= 350 ms, P95 <= 700 ms |
| query end -> admitted plan | P50 <= 400 ms, P95 <= 900 ms |
| obstacle observation -> issued safe zero | P99 <= 100 ms |
| spoken emergency end -> confirmed physical stop | P99 <= 300 ms on hardware |

The current Gemma planner's measured multi-second latency is far above the plan
target. The response lane must acknowledge concurrently, the planner must be
interruptible, frequent intents should use deterministic compilation, and no
unmeasured model swap is allowed to redefine the target.

## Board for implementation kickoff

| Card | Deliverable | Owner lane | Depends on |
| --- | --- | --- | --- |
| F0 | contract RFC: timestamp/frame/provenance envelope; `OwnerTrack`, `DynamicTrack`, `SemanticRegion`, `GoalRegion`, `SceneQuery`, `DialogueAct`, `SocialCue`, `SkillFeedback` | F | — |
| E0 | freeze current nav-instruct/follow/embodied/voice/latency baselines with manifest hashes and known-failure assertions | E | — |
| E1 | deterministic event + camera/LiDAR/robot-state replay and fault injector | E | F0 |
| N0 | ROS 2/Nav2 spike in an isolated service/container; one goal action, feedback, cancel, stop | N | F0 |
| N1 | KISS-ICP versus sensor-matched LIO bag study; declare TF ownership | N | F0 E1 |
| N2 | MPPI forward-preferred controller + collision monitor + keepout/speed semantics | N/D | N0 N1 |
| O0 | owner enrollment dataset and person track/ReID baseline | O | F0 |
| O1 | camera/LiDAR association, covariance/freshness, ambiguous/lost behavior | O | O0 E1 |
| S0 | dog-height road/sidewalk/curb dataset and compact segmentation baseline | S | F0 |
| S1 | landmark detector + SAM mask + OCR enrichment A/B; semantic memory publisher | S | S0 E1 |
| B0 | split `VoiceAgent` into deterministic, conversation, planner and social-cue services; remove physical tools from conversation | B | F0 E0 |
| B1 | compile every positive physical voice intent through common PlanSketch/PlanIR admission; keep emergency/stop fast path | B | B0 |
| B2 | wire reaction stimuli/arbiter, per-track resources, fresh pause/resume and actual audio completion | B | B0 F0 |
| D0 | dynamic prediction + proxemic costs; social costmap baseline | D | N2 O1 |
| V0 | vertical slice: voice -> sidewalk -> GoalRegion -> Nav2 -> verified stop | B/S/N/E | N2 S1 B1 |
| V1 | vertical slice: owner follow -> distractor/occlusion -> reacquire; converse/react concurrently | B/O/N/E | N2 O1 B2 |
| L0 | replay-only NoMaD/LeLaN/VLFM/NaVILA availability, license and adapter study | L | F0 E1 |
| H0 | physical commissioning checklist, test course, E-stop and evidence template | H | N2 O1 S1 B2 |

## Definition of done for this program increment

- The current baselines are reproducible and no existing result is rewritten.
- One frozen vertical slice completes `go to the sidewalk`, `wait near the
  lamppost`, `circle the owner`, and enrolled-owner follow with final semantic
  predicates, not teleports or oracle behavior inputs.
- A dynamic city suite contains moving pedestrians, occlusion, crossings,
  groups, storefronts, road/sidewalk boundaries, indoor transitions, absent
  targets, and sensor/compute faults.
- Navigation is smooth and body-forward by default; lateral travel is measured
  and justified rather than globally prohibited.
- The dog can acknowledge and converse while a task planner works; audio-only
  reactions may overlap navigation, while base/posture reactions defer or
  expire according to explicit resource policy.
- Every task supports cancel, timeout, feedback, verified completion, bounded
  recovery, generation-safe stale callback rejection, and fresh resume.
- Every promoted component has an immutable run ID, commit/config/checkpoint
  hashes, seed set, latency/resource distribution, failure histogram, and
  honest `does_not_prove` field.
- Learned policies remain optional challengers until they beat the frozen
  baseline on held-out data with no collision, identity, road, latency, or
  deadline regression.

## Research sources

- Navigation and control: [Nav2](https://github.com/ros-navigation/navigation2),
  [MPPI](https://docs.nav2.org/configuration/packages/configuring-mppic.html),
  [Following Server](https://docs.nav2.org/configuration/packages/configuring-following-server.html),
  [Unitree SDK2 SportClient](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/go2/sport/sport_client.hpp),
  [CMU Go2 autonomy stack](https://github.com/jizhang-cmu/autonomy_stack_go2),
  and [Elevation Mapping CuPy](https://github.com/leggedrobotics/elevation_mapping_cupy).
- Perception and maps: [ByteTrack](https://github.com/FoundationVision/ByteTrack),
  [SAM 2](https://github.com/facebookresearch/sam2),
  [Grounding DINO](https://github.com/IDEA-Research/GroundingDINO),
  [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR),
  [VLMaps](https://vlmaps.github.io/), and
  [ConceptFusion](https://concept-fusion.github.io/).
- Learning and behavior: [NoMaD](https://general-navigation-models.github.io/nomad/),
  [VLFM](https://arxiv.org/abs/2312.03275),
  [NaVILA](https://navila-bot.github.io/),
  [SayCan](https://say-can.github.io/),
  [Inner Monologue](https://arxiv.org/abs/2207.05608), and
  [BehaviorTree.CPP](https://www.behaviortree.dev/).
- Simulation/evaluation: [MetaUrban](https://metadriverse.github.io/metaurban/),
  [Habitat 3.0](https://aihabitat.org/habitat3/),
  [iGibson Social Navigation](https://svl.stanford.edu/igibson/challenge.html),
  [BARN](https://www.cs.utexas.edu/~xiao/BARN/BARN.html),
  [DynaBARN](https://www.cs.utexas.edu/~pstone/Papers/bib2html/b2hd-ssrr22-nair.html),
  and [SocNavBench](https://github.com/CMU-TBD/SocNavBench).

## Fable adjudication (2026-08-05) — appended

An independent Fable research plan was produced without reading this
document ([fable-research-plan.md](fable-research-plan.md), workflow
`wf_44b643ea-490`), then the two were adjudicated in
[ADJUDICATION.md](ADJUDICATION.md). Outcome: ~80% independent convergence;
this program's contracts, four-lane voice architecture, truthfulness rules,
and statistical machinery are adopted — with four binding corrections:
no Nav2 authority migration in v1 (challenger behind a named Phase-3
decision gate), voice differentiator enters the runtime on its own gates
(Phase 2, not P5), hardware procured in Phase 0 and commissioned in
Phase 2 (not P8), and the goal-calibration fix is the first card (the 0/25
row partially reflects three disagreeing "arrived" definitions, verified
against episode traces). UWB (`rt/uwbstate`) — absent from this document —
is restored as a first-class owner channel pending characterization. The
binding kickoff board lives in the adjudication.

**Owner amendment (same day):** hardware is purchased **last**; the
simulator is the test substrate throughout — close to this document's
original P8 sequencing. The adjudication's D4 ruling is superseded and its
Owner-amendment section carries the revised phase structure, the
sim-substitution rules, and the hardware-readiness ledger requirement.

## Explicit limits of this plan

- “Seamless around cities” is a program goal, not a present capability or a
  single acceptance test. With local camera/LiDAR and no GNSS/prior map, the
  first outdoor scope must be mapped or topological routes plus bounded local
  exploration.
- Nav2 Collision Monitor and Parcel's software gates are not certified safety
  systems. Unitree protections and an independent physical E-stop remain
  mandatory.
- Exact model/checkpoint licenses, transitive dependencies, and commercial
  terms must be audited independently. A repository's permissive code license
  does not automatically cover its weights or datasets.
- Open-vocabulary, OCR, simulated social behavior, and leaderboard scores are
  evidence within their scopes; none proves safe real-city deployment.
