# Perceptive all-terrain navigation — proposed algorithms and interfaces

**Design date:** 2026-08-09  
**Scope:** simulated Unitree Go2 navigation/locomotion; simple existing command input;
no full-duplex audio work  
**Maturity:** proposal for independent audit, not implemented or validated

## 1. Design principles

1. **Separate meaning, route, body motion, and balance.** “Go upstairs” is a task;
   the landing is a goal region; a timed body corridor is a navigation result; foot
   placement and joint targets are locomotion. One model must not silently collapse
   these authorities.
2. **Use every sensor for the fact it measures best.** Camera supplies appearance and
   semantics; depth/3-D LiDAR supplies geometry and negative-obstacle evidence; IMU,
   odometry, joints, and contacts supply motion and stability. Redundant evidence is a
   reason to estimate uncertainty, not to pick one universal sensor.
3. **Unknown is not free.** Translational motion requires sufficient observed swept
   volume and terrain support. Bounded turn-to-observe is allowed only when rotation's
   body/leg envelope is itself observed and admitted.
4. **Capabilities are measured artifacts.** A planner cannot label a staircase safe
   merely because it sees stairs. The selected controller must have a versioned
   capability envelope whose validation distribution covers the requested geometry.
5. **Learning proposes or controls a bounded subsystem; safety remains independent.**
   Learned traversability, waypoints, and joint targets carry confidence, version,
   freshness, and an explicit fallback. A final raw-sensor/stability guard can stop.
6. **Truth has one-way flow.** Simulator truth may score an episode and privileged
   terrain/physics may train a teacher. Neither enters a deployable student's runtime
   observation, route, completion predicate, or safety decision.
7. **Evidence precedes optimization.** Freeze an untouched upstream baseline and a
   mutation-sensitive evaluator before tuning rewards, planners, or policies.
8. **Forward travel is preferred, not mandated.** Destination motion penalizes lateral
   velocity and large reverse segments, while allowing lateral steps for balance,
   recovery, close-clearance maneuvering, formation control, and terrain alignment.

Camera/depth and LiDAR are the only local external-environment authorities in the first
ODD. IMU, encoders, contacts and odometry are proprioceptive/state feedback. A future
Google/online-map placeholder may propose a coarse topological route, but never local
free space, terrain capability, collision safety, or arrival.

## 2. Component and authority graph

```text
                         non-real-time / event-driven
 text, simple voice, UI ──> intent compiler ──> TaskRequestV1
                                                  |
  camera ─┐                                       v
 depth ───┼─> ObservationJoinV1 ─> semantic/topological goal grounding
 3D lidar ┤          |                            |
 IMU ─────┤          v                            v
 odom ────┤   StateEstimateV1              GoalRegionSetV1
 joints ──┤          |                            |
 contacts ┘          v                            v
                TerrainMapV1 + VolumeMapV1 ─> capability route planner
                         |                        |
 dynamic tracks ────────┘                        v
                                            TerrainRouteV1
                                                  |
                                                  v
                                            local MPPI/lattice
                                                  |
                                           TimedBodyTrajectoryV1
                                                  |
                                        controller mode admission
                                         /                    \
                              Unitree Sport              learned Go2 policy
                              body velocity              joint targets + PD
                                         \                    /
                                          actuator shaping
                                                  |
 fresh point cloud/depth + state ───────> MotionAdmissionV1
                                                  |
                                          ControlManager / HAL

 simulator truth ────────────────────────────────> scorer/replay only
 privileged height/contact/physics ──────────────> teacher only
```

There is exactly one active locomotion writer. Switching between Sport and learned
joint control is a state machine with stop confirmation and lease transfer, never a
configuration toggle observed mid-command.

## 3. Proposed simulator-neutral contracts

The names are proposals; implementation should reuse existing Parcel primitives where
they already carry the same invariant. All timestamps use a monotonic clock and every
record carries its clock domain.

### 3.1 Sensor and state contracts

