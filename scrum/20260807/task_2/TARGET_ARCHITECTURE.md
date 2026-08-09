# Target navigation and companion-behavior architecture

## Design thesis

The product should behave like one coherent dog, but it should not be one
model. Different decisions have different time scales, evidence needs, and
failure costs. The architecture therefore separates conversation, task
reasoning, semantic perception, metric navigation, locomotion, and safety while
joining them through typed, time-bounded contracts.

```text
                         owner speech
                              │
                 final ASR + turn/epoch identity
                              │
          ┌───────────────────┴────────────────────┐
          │ literal stop/manual safety path        │ streamed conversation
          │ reviewed common-intent compiler        │ (no motion authority)
          │ slow planner for novel/compound tasks  │
          └───────────────────┬────────────────────┘
                              │ TaskRequest / TaskSketch
                    trusted compiler + validator
                              │
                 TaskExecutive / reactive subtrees
            resources · deadlines · recovery · witnesses
                              │ semantic goal / formation goal
                              v
 camera ─┐             semantic/topological memory
         ├─> synchronized perception snapshot ────┤
 LiDAR ──┘       owner/people/regions/entities      │
                              │                     │
                         route planner <────────────┘
                              │
      learned waypoint/trajectory proposers (optional, TTL, shadow first)
                              │
               feasibility + frame + freshness validation
                              │
                global path + local controller
                              │
             one velocity smoother / actuator shaper
                              │
       FINAL independent metric-geometry monitor + hard zero
                              │
                  Parcel ControlManager / watchdog
                              │
                 Unitree Sport Move / StopMove
                              │
          onboard closed-loop gait, balance, joint control
```

## Time-scale budget

These are proposed design bands, not current measurements or safety guarantees.
Every rate must be remeasured under full GPU co-residency.

| Layer | Target cadence | Deadline behavior |
| --- | --- | --- |
| Unitree onboard balance/gait | vendor controller rate | owned by Sport; Parcel never emulates balance in Python |
| Raw geometry safety and command watchdog | 50–100 Hz | stale/missing evidence or deadline miss forces exact zero |
| High-level velocity control / local planner | 20–50 Hz | reuse last still-valid plan briefly; never reuse an expired safety verdict |
| Camera capture | ~30 Hz | timestamp and retain bounded history; drop oldest work |
| LiDAR/geometric mapping | 10–20+ Hz, sensor-driven | reject invalid transform/skew; safety consumes freshest valid geometry |
| Person detector/tracker/owner association | 15–30 Hz | ambiguous/lost owner slows or stops; no nearest-person substitution |
| Semantic segmentation | 5–15 Hz | stale regions lose planning confidence; fresh metric geometry remains live |
| Global route / topological planner | 1–5 Hz or event-driven | old route can remain advisory while local safety/controller runs |
| Open-vocabulary detection/OCR | 0.2–2 Hz/on demand | task waits/scans/clarifies; never blocks safety/control |
| Learned navigation proposer | ~1–10 Hz by model | latest-only buffer; task/revision/observation TTL; expired output discarded |
| Task executive | event-driven plus ~10 Hz supervision | deadlines/recovery/verification continue while model service is absent |
| Common deterministic intent | single-digit milliseconds target | safe local compile or explicit clarification |
| Novel task planning | asynchronous | immediate acknowledgment; bounded plan deadline; failure returns clarify/hold |
| Conversation/TTS | streaming | may overlap locomotion; action tags are proposals, not authority |

## 1. Locomotion and control

### Decision

Keep Unitree Sport as the closed-loop locomotion controller. Parcel should send
bounded body-frame `vx`, `vy`, and yaw-rate targets, observe fresh state, and
own task-level control and safety. Lateral velocity remains supported for
manual commands and constrained local avoidance, but ordinary travel should
penalize lateral motion and prefer yaw alignment followed by forward motion.

### Nav2 sidecar

Do not rewrite all of Parcel around ROS. Add an isolated, pinned ROS 2/Nav2
service behind a narrow protocol. `grid_v1` remains the production writer and
CI reference until a frozen, matched-information comparison satisfies the
promotion gates; the sidecar is an exclusive challenger, never a second active
velocity writer:

```text
Parcel task executive
  -> NavigateGoalV1 / FollowFormationGoalV1
  -> Route Server / semantic route graph
  -> Smac 2D global baseline
     (State Lattice challenger for heading/footprint constraints)
  -> validated path smoother
  -> Regulated Pure Pursuit baseline
     OR MPPI challenger for dynamic/local optimization
  -> exactly one velocity smoother
  -> Parcel final independent metric-geometry monitor
  -> Unitree Sport
```

Use Nav2's Rotation Shim contextually at the beginning of large heading changes
or after replanning. Do not mandate turn-in-place everywhere: rotating a
quadruped's full footprint can be less safe in a tight crowd than a smooth arc.
MPPI should penalize lateral velocity, excessive yaw, reversal, oscillation,
jerk, person risk, and road/sidewalk constraint violations; none is allowed to
reduce a hard collision cost.

Advantages:

- mature lifecycle, action, planner, controller, smoothing, behavior-tree, and
  costmap interfaces;
- the current BARN smoke already shows upstream MPPI solving one world where
  Parcel timed out;
- C++ high-rate control can be isolated from the Python voice/reasoning loop;
- RPP supplies an interpretable deterministic baseline for every learned or
  optimized challenger.

Limitations:

- Nav2 is not a complete social, semantic, owner-identity, or instruction
  system;
- mixed package/asset licenses and ROS distribution compatibility require a
  pinned deployment image;
- its Collision Monitor is a valuable defense, not a certified functional
  safety system;
- a circular differential-drive benchmark does not validate a Go2 footprint,
  gait, curb, or stopping envelope.

## 2. State estimation and geometric safety

### Required state contract

```text
PoseEstimateV1 {
  odom_T_base, map_T_odom, covariance,
  captured_at, received_at, transform_epoch,
  health: HEALTHY | DEGRADED | LOST,
  source, calibration_id
}
```

The controller consumes continuous ODOM. Global/semantic goals live in MAP.
Every proposal states its frame and observation time and is transformed through
recorded history; a missing transform rejects the proposal. A MAP correction
may move the global goal without discontinuously changing the local velocity
controller.

Use a two-rate producer: continuous ODOM at least 20 Hz for control, plus
slower 1–5 Hz MAP corrections that may jump without discontinuously changing
local commands. Start with the CMU Go2 autonomy stack as a hardware baseline
and compare SLAM/local-mapping candidates rather than inventing everything in
Parcel:

- FAST-LIO2 as the first ODOM candidate when an external Mid-360-class sensor
  is fitted;
- Point-LIO/CMU stack for the built-in Go2 L1 LiDAR/IMU baseline;
- scan-to-map localization for MAP corrections, with LIO-SAM or RTAB-Map as
  loop-rich mapping backends rather than the reactive ODOM default;
- DLIO as a logged-bag continuous-time challenger;
- RTAB-Map as a mature vendor-neutral RGB-D/3D-LiDAR integration path;
- NVIDIA nvblox as an Orin-accelerated TSDF/ESDF and Nav2 costmap path;
- elevation_mapping_cupy as a legged-terrain/curb/slope challenger;
- SLAM Toolbox/AMCL only as planar indoor baselines.

The mounted sensor geometry decides whether the robot can see negative
obstacles, curbs, and stair edges. If the L1 LiDAR/camera mount cannot meet a
measured recall and stopping-distance gate, deployment requires a depth camera
or more suitable 3-D LiDAR; software confidence cannot fill a physical blind
spot.

Treat the CMU stack as evidence and a baseline, not as a turnkey safety claim.
Its Go2 documentation reports weak discrimination for obstacles below roughly
0.3 m, occasional SLAM drift, camera timestamps not synchronized with
LiDAR/IMU, and more than one second of delay in one external ROS 2 Humble path.
Before choosing that path, measure low-obstacle, curb, stair-edge, glass, and
drop-off recall on the actual mount; capture-time synchronization; transform
error under gait vibration; and command-to-feedback delay. The result may
require depth or a better-sited 3-D LiDAR rather than a software-only fix.

### Final safety contract