```python
@dataclass(frozen=True)
class SensorFrameV1:
    sensor_id: str
    sequence: int
    capture_time_ns: int
    receive_time_ns: int
    clock_domain: str
    frame_id: str
    calibration_epoch: str
    transform_epoch: str
    payload_ref: ArtifactRef       # image/cloud/scan; immutable
    coverage: SensorCoverageV1     # FOV, min/max range, blind regions
    quality: SensorQualityV1       # noise/covariance, dropout, saturation
    health: Health                 # OK | DEGRADED | STALE | FAILED
```

`ObservationJoinV1` contains a time-indexed SE(3) transform for every included frame,
maximum skew, interpolation/extrapolation flags, and required/optional sensor health.
It is rejected if calibration changed within the join or required geometry is stale.

```python
@dataclass(frozen=True)
class StateEstimateV1:
    time_ns: int
    map_T_base: SE3
    odom_T_base: SE3
    map_T_odom: SE3
    twist_base: Twist6
    covariance_15x15: tuple[float, ...]
    imu_bias: ImuBias
    localization_status: TrackingStatus
    transform_epoch: str
    valid_until_ns: int
```

The initial state-estimation bake-off compares GLIM against a simpler LiDAR-inertial
baseline using the same packets and simulated ground-truth scorer. `TruthPoseProvider`
remains evaluator-only after the adapter exists. Camera visual features may help
relocalization, but locomotion must remain stable through camera failure.

`RobotStateV1` adds base roll/pitch/yaw rate, joint position/velocity, commanded and
estimated torque, foot contact/force, motor/thermal proxy, active controller, last
accepted command, fall/recovery status, and freshness. The current Sport adapter's foot
force seam is preserved; joint telemetry must be populated before it is declared
available.

### 3.2 World representations

```python
@dataclass(frozen=True)
class TerrainCellV1:
    elevation_mean_m: float
    elevation_variance_m2: float
    observed_probability: float
    slope_rad: float
    cross_slope_rad: float
    roughness_m: float
    step_up_m: float
    step_down_m: float
    support_probability: float
    traversability_probability: float
    dynamic_probability: float
    semantic_distribution: Mapping[str, float]
    last_observed_ns: int
```

`TerrainMapV1` is a robot-centered 2.5-D grid with resolution, SE(3) origin,
uncertainty, and provenance per layer. It also exposes stair/ramp segments, not just a
single scalar traversability score. A traversability probability is never equivalent
to collision-free truth.

`VolumeMapV1` is a local 3-D occupancy/TSDF/ESDF product with observed/unknown state,
dynamic mask, free-space confidence, body-clearance query, and time-decay rules. It
catches overhangs, rails, tabletops, stair undersides, and body/sensor-mast clearance
that a single-height grid loses.

`DynamicTrackSetV1` carries class-agnostic obstacle tracks with timestamped position,
velocity, covariance, extent, age, existence probability, source coverage, and
prediction modes. Semantic “human” classification adds social costs, but geometry
alone is enough to avoid an unknown moving body.

### 3.3 Capability and command contracts

```python
@dataclass(frozen=True)
class LocomotionCapabilityV1:
    controller_id: str
    artifact_sha256: str | None
    validation_manifest_sha256: str
    allowed_modes: frozenset[str]
    max_slope_up_rad: float
    max_slope_down_rad: float
    max_cross_slope_rad: float
    max_step_up_m: float
    max_step_down_m: float
    min_tread_depth_m: float
    min_body_clearance_m: float
    max_gap_m: float
    speed_limits_by_terrain: Mapping[str, Limits]
    required_sensors: frozenset[str]
    confidence_floor: float
    valid_physics_domain: DomainDescriptor
    prohibited_conditions: tuple[str, ...]
```

The values are populated only from a frozen validation report. A paper number, training
terrain configuration, or vendor marketing claim must not populate this object.

`TerrainRouteV1` contains a corridor of SE(3) body poses, terrain segments, required
locomotion modes, direction preference, per-segment uncertainty, observed landing and
escape regions, capability version, and an expiry. It is invalidated by map epoch,
controller capability, or task revision changes.

`TimedBodyTrajectoryV1` is a short horizon of desired body pose/twist/acceleration and
clearance envelopes. It is suitable for both controller backends; it contains no joint
targets. A `LocomotionCommandV1` sent through the existing controller boundary carries
desired body twist/posture/gait hint, limits, lineage, valid-from, and expiry.

The learned backend privately maps that command and robot-centric perception/state to
joint targets. A future low-level process needs a distinct high-rate interface and
watchdog; it must not weaken `ControlManager`'s exclusive lease semantics.

```python
class MotionDisposition(Enum):
    ADMIT = "admit"
    SCALE = "scale"
    TRANSLATION_HOLD = "translation_hold"
    EXACT_HOLD = "exact_hold"
    ESTOP = "estop"
```

`MotionAdmissionV1` is computed **after the only actuator shaper**. It records raw
command, final command, reason codes, evidence sequences/timestamps, swept-volume/TTC,
stability margin, and validity. `EXACT_HOLD` reasserts exactly zero and resets relevant
shaper state. Translation-preserving yaw requires an independently validated rotational
swept envelope; otherwise the disposition is exact hold.

### 3.4 Scenario and result contracts

`TerrainScenarioV1` records simulator/backend/version, asset and generator family,
terrain parameters, physics, sensor corruption, dynamic actors, mission, start/goal,
seed, and ODD tags. `EvalResultV1` records code/config/model/container/source hashes,
hardware, all seeds, aggregate and per-episode metrics, failure taxonomy, replay
artifacts, and explicit `does_not_prove` statements. Results append to a ledger; they
are never edited in place.

## 4. Perception, localization, and mapping algorithm

### 4.1 Ingestion and synchronization

For every sensor packet:

1. validate schema, monotonic sequence, capture/receive timestamps, calibration and
   transform epochs;
2. reject replay, impossible range, NaN/Inf, corrupted dimensions, and excessive age;
3. deskew 3-D LiDAR using IMU/odometry across the scan when supported;
4. create a time-indexed transform at capture time, never at planning time;
5. join camera/depth/LiDAR only within configured skew; retain individual covariance;
6. mark observed coverage explicitly—including self-occlusion and rear/downward blind
   space—rather than filling missing cells as free; and
7. publish health/freshness independently of data content.

LiDAR/depth and IMU/odometry are required for terrain translation in the initial ODD;
RGB semantics are optional for geometric collision avoidance. Loss of RGB degrades
semantic tasks; loss of safe geometry holds translation. Loss of external perception
does not disable the low-level proprioceptive balance/recovery fallback.

### 4.2 State estimation

The first benchmark uses GLIM as the permissive, current LiDAR/range–inertial candidate,
with FAST-LIO2 only as a GPL research comparator. Score absolute/relative trajectory
error, velocity error, relocalization, covariance calibration, compute/latency, and
failure rate on:

- repeated corridors and symmetric stairs;
- sparse geometry and long featureless walls;
- dynamic people/vehicles;
- rapid pitch changes, vibration, and stair impacts;
- scan delay, timestamp skew, IMU bias, and extrinsic perturbation; and
- floor transitions and loop closures.

The output retains distinct `map`, `odom`, and `base` frames. Local control consumes a
smooth `odom` trajectory; global route/semantic memory consumes `map`; `map_T_odom` is
time-indexed and can jump only through an explicit replan barrier.

### 4.3 Elevation and volume fusion

For each transformed point/depth sample, update elevation mean/variance with sensor and
pose covariance. Ray visibility clears stale artifacts but never erases unobserved
negative space. Per-cell filters compute:

- normal and longitudinal/cross slope;
- multiscale roughness and discontinuity;
- maximum plausible height in unknown cells;
- step-up and step-down edges;
- support/foothold area and reachability proxy;
- age/observation confidence;
- semantic and dynamic layers; and
- traversability conditioned on the active capability envelope.

In parallel, integrate static observations into a local volume map and keep dynamic
observations out of the persistent surface. Query the 3-D swept body/leg/sensor envelope
along candidate trajectories. Elevation Mapping CuPy is the lead elevation candidate;
nvblox is the lead GPU volume-map complement. Their ROS-facing implementations are
wrapped behind Parcel contracts so the core planner does not depend on ROS messages.