The last component before `ControlManager` consumes the freshest independently
validated metric geometry and the actual shaped command. Required sources are
defined by the commissioned ODD: LiDAR plus depth/stereo or another camera-
derived metric negative-obstacle channel where the L1 cannot cover low objects,
curbs, stairs, or drop-offs. Each source has its own field of view, capture
timestamp, calibration/transform, health, and degraded behavior. Obstacles are
combined conservatively; one source cannot vote another source's obstacle away,
and uncovered space is not declared free. RGB semantics may tighten a rule but
never establish clearance.

The monitor checks swept footprint, directional clearance, braking distance,
TTC, state/transform age, and controller feedback. It can tighten or stop but
never widen an upstream envelope. A hard stop forces exact zero after shaping
and resets state. Loss of any source required for the commanded direction and
ODD is STOP/HOLD, not a point-goal fallback. If only the L1 LiDAR is fitted, the
physical ODD excludes conditions its measured coverage cannot protect.

### Physical ODD and manual control

Before HIL or physical motion, maintain a reviewed operational design domain:
surface/friction, slope/step/curb limits, weather/water, illumination, crowd and
animal density, speed, sensor field-of-view/occlusion, compute/thermal state,
wireless dependence, and supervision/fence requirements. Link an FMEA/STPA-
style hazard log to mitigations, tests, residual-risk owner, incident/replay
procedure, and explicit go/no-go signoff. Simulator success is evidence for
those claims, not the safety case itself.

Authenticated joystick/UI/API control changes the command source, never the
safety path: it still traverses leases, robot limits, watchdog, shaping, final
geometry monitor, and E-stop. The CMU reference stack documents a manual mode
separate from its collision-avoiding smart-joystick mode; Parcel must not expose
any collision-bypassing manual mode as a safe product path.

## 3. Perception and semantic memory

### Three independent paths

```text
camera + LiDAR + internal IMU/odometry
  ├─ geometry: occupancy / traversability / TTC       20–50 Hz
  ├─ fast semantics: owner, people, road, sidewalk,
  │                 vehicles, doors, poles, obstacles 10–30 Hz
  └─ queried semantics: open-vocab objects, shops,
                       signs, OCR, masks                0.2–2 Hz
```

Recommended first components are RT-DETR for fast closed-set objects,
PP-LiteSeg for regions, a robust tracker, and a Parcel-owned owner identity
associator. Grounding DINO + SAM 2.1 + PaddleOCR form a slower query service.
They are model candidates, not a promise that their published GPU speeds will
transfer to Orin.

Camera–LiDAR association must use hardware capture timestamps, calibrated
six-degree-of-freedom transforms, camera intrinsics, and robust mask/point
association. Arrival-time synchronization is insufficient on a moving body.
Reject excessive skew or absent transforms instead of publishing a confident
wrong landmark.

### Semantic memory

Build a small typed memory before adopting a large scene-graph framework:

```text
SemanticEntityV1 {
  uuid, aliases, class_posterior, embedding, ocr_text,
  map_region_or_pose, covariance,
  first_seen, last_seen, ttl, mobility,
  source_evidence_ids, calibration_id, scene_revision,
  state: RESOLVED | AMBIGUOUS | UNSEEN | STALE
}
```

Reachability comes from geometry, never the VLM. Movable objects decay faster
than static landmarks; terminal success requires fresh re-observation. Clio,
Khronos, VLMaps, and ConceptGraphs are later adapter comparisons, not immediate
replacements for this contract.

### City-scale scope

Phase 1 navigation is limited to the locally mapped or currently observable
area. “Go to the store” can resolve a fresh known POI or run a bounded semantic
search within that area; it is not yet arbitrary city routing. A later city-
scale contract must add a `GEO`/world frame, uncertainty-bearing
`GEO -> MAP -> ODOM` handoffs, map/route version and freshness, outdoor/indoor
transition localization, geofences/road-crossing policy, connectivity loss, and
local re-grounding of every external destination. Google Maps or other network
maps remain advisory placeholders: they may nominate a route/POI but never
declare traversability, free space, or arrival.

## 4. Owner tracking and social navigation

### Identity before following

Transient tracker IDs are not identities. Enroll a consented multi-view owner
gallery, then fuse appearance, metric position/depth, motion continuity,
visibility, and evidence age into an identity posterior. Use M-of-N
confirmation and a margin over the second-best candidate. During a crossing or
long occlusion, emit `AMBIGUOUS`/`LOST`, decelerate or stop, search, and if
necessary ask the owner to identify/call themselves. Never silently choose the
closest person.