### 4.4 Stair and hill extraction

Stair detection clusters repeated parallel elevation discontinuities and fits:

- stair axis and up/down direction;
- riser-height/tread-depth distributions and variance;
- stair width and side boundaries;
- approach region, flight extent, intermediate/top/bottom landings; and
- observed coverage/confidence for every required tread and landing.

The detector proposes a `TerrainSegment`; it does not declare it executable. A ramp
classifier fits connected planes and separates longitudinal slope, cross-slope,
roughness, convex crest, concave valley, and exit visibility. Ambiguous steps/ramps keep
multiple hypotheses or are treated as unknown.

Negative obstacles require positive free-space rays to a visible edge plus missing
support below/after it; a no-return alone is not evidence of a cliff because glass,
absorption, range, or dropout can produce it. The initial policy holds and changes
viewpoint when support confidence is insufficient.

## 5. Global and local navigation

### 5.1 Goal grounding

Keep the existing simple text/voice compiler. It produces a task such as
`NAVIGATE(goal_region=...)`, `FOLLOW(owner...)`, or `STOP`, not motor output. Task 4's
pixel-to-semantic work provides candidates and goal regions. Until it is admitted,
simulator semantic truth remains confined to evaluator/oracle tiers and claims stay
geometry-only.

The semantic layer proposes several acceptable regions—for example, sidewalk interior,
a safe annulus near a lamppost, a store entrance approach, or a follow formation. The
route planner erodes these by body clearance, road policy, terrain feasibility,
uncertainty, and active controller capability.

### 5.2 Capability-aware global routing

Construct a graph over traversable surface patches and topological connectors:

- nodes: locally planar/supportable regions, landings, rooms, sidewalks, entrances;
- edges: flat corridors, ramps, stairs, curbs, doors, elevators, crossings;
- attributes: elevation change, minimum clearance, slope, step/tread statistics,
  direction, observed confidence, dynamic risk, semantic policy, energy, and required
  capability/mode.

An edge is hard-rejected when required geometry is outside the selected controller's
capability envelope, sensor coverage is inadequate, or unknown support exceeds the
exploration allowance. Search cost is:

```text
J_edge = travel_time
       + w_energy * energy_proxy
       + w_risk * calibrated_failure_risk
       + w_unknown * unobserved_support
       + w_dynamic * predicted_actor_conflict
       + w_social * social_policy_cost
       + w_mode * controller_switch_cost
```

Risk terms cannot make a lethal edge merely expensive; hard capability and safety
constraints are evaluated first. Multi-floor route planning uses landing/connectivity
nodes, not a projection that lets floors overlap.

### 5.3 Terrain-aware local MPPI/lattice

Start with deterministic sampling-based local control because it is inspectable and
can consume the evolving map. At 10–20 Hz:

1. seed control sequences from the prior accepted solution and safe stop trajectory;
2. sample body-frame `(vx, vy, yaw_rate, posture/gait_hint)` sequences within the active
   capability and actuator delay model;
3. forward simulate a conservative body model over 2–4 seconds;
4. reject candidates with unobserved support, swept 3-D collision, drop-off, excessive
   slope/cross-slope/step, invalid mode transition, instability proxy, or dynamic TTC;
5. score feasible trajectories for route progress, clearance, terrain uncertainty,
   stability, tracking smoothness, energy, social distance, and terminal alignment;
6. penalize lateral/reverse destination travel but preserve it for explicit recovery,
   formation, and close-clearance modes;
7. validate the selected trajectory again at full resolution; and
8. emit only its first short body-command segment with expiry.

Nav2 MPPI is an algorithmic/flat baseline, not a stair controller. Implement the core
against Parcel's map/capability contracts or wrap it only where its planar assumptions
hold. Compare a geometric 2.5-D lattice/PRM baseline with SCAN-Planner in shadow after
its young codebase and license are audited. ArtPlanner supplies a useful 2.5-D design
reference, but ANYmal weights and unsupported follower are not production Go2 assets.

### 5.4 Stairs state machine

```text
DETECT
  -> APPROACH (flat controller, low speed)
  -> ALIGN (stair axis; body/landing/treads observed)
  -> CAPABILITY_CHECK
  -> COMMIT_FLIGHT (learned/vendor mode lease)
  -> TRAVERSE (slow replanning + contact/stability monitoring)
  -> VERIFY_LANDING (support + settled pose)
  -> EXIT (flat controller)
```

At every state, stale geometry, lost support, excessive pitch/roll/slip, unexpected body
contact, tracking error, controller deadline miss, or changed terrain hypothesis causes
`HOLD`, controlled retreat only if its swept region is observed and capability-backed,
or recovery. Stair descent has stricter entry: the first treads and bottom landing must
be observed from an aligned view; the policy does not descend into an occluded landing.
Controller switching requires exact hold, settled feedback, exclusive lease transfer,
and a fresh capability check.

### 5.5 Hill/ramp state machine

Prefer ascent/descent aligned with the gradient; penalize cross-slope. Select speed and
posture from slope, roughness, friction belief, exit visibility, and capability. Compare
IMU/odometry motion with foot/contact expectations to estimate slip. Increasing slip or
unexpected roll/pitch scales motion, then holds. At convex crests, reduce speed and
require downward support observations before crossing the visual/LiDAR horizon.

### 5.6 Dynamic obstacles

Predict multiple constant-velocity/turn modes with covariance over the local horizon.
The planner maintains human personal space and yields early; the final raw-geometry gate
does not require a correct human label. Occlusion boundaries add risk. Simulator actors
used as collision truth must be physics-enabled; purely visual/kinematic actors can test
perception and prediction but cannot support contact-dynamics claims.

## 6. Final safety and recovery

The safety path consumes newer, simpler evidence than the planner:

```text
selected command
  -> acceleration/jerk shaping
  -> raw depth/point-cloud swept-volume + TTC check
  -> terrain support/drop-off check
  -> state/contact/stability check
  -> freshness/clock/calibration/lineage check
  -> MotionAdmissionV1
  -> exact final HAL command
```

It uses configured stop/slow/TTC regions that expand with velocity, actuator delay,
stopping distance, body/leg sweep, and state uncertainty. Required source timeout,
replay, calibration change, transform failure, or policy deadline miss is a stop, not a
point-goal fallback. The layer is deliberately independent from learned traversability
and should be isolated from planner/GPU failure. It is a software risk reducer, not a
functional-safety certification.

Recovery is bounded and evidence-dependent:

- hold and re-observe;
- rotate only inside a validated rotational envelope;
- retreat only over recently observed support and rear clearance;
- switch to proprioceptive stand/recovery on exteroception loss;
- replan around a blocked edge or choose a different goal region;
- declare `UNSUPPORTED_TERRAIN`, `SENSOR_UNAVAILABLE`, or `NO_SAFE_ROUTE` honestly.

No recovery may erase task revision, change arrival authority, or bypass a final hold.

## 7. Locomotion learning program

### 7.1 Baseline first

Pin Isaac Lab, Unitree RL Lab, Unitree model assets, RSL-RL, simulator container, and
source commits. Reproduce the official Go2 rough-velocity environment without Parcel
reward changes. Record training curves, checkpoint, scripted evaluation, seeds, GPU,
driver, container digest, config hash, and simulator version. Verify whether the exact
Go2 deployment/export path is implemented; Unitree's public README is more explicit for
G1, so this is a gate rather than an assumption.

Unitree Sport remains the production-shaped flat/mild-terrain baseline. Unitree MuJoCo
is low-level and does not emulate the onboard Sport controller, so Sport capability
must not be inferred from that simulator.

### 7.2 Teacher and student

Train a privileged teacher with:

- true local terrain heights/normals, contact and base velocity;
- randomized mass/CoM/inertia, friction, motor strength, latency, disturbances;
- desired body velocity/heading/posture and terrain mode; and
- exact curriculum difficulty and physics parameters.