### Formation-goal controller

At 10–20 Hz, sample reachable poses around the predicted owner. Score:

- requested formation (behind, side, come-here approach);
- consented distance band and owner visibility;
- static path/traversability and occlusion;
- predicted stranger/group personal space;
- sidewalk/road context;
- route length and temporal stickiness.

Submit one short-TTL SE(2) goal/corridor to the common planner. Behind is a
preference in crowds/narrow spaces, not a fixed point that can land across a
wall. The commissioned independent metric-geometry lane remains the hard
authority; required LiDAR/depth/stereo sources depend on the ODD and their
validated directional coverage.

Use a simple uncertainty-aware CV/CA/turn predictor first. A multimodal learned
human predictor promotes only if calibration and closed-loop outcomes improve.
Soft social costs may influence route choice; they do not replace geometry.

MiniCPM-RobotTrack is the first learned shadow comparison because it releases
Apache-2.0 weights, emits eight `(x,y,yaw)` waypoints, and documents Go2/Orin
deployment. Its authors also report nonzero collision rates and warn about
behavior without a visible target, which is exactly why identity, presence,
TTL, reachability, and safety gates remain outside the model.

## 5. Instruction following and task behavior

### One canonical task request

Replace repeated transcript parsing with:

```text
TaskRequestV1 {
  speech_act,
  task_kind,
  semantic_arguments,       # entity/region/relation/formation
  quantities_and_units,     # 5 steps, one orbit, 1 m
  constraints,              # stay off road, behind owner
  candidate_handles,
  ambiguity_and_confidence,
  amendment_or_cancel_target,
  communicative_urgency_cues,
  input_channel,
  speaker_claim_and_evidence,
  authorization_class,
  replay_risk,
  transcript_ref,
  observation_snapshot_id
}
```

A trusted policy converts communicative cues into task timing and interruption;
the model cannot label itself high priority. Common commands compile locally.
A tiny function-calling model such as FunctionGemma may later shadow the typed
parser, but it is not the conversation brain or task executive.

Authentication is independent of intent quality. An enrolled/local owner or
explicitly authorized control channel may request motion; a bystander, TV,
phone replay, remote stream, OCR result, storefront sign, or retrieved web text
cannot silently acquire the base. Anyone may issue the literal emergency-stop
phrase, because stopping is safer than trying to authenticate first. Every
other safety-relevant command records speaker/channel evidence and an
authorization decision, and ambiguous speech asks or holds.

Natural units and implied scale are resolved before control. “Walk away from
me five steps” becomes a bounded owner-relative metric goal using the robot
profile's calibrated nominal step length; it is not five timed velocity bursts.
“Walk around me once” becomes an `OrbitOwner` goal with one revolution and a
small, free-space-clamped companion radius; it is not an unconstrained route
around the block. The planner may use reverse motion when that best preserves
owner visibility and safety, but the controller still verifies the whole swept
path. If the implied goal is infeasible or unsafe, the task adapts within its
declared bounds or asks rather than silently changing scale.

### Fast and slow lanes

- **Literal lane:** stop/E-stop/manual/cancel. No LLM.
- **Reviewed common lane:** sidewalk, lamppost, come here, follow behind, wait,
  bounded relative steps, small orbit, pace changes. Deterministic parse and
  compile.
- **Slow semantic lane:** novel references, compound goals, underspecified
  destination, multi-step errands. Model proposes a `TaskSketch` DAG against an
  immutable evidence snapshot.
- **Conversation lane:** existing Gemma streams independently. It may
  acknowledge and converse while planning continues, but cannot report physical
  completion before the executive's witness.

Remove the configured 90-second wait from the authoritative task path. Freeze
separate acknowledgment, typed-intent/admission, first-safe-action, and usable-
plan deadlines from measured p95/p99 service traces and task risk. Send a brief
acknowledgment while planning, but after the plan hard deadline the executive
must HOLD/clarify/fail the task. Optional background research may continue only
as non-authoritative work; a late plan can be admitted as a new revision only
if its owner intent, task lineage, evidence, and deadline are still current.