Teacher output is joint position targets (or residuals) at approximately 50 Hz, tracked
by PD at 200–500 Hz. Physics runs at 500–1000 Hz. These are initial research rates and
must be profiled against the final model/controller, not copied blindly.

Distill to a recurrent student that observes only:

- noisy/delayed robot-centric elevation or point-cloud features derived from the same
  camera/LiDAR packets intended for deployment;
- IMU, joint positions/velocities, contacts/foot force where commissioned;
- command and action histories; and
- explicit sensor-validity masks/age.

Train short exteroception outages so the recurrent belief and proprioceptive fallback
remain stable. Do not reward blindly continuing through missing geometry; navigation
still holds translation when it lacks route evidence.

### 7.3 Curriculum

1. stand, recover, and low-speed command tracking on flat ground;
2. small roughness, randomized friction, impulses, payload and actuator delay;
3. longitudinal slopes, cross-slopes, ramps and curbs;
4. regular stair ascent at varied approach yaw;
5. regular stair descent with visible landings;
6. irregular/open stairs, narrow/turning landings, rubble and stepping surfaces;
7. gaps/drop-offs and false/noisy exteroception;
8. static obstacle route tracking across mixed terrain;
9. moving obstacles and owner/bystander separation; and
10. long indoor-to-city composite routes plus cross-engine held-out evaluation.

Difficulty increases only after the lower confidence bound on success and hard-safety
metrics passes. Failure-heavy cases stay in validation/OOD sets when they are not in the
declared ODD; the curriculum does not silently redefine “supported.”

### 7.4 Reward/constraints

Positive terms: command/path progress, upright stability, intended foot clearance,
stable/non-slip support, smooth action, energy efficiency, recovery, and desired body
height/orientation. Negative terms: forbidden body contact, falls, cliff entry, slip,
joint-limit use, torque/thermal proxy, action rate/jerk, tracking error, unnecessary
lateral/reverse movement, and timeouts.

Hard termination and evaluator failures cover human contact, fall, trunk/hip/sensor
impact, unsupported drop-off, invalid command, and numerical/controller failure. Normal
foot–terrain contact is expected and labeled separately.

### 7.5 Domain randomization

Version physically plausible distributions for:

- base/limb mass, payload/placement, CoM and valid inertia;
- motor strength, joint stiffness/damping/friction, backlash/dead zone, torque/voltage;
- ground static/dynamic friction, restitution/compliance, foot geometry;
- action/sensor/communication delay, jitter, packet loss and clock skew;
- camera intrinsics/extrinsics, exposure, blur, distortion, compression, lighting and
  texture/material/weather distractors;
- LiDAR beam pattern/extrinsics, range/angle error, incidence/range dropout, motion
  distortion, reflective-material failure;
- IMU bias/random walk, encoder noise/offset, calibration changes; and
- pushes, foot trapping, movable clutter and pedestrian policies.

Maintain three distributions: training, frozen in-domain release, and frozen OOD
stress. Hold out generator/mesh/asset families and an entire physics engine. A different
random seed from the same staircase generator is not a convincing generalization test.

## 8. Simulator portfolio

No simulator is authoritative for every layer:

| environment | role | not evidence for |
|---|---|---|
| Isaac Lab / Isaac Sim | primary vectorized articulated Go2 terrain training; contact/sensor curricula; RTX release slices | physical safety or real sensor recognition |
| current Parcel MuJoCo city | fast deterministic command, semantic, planner, dynamic-cost, safety and UI regression | gait, foot contact, stairs, falls, sim-to-real |
| articulated Unitree MuJoCo | independent low-level sim-to-sim, SDK2 schema, terrain regression | onboard Sport-controller behavior; photoreal perception |
| Gazebo Harmonic | later ROS 2 timing/TF/QoS/sensor-noise/HIL integration | high-throughput RL; kinematic visual actors as collision truth |
| MetaUrban | procedural sidewalks/city assets, people/traffic, social and semantic stress | authoritative Go2 foot-contact dynamics |
| URBAN-SIM | promising Isaac/Go2 urban challenger | features/checkpoints still marked TODO in public repo |
| Habitat/iGibson/OmniGibson | frozen indoor semantic/VLN/ObjectNav distributions | legged stair-contact qualification |

Use one `EmbodiedSimBackend` adapter for clock, reset/step, sensor packets, actuator
commands, evaluator truth, and deterministic scenario seed. Policy code cannot import a
specific simulator. Truth and privileged teacher channels use types unavailable to the
deployable runtime build.

## 9. Evaluation design

### 9.1 Scenario families

- flat indoor: doors, corridors, furniture, glass/mirrors, low overhangs;
- stairs: up/down, varied riser/tread/width/yaw, open risers, turning flights, narrow or
  occluded landings, low light;
- sidewalk/curb: curb up/down/oblique, curb ramps, gutters, parked-car occlusion;
- hills: longitudinal/cross-slope, crest/valley, switchback, mixed/slippery traction;
- rough: heightfields, rocks/rubble, stepping surfaces, shallow gaps/drop-offs;
- static clutter: BARN-like passages plus height-dependent obstacles;
- dynamics: crossing/overtaking/oncoming people, groups, bottlenecks, occlusion;
- faults: frame delay/drop/replay, extrinsic changes, drift/relocalization, inference
  timeout/NaN, degraded lighting/range; and
- composite: room → corridor → stairs → sidewalk → hill → semantic goal.

### 9.2 Metrics

**Hard safety:** human contacts, forbidden body/sensor contacts, falls, drop-off entries,
minimum clearance/TTC, slip, joint/torque/thermal-proxy violations, exact-hold response,
and safety-shield activations.

**Task:** success, SPL/SoftSPL, goal-region error, route completion/time, elevation gain,
stairs up/down/curb/hill success separately, recovery/intervention, semantic-region
correctness, and social personal-space compliance.

**Motion:** body velocity/yaw tracking, path curvature, heading alignment, unnecessary
lateral/reverse distance, acceleration/jerk, roll/pitch distribution, stance/support
margin, energy/cost-of-transport proxy, and peak power.

**Perception/system:** pose ATE/RPE, elevation error/uncertainty calibration,
traversability precision/recall, drop-off/overhang detection, dynamic-track ADE/FDE,
sensor-to-map/map-to-plan/sensor-to-command p50/p95/p99, deadline misses, stale-frame
holds, real-time factor, GPU memory/power, and replan/stuck time.

### 9.3 Initial promotion gates

Thresholds are proposals to ratify after an untouched baseline; they are not achieved
results.

- **PR / deterministic MuJoCo:** 20–50 episodes for affected components, no invalid
  command/truth leak/NaN, zero falls or forbidden contacts in the small suite, RTF > 1.
- **Nightly / Isaac:** at least 250 episodes per affected family; lower 95% confidence
  bound on in-domain success >= 95%; zero observed human contacts/falls; p99 deadline
  within budget; no >2 percentage-point admitted-checkpoint regression.
- **Weekly OOD:** >=1,000 held-out episodes across geometry, assets, physics and sensor
  faults; proposed OOD success >=90%; each stair-up/down, curb-up/down and cross-slope
  slice passes independently; every contact gets replay triage.
- **Cross-simulator release:** frozen policy with no target-simulator tuning; success in
  Unitree MuJoCo/Gazebo no more than 10 points below Isaac; identical schemas/timeouts;
  no new safety-failure class.

Zero failures never demonstrates zero failure probability. For independent trials, zero
failures in 1,000 still leaves an approximate 95% upper failure-probability bound near
0.3%. Report exposure and confidence intervals, not “collision-free” as an absolute.

### 9.4 Evaluator integrity

Before hill-climbing, mutation tests must fail when they:

- leak simulator pose/height/semantics to the student;
- suppress a collision, fall, or forbidden body contact;
- count normal foot contact as a collision—or ignore body collision as normal contact;
- turn unknown/drop-off cells into free space;
- replay/stale a sensor while preserving an OK flag;
- bypass the post-shaper exact hold;
- let a planner request terrain beyond the active capability;
- swap controller writers without stop/lease transfer;
- accept kinematic base translation as stair completion; or
- mark proximity as semantic/task completion without the existing arrival authority.