### Trusted compilation and reactive execution

The reasoning model should output the next **semantic skill or goal proposal**,
not the next motor move. A navigation VLA may separately propose a short local
trajectory. The local controller alone computes the next velocity tick. A new
proposal does not automatically override current work: the executive checks
task identity, explicit owner intent, safety, resources, interruptibility, and
checkpoint state, then executes, defers, queues, drops, or asks. This is how a
sad-owner bow can wait behind a road-exit maneuver while an explicit emergency
stop remains immediate.

The model may select only audited symbolic skills:

```text
NavigateTo      ApproachOwner      FollowFormation (persistent)
OrbitOwner      MoveRelative       Hold
AskClarification Vocalize          ExpressiveGesture
ReturnToSafePose
```

The compiler owns IDs, resources, safety invariants, deadlines, checkpoints,
retry/recovery budgets, interruption class, and terminal witnesses. The
executive executes async goal/feedback/result/cancel operations. A cancel
request is not a transfer of authority until the controller acknowledges it
and fresh feedback proves the body stopped.

Recovery is a bounded typed subtree, for example:

```text
grounding failure -> rescan -> alternate candidate -> semantic frontier search
no route          -> clear/rebuild local map -> alternate approach -> ask/refuse
controller stall  -> stop -> short safe backoff/scan -> replan -> fail safely
owner lost        -> controlled deceleration under fresh geometry -> HOLD
                  -> stop-and-look -> bounded belief search -> ask
```

Any concurrent safety/state evidence loss bypasses controlled deceleration and
forces hard zero; “owner lost” never authorizes unmonitored coasting.

### Clarification

Keep `ClarificationPending{task_id, revision, slot, candidate_handles,
evidence_snapshot_id, expires_at}`. Ask the minimum discriminating question;
bind the answer to the same task lineage. If evidence changed or expired, say
so and re-ground. Never convert uncertainty into an arbitrary nearest target.

### Affect and gestures

The conversation/affect model outputs a low-priority proposal such as
`{gesture|null, confidence, evidence, valid_until}`. The behavior arbiter maps
explicit owner request, inferred affect uncertainty, locomotion criticality,
checkpoint state, and resource availability to `execute`, `defer`, or `drop`.

- audio, gaze, and small expression overlays can often overlap navigation;
- a laugh/chuckle or brief verbal reaction normally uses only the audio lane
  and can overlap a safe ongoing task without changing its locomotion lease;
- posture gestures such as bow/stretch/paw wave require a safe checkpoint or
  idle base, an audited clip, duration, settle pose, and completion result;
- an important navigation, follow, recovery, manual, or safety action is never
  interrupted by inferred affect;
- explicit owner requests may queue, but still cannot override safety.

## 6. Learned navigation interface

Every navigation model implements the same out-of-process proposal contract:

```text
NavProposalV1 {
  model_id, model_hash, task_id, task_revision,
  observation_ids, captured_at, produced_at, expires_at,
  frame, relative_se2_waypoints[], time_from_start[],
  waypoint_covariance[], arrival_probability,
  confidence, task_mode, footprint_profile_id, kinematic_profile_id,
  input_abi_hash, calibration_abi_hash,
  evidence_handles, diagnostics
}
```

The receiver checks schema, finite bounds, frame transform, observation/task
generation, TTL, local reachability, hard masks, and collision. It may select,
truncate, replan through, or reject a proposal. It never forwards model output
directly to Sport.
Per-waypoint uncertainty is calibrated by the adapter on held-out Parcel data;
a raw logit or model-written “confidence” is not calibration. If uncertainty is
unknown, the adapter declares it unknown/large rather than inventing precision.

Third-party inference runs outside the control process. Pin code and weights by
immutable revision and hash, review any `trust_remote_code` implementation,
produce an SBOM, and run it without network access, credentials, writable model
cache, or device permissions beyond the declared inference surface. Resource
limits and a killable deadline make compromise, hang, OOM, or malformed output
equivalent to an unavailable proposer and therefore a deterministic HOLD. A
classical controller may continue only when an independently grounded goal is
still fresh and authorized and every state/transform/geometry gate remains
healthy; model failure never creates a new fallback motion goal.

Model roles remain distinct:

| Model | Appropriate role | Inappropriate role |
| --- | --- | --- |
| InternVLA-N1 System 2 / DualVLN | desktop instruction grounding and bounded goal/trajectory proposal | README badges declare CC BY-NC-SA 4.0 while machine-readable Hub metadata/artifact grants are absent; product use is blocked and isolated research needs explicit legal approval; camera, latency, and frozen-eval review still required |
| X-NavDP | RGB-D local trajectory/recovery challenger | language planning or unshielded command authority |
| CE-Nav | Go2/cross-embodiment local-policy challenger after artifact/dependency review | legacy Isaac environment, incomplete training release, or direct motor authority; repository MIT does not waive checkpoint/dependency/Isaac review |
| MiniCPM-RobotTrack | owner-follow waypoint shadow on Go2/Orin | owner identity, target-presence decision, or collision authority |
| CityWalker | urban traversability/short waypoint prior | open-vocabulary instruction or social reasoning |
| VLFM pattern | unseen-object frontier scoring | final path/control or free-space authority |
| VAMOS / OmniNav | research-only semantic path/affordance and exploration comparisons | product selection before code/model/data terms and Go2 role fit clear |
| NoMaD/ViNT | teach-repeat/topological route memory | semantic instruction understanding |
| NaVILA/StreamVLN/Uni-NaVid | research comparators | immediate production default |
| Qwen-RobotNav | architecture reference; official weights unavailable | installable candidate |
| ABotN-Bench | role-specific POI/point-goal evaluation | navigation policy or physical evidence |

## 7. Compute placement

Current desktop: RTX 5000 Ada 32 GB, 96-core Threadripper Pro, 246 GiB RAM.
Future target discussed in the repository: Orin NX 16 GB.

Desktop:

- conversation/planner service and one large navigation challenger;
- Grounding DINO/SAM/OCR and offline replay;
- MetaUrban/Isaac/Habitat research services;
- model profiling and quantization.

The InternVLA 8B variants expose roughly 16.6–16.8 GB of BF16 weight files;
20–24 GB is only a Parcel planning estimate once runtime allocations are added,
not an official peak-memory measurement. The configured Gemma q4 artifact is
14.4 GB on disk, while a prior observed CUDA process occupied 15,280 MiB at
idle; neither number is a peak full-stack memory measurement. Do not assume the
services can coexist with KV cache, vision encoders, simulator, and perception.
Benchmark process-level peak VRAM and full-load latency; use separate scheduling
or a second GPU/device if necessary.

Orin NX:

- geometry, TensorRT detector/segmenter/tracker, owner association, and safety
  first;
- MiniCPM-RobotTrack or CityWalker as bounded-rate candidates only after real
  profiling;
- drop open-vocabulary/semantic work before control or safety under thermal or
  memory pressure;
- no 7–8B BF16 model is assumed to fit alongside the product stack.

## Architectural tradeoff summary

| Choice | Advantage | Limitation |
| --- | --- | --- |
| Hierarchical proposals + deterministic authority | debuggable, composable, safe fallback, models can be swapped | more interfaces and integration work than one end-to-end policy |
| Unitree Sport locomotion | mature onboard balance/gait and faster physical progress | less low-level research freedom; vendor behavior/firmware must be commissioned |
| Nav2 sidecar, not rewrite | mature high-rate navigation without coupling voice stack to ROS | IPC/versioning/ROS image operational burden |
| Common planner for navigation and follow | walls/crowds handled consistently; one safety path | formation controller becomes more complex than direct proportional follow |
| Fast closed-set + slow open-vocabulary perception | predictable latency plus semantic breadth | model ensemble, calibration, memory, and license management |
| Deterministic common intents + slow model fallback | low latency and reliable frequent commands | grammar/skill catalog still needs deliberate product expansion |
| Semantic model proposes next skill/waypoint, not next motor tick | uses reasoning where it helps without destabilizing control | learned model cannot compensate for a fundamentally weak local controller |
| Separate conversation and planning | natural full-duplex conversation does not wait for physical planning | GPU contention and cross-lane task/reply synchronization must be managed |

The central rule is simple: learned intelligence decides **what might be useful
next**; grounded state, the executive, controller, and safety system decide
**what is valid now and whether it succeeded**.