All comparisons use paired scenario manifests/seeds, per-episode outputs, Wilson or
bootstrap confidence intervals, and immutable provenance. Tune on training/validation,
never on frozen OOD or cross-simulator release sets.

## 10. Latency and scheduling

Initial target cadences:

| layer | target rate | scheduling rule |
|---|---:|---|
| physics | 500–1000 Hz | simulator-specific, deterministic step |
| joint PD / low-level watchdog | 200–500 Hz | isolated real-time-oriented process/thread |
| learned locomotion inference | ~50 Hz | bounded deadline, previous-safe/stand fallback |
| stability/raw-geometry safety | 50–100 Hz | independent of semantic/VLM/GPU planner failure |
| state estimator | 50–200 Hz | timestamp-driven |
| elevation/volume maps | 10–30 Hz | asynchronous, newest complete epoch |
| local terrain planner | 10–20 Hz initially | warm-started; hard deadline and safe stop seed |
| global route planner | 0.5–5 Hz/event | replan on invalidation or blockage |
| semantic/VLM proposal | 0.5–2 Hz/event | async, TTL proposal only |
| voice/text | event driven | outside hard motion loops |

Instrument capture-to-state, state-to-map, map-to-plan, plan-to-final-command, policy
inference, queue time, jitter, stale drops, deadline misses, and simulator RTF. Run heavy
semantic perception asynchronously from safety and locomotion; resource contention on
the single GPU is itself a release scenario.

## 11. Compute and environment plan

Audited host: Ubuntu 26.04, Linux 7.0, NVIDIA RTX 5000 Ada (32,760 MiB, compute 8.9),
driver 595.84, 96-core Threadripper PRO 7995WX, approximately 246 GiB RAM and 2.9 TB
free disk; system Python is 3.14.4. `nvcc`, Isaac Lab, and `uv` were not found.

This is sufficient for single-GPU vectorized Go2 training and GPU mapping experiments,
but the host versions are outside several upstream tested matrices. Use a pinned
Ubuntu 24.04/ROS 2 Jazzy container or an upstream-supported isolated Isaac environment,
mount artifacts/results explicitly, and record image digests. Do not install into or
replace system Python. Start with physics-only batches, then budget smaller RTX sensor
batches. Multi-GPU claims do not apply to this one-GPU workstation.

## 12. Implementation ownership and dependency graph

```text
P0 contracts/truth isolation ───────┬─> perception/state ─> maps ─┐
                                    ├─> eval kernel/scenarios ────┼─> integrated R3+
                                    └─> isolated Isaac bootstrap ─┤
                                                                   |
upstream Go2 baseline ─> teacher ─> student ─> cross-sim ─────────┘

current planar regressions ───────────────────────────────> every PR gate
Task 4 semantic camera work ──────────────────────────────> semantic composites
```

Freeze the P0 schemas and truth boundary first. Perception, evaluation, and upstream
locomotion reproduction then parallelize. Terrain routing waits for a minimally trusted
map and capability contract; student promotion waits for the evaluator and untouched
teacher baseline. Dynamic-city work need not block first stairs/hills physics, and
voice/audio work is not a dependency.

## 13. Stop conditions and honest outcomes

The system should stop or decline when:

- terrain lies outside the active controller's validation envelope;
- required landing/support/clearance is unobserved or too uncertain;
- required sensor/transform/state data is missing, stale, skewed, replayed, or unhealthy;
- state estimation covariance or map discontinuity exceeds threshold;
- collision/drop-off/TTC or stability guard cannot admit motion;
- controller inference/feedback misses its deadline or becomes invalid;
- no route remains after hard constraints; or
- current simulator cannot physically model the claimed behavior.

Valid product responses include “I cannot safely use these stairs,” holding position,
re-observing, choosing a ramp, or asking for help. Persisting toward a goal is not more
important than preserving authority and evidence.
