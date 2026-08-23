# Parcel companion robot — engineering executive summary

**A ten-page bridge from senior software engineering to robotics: physics,
architecture, current-code truth, quality, hardware readiness, and next gates**

| Document control | Value |
| --- | --- |
| Status | Current-code engineering explanation and executive decision brief |
| Audit date | Base audit 2026-08-22; implementation delta 2026-08-23 |
| Last audited software baseline | `939001ea1038c8861773dca0da629d5ab441aea5`; Wave 2 Batches A and B are committed through the reliability/coverage landing. This documentation delta does not promote the active Wave-3 implementation. |
| Worktree scope | Active Wave 3 hardware-transition work: Python/Jetson portability, Mid-360 ingestion, XVF3800 audio, stopping-envelope evidence and box-day preparation, followed by started but unevidenced Go2 backend/profile/firewall work and defined aarch64/microphone-arm cards. In-flight mechanisms are never counted as released or commissioned. |
| Audience | Senior software engineers learning robotics, engineering/product leaders, robotics and safety reviewers, and procurement owners |
| Brief length | Approximately 7,000 words, or about 11–14 dense technical pages depending on rendering, tables, and code blocks |
| Canonical detail | [Parcel companion robot engineering handbook](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md) |

This ten-page brief assumes software, distributed-systems, testing and ML experience,
but no robotics background. It answers six questions:

1. What robot has actually been built in code?
2. How good is the current engineering and evidence?
3. What prevents this from becoming a semiautonomous Unitree companion dog?
4. When is hardware procurement justified?
5. What sequence converts the research stack into a bounded physical product?
6. Which robotics and physics concepts explain those decisions?

The answer in one sentence is:

> Parcel is a credible, safety-conscious simulator autonomy stack with strong
> semantic/task boundaries and a clean committed Batch-B gate. It has now entered a
> physical-substrate-first implementation phase, but it is not a physical companion
> product because the Go2 observation path, localization/SLAM, owner identity,
> native command isolation, measured stopping and body commissioning are not closed.

### How to read every capability claim

Robotics projects become misleading when four different states are collapsed into
the word *done*. This document uses the following vocabulary throughout:

| State | Meaning | Example in Parcel |
| --- | --- | --- |
| **Implemented** | Code and usually isolated tests exist. | RealSense backends and an owner-appearance tracker are committed, but their existence does not wire them into physical runtime composition. |
| **Wired** | A normal composition root constructs it and its output reaches the intended consumer. | The simulator observation reaches navigation and the safety chain. |
| **Verified** | A declared scenario passes with reproducible metrics and provenance. | Frozen simulator safety panels and many narrow P1/P2 fixtures pass. |
| **Commissioned** | Parameters, frames, timing, faults and operator procedures are measured on the intended physical body. | No autonomous Parcel perception-to-motion path is commissioned on a Go2. |

An implementation can be excellent and still have zero product effect. A wired
feature can run and still be wrong. A simulator-verified feature can fail on carpet,
under clock skew or with a real camera. Commissioning is the engineering activity
that converts assumptions into measured properties of one hardware configuration.

### 2026-08-23 implementation delta and direction

This dated section supersedes earlier progress, release-integrity and procurement
statements where they conflict; the underlying architecture and robotics analysis
remain unchanged.

The last audited software baseline is `939001e`. Its accepted eight-worker commit gate
passed all ten hard stages, collected 9,512 tests and reported 9,403 passed, 17
skipped and one expected failure in the parallel default suite, followed by the
serial rows. That closes the earlier tracked-source aggregate failure at the
declared local gate shape. Hosted/branch-protection evidence, a documented
load-sensitive WebSocket flake and target-device execution remain separate open
claims.

Wave 3 is deliberately changing the center of gravity from simulator capability to
physical substrate. Its current uncommitted status is:

| Card | Current verdict | What changed | What is still not proved |
| --- | --- | --- | --- |
| HW-1 Python/Jetson portability | Final **ACCEPT-WITH-NOTES** | Source imports across the Python 3.10 floor; CPython 3.12 product-venv direction and 3.10 vendor-venv split; aarch64 locks | Execution on the Orin and the Jetson ORT-GPU supply path |
| HW-3 Mid-360 band | Final **ACCEPT-WITH-NOTES** | Pure-Python synthesized-packet ingestion emits no scan for empty/under-populated input; seam tests show downstream HOLD when propagated | A `Go2Backend` that propagates it, plus real packets, transport, extrinsics, clock mapping and physical authority |
| HW-4 XVF3800 audio | **HOLD; correction active** | Verification established that the array streams when silent playback clocks capture | A green correction, product arm route, through-air AEC/false-barge-in and on-dog audio |
| HW-6 stopping envelope | Final **ACCEPT-WITH-NOTES** | Executable, provenance-bearing stopping-envelope calculation and gate | Measure gateway period, command-to-standstill and localization jump; HW-2 must first add scan age as a sixth term, then measure it |
| HW-8 box-day preparation | Closed **ACCEPT-WITH-NOTES** | EDU Plus Stage-0 run sheet, unknowns register and support-ticket draft | Owner sign-off, sent ticket, delivered hardware and execution of the runbook |
| Wave-3b physical substrate | **ACTIVE; UNVERIFIED** | Go2 backend/profile/firewall design and implementation have started; aarch64 and microphone-arm cards are defined | Executor status, independent verification, integrated gate and target-device evidence |

ROAM-2 is an equally important negative result: its coverage objective engages and
stays collision-free in the retained static runs, but the current metric saturates
before motion and the policy homes/circles instead of exploring. It therefore stays
off by default and is not frontier exploration or SLAM.

The next implementation chain is intentionally concrete:

1. close and reverify the physical-array HOLD;
2. add an observe-only `Go2Backend` with typed physical scan authority;
3. add one capability-admitting EDU Plus profile with measured, versioned
   extrinsics and no simulator truth;
4. prove the deployment shape on aarch64, check in the Orin firewall and expose the
   authenticated microphone-arm route;
5. execute read-only box-day capture before modifying the body;
6. commission LIO/SLAM, the native sole-writer gateway, independent stop and the
   measured stopping envelope; and
7. progress through stationary, stand-mounted and tethered minimum-speed trials
   before semantic navigation, following or roaming receives physical authority.

This is the right direction, but it does not promote overall maturity: normal
composition is still MuJoCo-first, no Go2 is on hand, Wave-3 implementation remains
outside the last audited software baseline, and no integrated Wave-3 gate or physical
motion result exists.

## 1. Executive decision

### 1.1 Product judgment

Parcel should be funded and managed as a **simulation-first supervisory-autonomy
platform entering physical integration**, not as a field-ready companion robot.
The integrated product is approximately **L2** on the maturity ladder used here:

| Level | Meaning |
| --- | --- |
| L0 | Absent or research proposal only |
| L1 | Implemented in isolation or unit-test-only |
| L2 | Composed through a normal simulator/development path |
| L3 | Repeated deterministic simulation/replay evidence for the stated scope |
| L4 | Supervised bench/tethered evidence on intended hardware |
| L5 | Repeated integrated evidence in a declared operating design domain (ODD) |

Several deterministic subsystems reach L3 in simulation. The integrated physical
robot remains L0–L1 because no normal runtime consumes a synchronized physical
observation and no autonomy path has commissioned Go2 motion, localization,
perception, stopping, identity, or through-air voice.

The strongest product assets are worth preserving:

- models propose bounded tasks; deterministic compilation/admission owns effects;
- revisions reject late work and semantic arrival requires fresh terminal evidence;
- motion crosses priority, TTL, input-health, collision/person/TTC, shaping,
  exact-stop, watchdog and stationary-witness layers;
- learned components are proposal/shadow/subtractive-veto sources, and tests include
  negative, frozen, provenance and seeded-defect evidence.

The immediate problem is not a shortage of AI models. Batch B closes the declared
local tracked-source gate, and Wave 3 has an explicit interpreter split in flight,
but the target deployment and physical evidence chain remain incomplete. More
semantic features should not be used to defer the following foundations:

1. hosted clean-checkout evidence plus honest Python/import capabilities;
2. a synchronized physical observation and `map → odom → base_link` SLAM spine;
3. a native sole-writer Unitree gateway plus independent stop;
4. calibrated perception/owner identity and repeated first-ODD evidence.

### 1.2 Procurement judgment

The project record now identifies an ordered **Go2 EDU Plus with Orin NX and a
Mid-360**. That is the correct way to treat the purchase: supervised R&D and
commissioning equipment, not a mount-and-run autonomous product. The body, D455 and
independent stop are not yet on hand; the only relevant physical device currently
available to this checkout is the reSpeaker XVF3800 microphone array. Delivery
therefore begins an evidence campaign rather than raising the software's maturity.

| Question | Decision |
| --- | --- |
| Buy for autonomous companion deployment? | **No.** Physical autonomy prerequisites are absent or uncommissioned. |
| Buy D455 for engineering now? | **Yes.** It unlocks physical camera, metric-depth and owner-tracking measurements; the RGB-only UVC path cannot satisfy the current depth contract. |
| Buy Go2 EDU as an engineering platform today? | **Already ordered as an EDU Plus R&D platform.** Receipt does not authorize autonomous motion; acceptance, independent-stop and lab-safety gates still govern use. |
| How must the purchase be classified? | Supervised R&D/data-collection/commissioning platform, not an autonomous product. |
| What should be purchased with the body? | Independent stop decision/remote, tether or leash, controlled-area equipment, dedicated network and the agreed sensor/compute mounts. |
| What should happen before delivery? | Owner reviews/signs the box-day plan, sends the open Unitree questions, names operator/reviewer, and prepares the independent stop, controlled area, network and capture/privacy procedures. |
| What should happen in the return window? | Inventory and photograph first; capture read-only firmware/network/sensor identity; verify compatibility, battery and payload interfaces; then calibrate axes/frames and permit only separately approved minimum-speed motion. |

Procure when the team can learn from the body every week; an idle robot does not
reduce the critical uncertainty.

## 2. Product objective and first operating domain

The north-star product is a conversational quadruped companion that can follow its
owner, navigate to semantically described places, accept corrections, recover from
ordinary ambiguity or blockage, interact naturally, and report completion only when
fresh evidence verifies the requested outcome.

A representative target mission is:

> “Walk with me, and after the red bench wait near the entrance.” The robot should
> discuss an unrelated topic while moving, clarify which entrance is meant, avoid
> crowding people, accept “use the other entrance,” reacquire the correct owner
> after occlusion, and say it arrived only after pose, target, relation and settled
> motion evidence agree.

That mission combines six systems that are often evaluated separately:

- conversation and turn commitment;
- task interpretation, authorization, revision and recovery;
- semantic perception and memory;
- localization, mapping and navigation;
- owner identity, prediction and social behavior;
- physical control, stopping and terminal truth.

The recommended first ODD is intentionally narrow: supervised private indoor routes,
flat/dry surfaces, adequate lighting, low walking speed, a mapped/calibrated area,
trained operator, independent stop and controlled participants. Road crossing,
stairs, elevators, public crowds, adverse weather and unsupervised operation remain
out of scope until separately evidenced.

ODD restriction bounds sensing, stopping, maps, people density, recovery and release
evidence. Supervised indoor results do not extrapolate to public outdoor operation.

## 3. Robotics and physics primer, mapped to Parcel

### 3.1 A robot is a feedback system in a changing physical world

A conventional service receives a request, computes a result and can often retry.
A mobile robot repeatedly estimates the world, chooses an action, changes the world
and then observes the consequences. Its essential loop is

```text
physical world -> sensors -> state estimate -> plan -> control -> actuators
      ^                                                         |
      +------------------- body motion -------------------------+
```

At 10 Hz, each iteration has 100 ms before the next nominal tick. Camera inference,
IPC, planning, Python scheduling and command transport consume parts of that budget.
Unlike an HTTP timeout, a late velocity command can continue moving mass toward a
person. The system therefore needs timestamps, bounded queues, command expiry,
freshness checks and a stop owner that does not depend on a successful high-level
loop. Parcel understands much of this at the software level: commands have TTLs,
the arbiter chooses among behaviors, `ControlManager` watches state and the final
safety path can replace a candidate with zero. The missing physical observation and
native gateway mean the loop is not yet closed around real hardware.

For a software engineer, this resembles a distributed transaction whose writes have
momentum and nonzero rollback distance. Safety is a monotone authority chain:
downstream stages may reduce speed or stop, but semantic, learned or stale
information must never restore removed authority.

### 3.2 Coordinate frames: SE(2), SE(3), and why labels on numbers matter

A pose is not just `(x, y, yaw)`; it is a transform between coordinate frames. A
ground robot is often planned in the planar rigid-motion group **SE(2)**. A pose
`T^a_b = (x, y, theta)` means “the pose of frame `b`, expressed in frame `a`.” It
acts on a point by rotation and translation:

```text
[p_x^a]   [cos theta  -sin theta] [p_x^b]   [x]
[p_y^a] = [sin theta   cos theta] [p_y^b] + [y]
```

Transforms compose in order: `T^map_camera = T^map_base * T^base_camera`. **SE(3)**
adds full 3-D rotation and translation, usually represented by a homogeneous matrix
or translation plus quaternion. Camera-to-floor geometry needs SE(3), even when
navigation later projects the result into SE(2).

The standard mobile-robot frame chain separates roles:

```text
map --(global correction, may jump)--> odom --(smooth, drifts)--> base_link
                                                               -> camera / lidar / imu
```

`odom -> base_link` should be continuous for control. `map -> odom` absorbs loop-
closure or relocalization corrections, allowing a building-frame goal to remain
meaningful without injecting a discontinuity into the controller. Parcel's
`pose.py` correctly defines MAP and ODOM, `PoseEstimate`, covariance and health.
`TruthPoseProvider` intentionally returns identical zero-uncertainty simulator
truth in both frames; `DriftingOdomProvider` exposes drift in tests. What is absent
is a production transform provider and a synchronized physical `base_link` sensor
tree. Simulator truth therefore hides the hardest frame problem.

### 3.3 Kinematics: how commanded velocity becomes motion

Kinematics describes motion without asking what forces caused it. Parcel commands a
body twist `(v_x, v_y, omega_z)`: forward speed, lateral speed and yaw rate in the
robot body frame. For a planar body pose `(x, y, theta)`, the ideal integration is

```text
x_dot     = cos(theta) v_x - sin(theta) v_y
y_dot     = sin(theta) v_x + cos(theta) v_y
theta_dot = omega_z
```

Treating a map-frame “move east” vector as body-frame forward turns the error with
the robot. A differential-drive base is nonholonomic and cannot command arbitrary
`v_y`; a Sport-controlled quadruped can usually strafe only within gait limits.
`ControlManager` therefore checks body- and lateral-velocity capabilities.

Kinematics also covers the robot footprint and sensor extrinsics. A point robot can
fit through any positive-width gap; a Go2-sized body cannot. Planning therefore
inflates obstacles by footprint plus clearance, transforming “move a disc through
raw geometry” into “move a point through a configuration-space obstacle map.” The
committed prototype exposes a real coupling defect here: a conservative obstacle stop
number can make an ordinary 0.8–0.9 m doorway mathematically impassable, while the
planner and final gate do not yet derive their entire envelope from one commissioned
source.

### 3.4 Dynamics: force, inertia, friction, and why simulation distance is not proof

Dynamics connects motion to force. In translation, `F = m a`; in rotation,
`tau = I alpha`. Motor limits, body mass, payload, leg configuration and ground
contact bound achievable acceleration. Friction limits horizontal contact force:
approximately `|F_tangent| <= mu F_normal`. If commanded deceleration exceeds that
friction cone, feet slip and the assumed stop distance is wrong. Carpet, tile,
incline, wetness, battery voltage and carried payload all change the physical
response.

Leg contact changes each gait phase. Static stability keeps the center-of-mass
projection inside a support polygon; dynamic trotting instead manages momentum and
recoverability as that polygon changes. Parcel sensibly delegates high-rate joint,
contact and balance control to Unitree Sport while requesting bounded body twists.

Current MuJoCo evidence is primarily evidence for autonomy logic and interaction
geometry. A socket backend advancing a base in a scene does not establish actuator
bandwidth, foot slip, recovery from a shove, or real braking. Those require system
identification on the intended body: command steps, measured velocity response,
latency, overshoot, stop distance and repeated surface/payload/battery arms.

### 3.5 Sensors: every measurement is a projection with failure modes

An RGB camera measures irradiance projected through a lens. Under a pinhole model,
a 3-D camera-frame point `(X, Y, Z)` maps to pixel `(u, v)` using
`u = f_x X/Z + c_x`, `v = f_y Y/Z + c_y`. Reversing that projection requires
depth: `X = (u-c_x)Z/f_x`, `Y = (v-c_y)Z/f_y`. Therefore a detector bounding box is
not a metric obstacle or goal by itself. It needs calibrated intrinsics, depth or
multi-view geometry, camera-to-body extrinsics, timestamps and a robot pose at the
measurement time. UVC RGB can support appearance and language tasks, but cannot
silently manufacture the metric depth required by safety or navigation.

Depth cameras fail on reflective/distant surfaces and have range-dependent error.
LiDAR misses are ambiguous without a device contract. An IMU measures angular rate
and specific force, not world velocity; bias makes integrated pose drift. Contact
odometry also drifts when feet slip.

Parcel has good schema instincts: origin, frame, freshness and payload validity are
treated as evidence properties, and camera ingress can carry calibrated metadata.
Committed Wave P1/P2 adds UVC, D455 and recorded backends plus a detector process seam.
However, `_attach_configured_camera_ingress` still constructs MuJoCo/EGL
unconditionally. Thus physical backends are implemented but not runtime-wired, and
the normal `SimObservation` still carries truth pose, truth-like owner tracks and
simulator scans.

### 3.6 Uncertainty and Bayes: a belief is not a boolean

Sensors and motion models are noisy, so a robot maintains a belief over state. Bayes'
rule combines prior belief and measurement likelihood:

```text
p(x | z) ∝ p(z | x) p(x)
```

Sequential estimation alternates a **prediction** from motion and an **update** from
measurement. In a Kalman-style estimator, the mean is the best estimate and the
covariance `P` describes uncertainty and correlation. A measurement with covariance
`R` should move the estimate less when it is noisy. The innovation `z - h(x)` and
its covariance answer whether the observation is statistically consistent; a
Mahalanobis gate is a scale-aware distance test, not an arbitrary Euclidean radius.

Parcel uses these ideas locally. `PoseEstimate` validates a 3×3 covariance over
`(x, y, yaw)`. Camera-grounded objects carry planar covariance; the metric localizer
uses Joseph-form covariance updates; lock-on/arrival logic can require fresh views,
covariance shrink and consistency. A zero covariance deliberately reduces chance-
constrained geometry to the old Boolean simulator behavior.

The same discipline applies to people. “Owner” is a hypothesis from enrolled
appearance, voice, continuity and perhaps UWB—not a label or raw cosine. Simulation
emits confidence 1.0, while one hard experimental clip scored a stranger near 0.917.
Physical state needs confirmed/tracking/ambiguous/lost, margin and age; ambiguity
means HOLD or search.

### 3.7 Estimation and SLAM: locating the robot while building the map

Odometry estimates relative motion and is locally smooth but accumulates error.
Localization estimates pose in an existing map. SLAM estimates trajectory and map
together. A typical factor graph represents poses as nodes and odometry, IMU, visual
features, scan matches and loop closures as probabilistic constraints. Optimization
finds the trajectory most consistent with those constraints. A loop closure can
remove accumulated global drift, which is why MAP may jump while ODOM must not.

SLAM is not equivalent to an occupancy grid. An occupancy grid answers where space
appears free or occupied; SLAM also answers where the robot was when measurements
were taken. Nor is Parcel's `OnlineMap` SLAM: it stores semantic object/place
evidence and names, useful for “the couch I saw yesterday,” but it does not estimate
free space, body trajectory or `T_map_odom`.

Parcel's seam is well chosen: consumers request typed frame, health and covariance
from one `PoseProvider`. Integrate proven ROS 2 drivers, `tf`, bags and SLAM, while
Parcel owns admission. Compare candidates on identical bags using trajectory error,
drift, lost/false-relocalization rates, recovery, covariance consistency and latency.
LOST transform health must block MAP goals and semantic arrival.

### 3.8 Mapping and planning: geometry, semantics, and time

An occupancy cell represents a belief that an area is occupied. Log-odds updates are
convenient because independent evidence adds: `L_t = L_(t-1) + inverse_sensor_model`
(with prior correction and clamping in a real implementation). Ray tracing marks
space before a hit free and the endpoint occupied. Inflation then accounts for body
radius and desired clearance.

Parcel's rolling 161×161 grid at 0.1 m resolution covers about 16.1 m square. A*
search minimizes accumulated cost plus a heuristic; eight-connected motion permits
diagonals. Comfort and dynamic-agent costs bias the path, while a tracker converts a
path into velocity. This is a sensible interpretable local baseline. Its tradeoff is
myopia: a robot-centered rolling grid cannot by itself remember a building or
relocalize after restart. Unknown-space penalties trade exploration against caution,
and a grid-invalid scan currently permits a weaker fallback in some paths.

Planning is layered by timescale: mission intent, global route, local response and
final command admission. Semantic/route memory may propose; fresh geometry verifies.
The planner optimizes progress, while an independent final gate restricts commands
even when planning or configuration is wrong.

### 3.9 Feedback control, latency, and stopping distance

A controller closes the loop from path error to linear/angular velocity. Whether it
uses proportional feedback or horizon optimization, tracking depends on fresh state,
bounded delay and an actuator model.

Parcel shapes velocity to respect acceleration and jerk, preventing discontinuous
requests. It then reasserts exact stop after shaping so a smoother cannot “soften” a
safety zero into residual motion. The crucial physical budget is

```text
d_stop(v) = r_foot + v tau + v^2/(2 a_brake) + Z_sensor + Z_robot
```

where `r_foot` is footprint radius, `tau` is total sensing/compute/transport/actuator
reaction latency, `a_brake` is measured deceleration, and the `Z` terms reserve for
sensing intrusion and pose uncertainty. For people, their closing motion during the
response horizon must also be considered. The quadratic braking term means doubling
speed more than doubles required clearance. The latency term explains why a fast
model that is usually 50 ms but occasionally 700 ms cannot sit synchronously in the
motion loop without a deadline and safe fallback.

`SafetyEnvelope` encodes this equation and supplies one authority surface. Its committed
prototype values—0.70 m person band over a software-derived 0.68 m floor—are useful
simulation policy, not physical facts. Real `tau`, deceleration and uncertainty must
be measured end to end. The independent stop must remain available if Python, GPU,
LAN, cloud, UI or the main process dies.

### 3.10 Companion behavior is a robotics authority problem

A companion adds conversation, initiative, memory, identity and social spacing to
navigation. These are not merely UX services because they decide *whose* request is
authorized, *which* physical referent is intended, and *when* motion may resume.
Partial speech is useful for anticipation and interruption but should not authorize
motion; only a committed turn plus a recognized principal should. A language model
may propose “go beside the couch,” while deterministic code resolves the relation,
checks freshness, acquires resources and validates completion.

Memory may suggest where to look; it cannot prove current presence, free space or
speaker identity. Appearance/affect may personalize but cannot arm the base.
Corrections invalidate old task generations, and narration must follow evidence—a
controller timeout alone is not arrival.

Parcel's strongest design choice is this separation between semantic proposal and
physical admission. Its committed P2 memory and awareness work extends consent,
provenance, forget/replay and bounded initiative. The major gaps are production
speaker enrollment, runtime physical owner tracking, through-air endpointing/AEC,
and one uniform consequential-action lifecycle. A good companion feels fluid, but
fluency must be built around—not in place of—identity, uncertainty and stop authority.

## 4. Current architecture as built

### 4.1 End-to-end authority path

The current design is a hybrid deterministic autonomy stack:

```text
text / microphone / hosted Realtime
              |
   committed transcript + principal
              |
 deterministic intent router ---------> immediate STOP/cancel
              |
 local PlanSketch or model PlanIR proposal
              |
 compiler + fresh-snapshot validator
              |
 TaskExecutive + resources + task revision
              |
 navigation / follow / spatial / activity controller
              |
 priority + TTL command arbiter
              |
 input health + obstacle/person/TTC safety
              |
 smoothing/shaping + post-shaper exact-stop reassertion
              |
 ControlManager / simulator command sink
```

The model supplies semantic value: interpreting open-ended language, proposing
bounded tasks, responding conversationally and eventually suggesting recovery.
It does not own raw velocity, joints, safety priority, actuator leases or successful
completion. This boundary should not be weakened as models improve.

The code still has more than one consequential-action lifecycle. Navigation,
following and typed tasks normally use the brain/executive path, while some legacy
walk, catalog skill, pose/trajectory and fallback paths bypass portions of it. They
still encounter downstream safety in the simulator runtime, but task resources,
pause/resume, progress and verification are not uniform. The target is one semantic
task gateway for every non-emergency physical effect, plus a separate dominant STOP.

### 4.2 Normal composition remains simulation-first

The normal UI/runtime builder constructs a `MujocoSocketBackend`; the stack launcher
ultimately starts the simulator. The runtime's central observation is still
`SimObservation`, carrying truth pose, ray-cast scan, simulator owner/dynamic tracks
and semantic sidecars.

Canonical configuration reinforces this:

- controller: simulator;
- Unitree command axes: uncommissioned;
- Unitree state frame: uncommissioned;
- allowed physical modes: empty;
- navigation model: deterministic `grid_v1`;
- semantic source: simulator `oracle`;
- route memory: disabled;
- `rl`-named motion backend: empty policy path, therefore no actuating learned
  locomotion policy.

This is good fail-closed configuration. It also means changing a launcher option or
adding a vendor class does not create a physical product.

### 4.3 Subsystem truth table

| Subsystem | Implemented and useful now | Missing product evidence |
| --- | --- | --- |
| Local navigation | 161×161 rolling log-odds grid at 0.1 m, inflation/costs, eight-connected A*, path tracking and reactive/TTC safety | Persistent free-space map; consistent invalid-scan HOLD policy; physical traversal |
| Semantic mapping | Oracle rows for deterministic simulation; committed experimental `OnlineMap` with evidence, visits, names, embeddings, decay and persistence | Physical input, promotion accuracy, map lifecycle and proof that it never substitutes for SLAM |
| Localization | MAP/ODOM `PoseProvider`, covariance/health validation, truth and drifting-odom providers | EKF/graph estimator, IMU/contact/visual/LiDAR fusion, `T_map_odom`, loop closure and relocalization monitoring |
| Motion safety | Priority/TTL arbitration, finite/fresh/frame/origin checks, person/obstacle/TTC gates, shaping, exact-stop reassertion, watchdog and stationary witness | Native sole-writer gateway, independent stop campaign and commissioned response/braking envelope |
| Interaction | Local and hosted voice lanes, committed-turn authority, task compiler/executive and deterministic STOP | Active hosted config in a clean checkout, tuned through-air endpointing/AEC and one uniform action lifecycle |
| Companion memory | Committed consent/provenance owner facts, remember/forget/replay, affect labels and bounded initiative | Production speaker enrollment, deletion audit, distillation lifecycle and physical owner-presence source |

The committed runtime can install/feed/persist an instance-bound learned map when a
`learned_map` or `shadow` navigation profile is actually selected; recorded simulator
patrol evidence grew 69 entries/seven labels and then 85/eight after reload. Shipping
navigation remains oracle-driven, `robot.prototype.yaml` leaves the prototype
navigation overlay commented out, and the normal camera attach site still builds
MuJoCo/EGL. The map is therefore implemented and narrowly wired under explicit
configuration, not the verified default and not physical SLAM.

The committed P1-E profile similarly exposes a 0.70 m stranger band above a
software-derived 0.68 m floor and a 1.25 m owner keepout. Those are simulator policy,
not commissioned stopping evidence, and planner inflation does not yet share one
complete envelope with the final gate. Unitree `StopMove` is a useful command, but
it is not an independent power cut.

## 5. Committed experimental capability snapshot

Wave P1/P2 landed in `b74f0bf`; `21ea2fb` landed Week 1; Wave 2 Batches A and B
then landed in `e15e466` and `939001e`. Committed is still not synonymous with
commissioned: normal composition remains simulation-first and none of these
mechanisms has closed its intended-hardware rows. The table records committed
engineering progress while retaining the **experimental** maturity label.

| Wave | What exists | Recorded evidence | Why it remains experimental |
| --- | --- | --- | --- |
| P1-A physical camera/process | UVC, RealSense, recorded backends; Unix-socket detector/embed daemon | Synthetic/recorded detector p50 about 100.6/113.7 ms; process overhead p50 0.6/1.8 ms; corrected targeted 93 pass/1 expected failure | No camera attached; physical backends not selected by normal runtime; UVC lacks metric depth |
| P1-B learned map | Runtime install/feed/persist, thumbnails/naming/embeddings | Sim patrol 69 entries/7 labels; reload continuation 85/8; status records 500 pass/2 warnings | Default remains oracle; no physical precision/recall, duplicate/retrieval score or crash-durability proof |
| P1-C owner appearance | Enrollment gallery, embeddings, tracker and UWB fusion seam | Desktop SigLIP crop embed p50 3.44 ms; corrected GPU status 100 pass | Held-out owner recall/live two-person continuity halted; runtime owner still mocap truth |
| P1-D VLM veto/names | Subtractive veto, represented ASK outcome, vocabulary/name growth | 18/40 (45%) naming fixture; corrected targeted 51 pass/1 skip | ASK is unwired; VLM is off the current 10 Hz dispatch call graph, but `mark_control_thread` has no production caller; no motion-admission authority |
| P1-E social zone | Configurable prototype band and derived authority floor | Large targeted simulator sweep recorded | No physical braking/comfort evidence; full planner/final-gate envelope unification not delivered |
| P2-A owner facts | Structured fact store, consent, replay, remember/forget tools | Nine deterministic probe families met | Hosted model-chosen row unrun; privacy/distillation lifecycle incomplete |
| P2-B identity/affect/initiative | Labels rather than gates, affect and bounded event plumbing | Targeted software matrices recorded | No speaker enrollment or physical owner event source; no base authority |

Week 1 adds several meaningful committed results:

- GATE-0 tracks a provenance-pinned 20-file Unitree pack, evaluates its closure and
  scenes before safety consumers, contains ordinary commit-stage exceptions, pins
  Ruff, fixes the Python 3.11 dataclass import, and provisions hosted OSMesa.
- TURN-1 makes hosted endpointing configurable while retaining the default payload;
  MARK-1 distinguishes generated, acknowledged, played and interrupted audio.
- ROAM-1 exposes bounded owner-commanded wandering. Seven 120-second simulator runs
  stayed in bounds, reported zero contacts and achieved 1.30--6.57 m net displacement,
  while also revealing two timing/load-sensitive behavior modes rather than one
  stable exploration policy.
- CURIO-1 adds bounded evidence-grounded remarks; AIR-1 contributes measurement
  tools but deliberately leaves through-air acoustic rows unmeasured.

Wave 2 is now committed: physical-camera venue selection, calibrated owner-state
wiring, correctness-gated names/ASK, shared doorway clearance, duplex turn policy,
capability admission, frozen prompt/runtime hygiene and optional coverage-directed
roam all crossed the software release boundary. ROAM-2's coverage objective is
wired and default-off, but its registered 1.5× improvement claim missed because the
metric saturated and the policy remained too home-seeking. It is evidence of a
remaining exploration gap, not a promoted autonomy capability. Wave 3 is the new
in-flight plane and remains uncommitted.

The correct promotion pattern is consistent across these features:

1. keep default behavior unchanged;
2. run the challenger on deterministic fixtures and nulls;
3. measure real sensor/model timing and accuracy;
4. run shadow on independent physical data;
5. freeze thresholds before final held-out evaluation;
6. promote only as a proposal source under existing deterministic admission;
7. preserve rollback and exact evidence provenance.

## 6. Current quality and integrity snapshot

### 6.1 Scale and collection

At committed `939001e`, the accepted Batch-B gate collected 9,512 tests. Under the
declared eight-worker/CPU shape, all ten hard stages passed; the parallel default
suite reported 9,403 passes, 17 skips and one expected failure, and its serial rows
also passed. The result was repeated from a tracked-only clean clone at the accepted
resource shape. The active Wave-3 tree is changing underneath this update, so its
larger counts and targeted card results are not promoted into a new denominator.

This is a substantial engineering test surface and the earlier clean-source
aggregate defect is closed for the declared local gate. It is still not hosted,
aarch64 or physical assurance.

### 6.2 What GATE-0 fixed, and what remains

**1. The committed tracked-source gate is now green at the accepted local shape.**
HEAD tracks the provenance- and hash-pinned Go2 pack, validates its closure before
safety consumers, contains ordinary stage exceptions and explicitly caps the gate
at eight workers. GATE-0b reproduced the complete pass from a tracked-only clean
clone. Hosted execution and a pre-existing load-sensitive WebSocket test remain
separate release risks rather than reasons to reopen the clean-clone result.

**2. Python portability has a useful uncommitted answer, not a released target
answer.** HW-1 proves the source/import floor on real CPython 3.10 and selects a
CPython 3.12 product environment with 3.10 vendor/capture environments. Its aarch64
locks resolve, but nothing has executed on the Orin and the Jetson ORT-GPU source is
still unresolved. HW-7 must turn that design into an honest target-device gate.

**3. Eager package barrels still collapse module boundaries.** Importing a
core/navigation leaf can load roughly 118 Parcel modules, including the large
navigation pipeline, simulator environments and InstructNav. A seven-hop cycle
previously allowed `_HAS_INSTRUCTNAV=False`, turning required semantic navigation
into a no-op while other tests remained green. Thin package initializers, leaf
imports and startup-fatal capability admission remain higher leverage than merely
splitting the god objects.

**4. Hosted, aarch64 and the current wave remain separate promotion gates.** Workflow
text is not a retained hosted run or branch-protection proof. The uncommitted Wave-3
tree must earn its own integrated gate, and the Orin must produce an explicit
run/skip-with-reason report rather than inherit a desktop verdict.

### 6.3 Current execution evidence

The accepted `939001e` landing gate passed all ten hard stages on the quiescent
developer tree with the eight-worker setting: Ruff retained seven baseline
fingerprints and added none; tier coverage was 9,512; the parallel default suite
reported **9,403 passed, 17 skipped and one expected failure**, followed by passing
serial rows. GATE-0b separately established the tracked-only clean-clone shape.

That evidence is unusually candid about its limitations. ROAM-2's coverage objective
does not yet explore effectively; AIR-1's estimated speech onset cannot pass as a
measured latency; no camera or Go2 hardware row ran; and one loopback-WebSocket test
is documented as load-sensitive. Hosted Actions, branch protection, aarch64 execution
and physical campaigns still require independent closure. Wave 3 is uncommitted and
has targeted card evidence only, not a stable integrated result.

There are useful narrow positives: 100 packaged assets are byte-parity checked;
frozen navigation and safety/latency/freshness panels reproduce expected results;
assertion and seeded-defect fixtures show that many tests detect the intended fault.
These are strong test techniques. They do not qualify physical hardware.

The executive quality statement is therefore:

> Strong local regression engineering with a tracked-source gate that is green at
> the declared eight-CPU shape; hosted, load-sensitive, aarch64 and physical
> assurance remain, and Wave 3 must earn its own integrated verdict.

## 7. Physical Unitree readiness

### 7.1 What exists

Parcel has a useful high-level Unitree foundation:

- lazy Unitree Sport controller factory;
- high-level body-velocity mapping to `Move`/`StopMove`;
- controller state source and mode handling;
- leases, command/state freshness, limits, faults, tilt response, stop retries and
  stationary confirmation in `ControlManager`;
- explicit axes/frame/mode commissioning records and CLI concepts;
- evidence-origin controls intended to distinguish physical from synthetic state.

Using Unitree Sport for the first ODD is the correct tradeoff. The vendor controller
owns high-rate balance, contact and gait, while Parcel supplies bounded body-velocity
requests. Moving to low-level joints or learned torque control would multiply the
safety and controls program without being necessary for initial companion behavior.

### 7.2 What is missing

The normal runtime does not instantiate the Unitree manager and a physical sensor
spine together. It lacks:

- synchronized camera/LiDAR/IMU/joint/controller evidence;
- hardware clock mapping and commissioned extrinsics;
- physical odometry/localization/SLAM and transform health;
- a backend-neutral physical observation accepted by navigation/safety;
- a calibrated owner/stranger belief;
- a native restart-disarmed sole-writer gateway;
- an external independent stop integrated into the test plan;
- measured velocity response, stop distance, slope/surface/payload/battery behavior;
- a capability-admitting deploy supervisor and repeated physical scenarios.

Starting a detector daemon or selecting a camera environment variable does not close
this gap: normal runtime camera attachment still creates MuJoCo/synthetic sources.
Likewise, an official Go2 model in MuJoCo is not proof that the simulator uses
physical locomotion dynamics; current base travel is principally a behavioral/
kinematic integration test.

### 7.3 First physical architecture

```text
physical sensors + Unitree state
          |
 timestamps / calibration / provenance
          |
 odometry + localization/SLAM + transforms
          |
 synchronized RobotObservationV2
          |
 local grid / tracks / semantic proposals
          |
 task-selected controller candidate
          |
 independent final safety disposition
          |
 native sole-writer gateway (epoch/lease/TTL/watchdog)
          |
 Unitree Sport Move/StopMove + stationary feedback
```

UI, hosted dialogue, history persistence and large semantic models remain outside
the stop island. Their failure may reduce experience or task capability; it cannot
extend positive-motion authority.

## 8. Target architecture and principal changes

The target is not a whole-codebase ROS or C++ rewrite. It is a modular semantic
application with a few deliberately isolated physical/timing domains.

### 8.1 Target process boundaries

1. **Python semantic application:** interaction, intent, PlanSketch compilation,
   mission supervision, deterministic task executive, memory, semantic world model
   and narration.
2. **Sensor/localization sidecars:** drivers, timestamping, transforms, odometry/
   SLAM, local maps and tracking using ROS 2/C++ where mature infrastructure helps.
3. **Local-autonomy/admission sidecar:** high-rate bounded navigation snapshots,
   local planning candidates and final safety disposition.
4. **Native Unitree gateway:** one robot-network credential/writer, boot epoch,
   arm/disarm, authenticated lease, monotonic sequence, TTL, local limits, watchdog,
   stop dominance and stationary witness.
5. **Optional inference workers:** detector/embedding and language services behind
   bounded queues, deadlines, cancellation and capability health.

### 8.2 Structural refactor order

The order matters:

1. make `core`, `navigation`, `navigation.envs` and `instructnav` initializers thin;
2. migrate production consumers to leaf imports;
3. add forbidden-import/order and capability-admission tests;
4. define synchronized observation, transforms and gateway contracts;
5. then split the 14,293-line `runtime.py` and 6,604-line navigation coordinator
   into lifecycle-owned services.

Splitting the giant files first would move code while preserving the import cycle
and ambiguous capability boundary. Package integrity is the higher-leverage first
step.

## 9. Principal design tradeoffs

| Decision | Selected tradeoff | Benefit | Accepted cost |
| --- | --- | --- | --- |
| Hybrid agent vs token-to-motor | Models propose; deterministic code admits/executes | Replaceable models, bounded authority and truthful replay | More contracts and explicit skills |
| Classical actuating baseline vs learned navigation | A*/tracker actuate; learned systems shadow/propose | Data-efficient, inspectable rollback | May initially underperform advanced methods |
| Unitree Sport vs low-level control | Vendor balance/gait; Parcel body velocity | Much smaller physical assurance problem | Less gait/expression authority |
| Semantic map vs metric SLAM | Keep linked but separate | Correct uncertainty/decay/authority semantics | Transform/revision bookkeeping |
| Route memory vs current geometry | Memory proposes; fresh grid verifies | Familiar long-horizon routes without stale free-space authority | Persistence/reanchoring work |
| UVC vs RGB-D | RGB-D first for metric grounding | Matches current depth/localization contract | Cost, power, USB and calibration |
| Selective ROS vs ROS rewrite | Use ROS for sensors/tf/bags/localization | Gains mature infrastructure while preserving task/safety design | Two ecosystems and IPC contracts |
| Hosted vs local voice | Hosted conversation optional; local closed intents/STOP | Interaction quality without cloud safety dependency | Privacy, cost, network and dual paths |
| Independent final gate vs shared check | Share calibrated inputs, recompute restriction | Defense against planner/config mistakes | Intentional duplicate computation |
| Ordered EDU Plus posture | Treat it as supervised R&D and gate every physical authority separately | Earlier physical learning without a deployment claim | Capital/operator/lab obligations before product readiness |

Two policies should remain non-negotiable:

- No learned/model/memory component may manufacture physical truth or increase
  downstream motor authority.
- Route memory, semantic names, external maps and language assertions may propose
  where to look; only fresh geometry/localization and deterministic admission may
  justify how to move or whether arrival is true.

## 10. Gated delivery plan

| Gate | Work | Exit evidence |
| --- | --- | --- |
| **A. Release integrity** | Preserve the green tracked-only eight-worker gate; close the load-sensitive WebSocket case, add hosted evidence, land the explicit product/vendor Python split, prove aarch64 disposition and keep required capabilities startup-fatal | Local, hosted and target reports name the same admitted rows or explicit target-only skips. No Wave-3 promotion inherits Batch B's verdict. |
| **B. Lab readiness** | Freeze EDU SKU/firmware/SDK/BOM; prepare controlled area, stop/tether, operator, network, capture and privacy procedures | Signed R&D acceptance plan; read-only data can be captured on day one. |
| **C. Physical substrate** | Inventory/telemetry; clock and extrinsic calibration; physical bags/replay; native gateway; axes/frame/mode and fault commissioning | Tethered minimum-speed motion independently stops on expiry, client death, state loss and operator action. |
| **D. Estimation/perception shadow** | Compare SLAM on common bags; publish MAP↔ODOM health; wire RGB-D/LiDAR; measure metric perception, semantics and owner ROC/ID switches | Frozen timing/accuracy/health thresholds pass independent visits without synthetic/physical mixing; learned output remains proposal-only. |
| **E. Supervised mobility** | Point/semantic goals through doorways, blockage, people, localization jumps and process/network faults | Repeated first-ODD missions meet collision, clearance, intervention, success, latency and false-arrival thresholds. |
| **F. Companion behavior** | Physical owner enrollment/follow/reacquisition; noisy through-air voice; correction/recovery; complete memory privacy lifecycle | Bounded missions show identity continuity, truthful narration, acceptable comfort and explicit handoff. |
| **G. ODD expansion** | Add one dimension at a time: surface, lighting, novelty, density, outdoors or supervision | Each expansion has separate hazards and evidence; roads, stairs, elevators and unsupervised public use remain separate programs. |

## 11. Executive risks and decisions required

### 11.1 Top risk register

| Risk | Impact | Immediate mitigation |
| --- | --- | --- |
| False-green release/capability admission | Features silently absent while tests appear green | Integrity Gate A; thin imports; startup-fatal required capabilities |
| No physical localization/SLAM | Global goals, maps and arrival invalid on hardware | Select sensor/estimator candidates; physical bags; MAP↔ODOM health contract |
| Simulator-to-real overclaim | Unsafe procurement/field expectations | Separate evidence levels; physical system identification and stopping campaign |
| Owner identity switch | Robot follows a stranger | Explicit enrolled belief, ROC/ID-switch gates, ambiguity means HOLD |
| Duplicated safety envelopes | Planner/gate disagreement or unexplained stops | One immutable calibrated envelope input; independent monotone final recomputation |
| Python/GPU/cloud failure in motion path | Extended motion or loss of stop | Native sole-writer gateway; local TTL/watchdog; independent stop |
| Personal data leakage/false memory | Trust, privacy and regulatory harm | Consent/provenance, purpose/retention, delete-derived audit, labels not credentials |
| Compute/thermal/dependency mismatch on Orin | Missed deadlines or unusable deployment image | aarch64 install proof, worst-load profiling, thermal soak and power budget |
| Large mutable coordinators | Wide blast radius, lock/teardown defects | Fix import boundaries, then extract lifecycle-owned services |

### 11.2 Decisions leadership must own

1. Exact first ODD, supervision model and hard release thresholds.
2. EDU Plus acceptance/firmware plus the final sensor, battery, mount, independent-stop and network BOM.
3. Supported Python/deployment matrix, including ROS/Humble and Jetson/aarch64.
4. Selected localization/SLAM provider and whether Parcel owns or integrates it.
5. Physical speed regimes and measured stopping/uncertainty reserves.
6. Owner enrollment, identity, consent, retention and multi-person voice authority.
7. Which pose/gesture actions remain simulator-only versus receive a separately
   commissioned gateway capability.
8. What task state may resume after process restart, relocalization or gateway re-arm.
9. Who signs safety review, operates the lab and accepts each promotion gate.

### 11.3 Recommended next milestone

The next milestone should be named:

> **Hermetic software integrity plus a safely commissioned, observable Go2 research
> platform.**

It should not be named “autonomous companion dog.” That later milestone becomes
credible only after the physical estimation–perception–control evidence spine and
repeated first-ODD companion missions exist.

The immediate implementation order is: close HW-4; build the observe-only
`Go2Backend` and typed physical scan authority; admit one physical EDU Plus profile;
prove the aarch64 deployment shape; land the Orin firewall and microphone-arm route;
then perform read-only box-day capture before LIO/SLAM, native-gateway and tethered
minimum-speed commissioning. New semantic breadth should not displace that chain.

## 12. Source map and further reading

- [Canonical engineering handbook](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md)
  — full current architecture, quality evidence, subsystem designs and robotics
  textbook.
- [Documentation index](README.md) — authority and specialist routing.
- [CI gate reference](CI.md) — intended runner/cadence plus current integrity warning.
- [Dependency/environment guide](DEPENDENCIES.md) — host/dependency state and
  Python/asset warnings.
- [Motion and Unitree commissioning](MOTION.md) — controller lifecycle and cautious
  physical bring-up.
- [Wave 3 hardware design](../scrum/20260822/WAVE3_HW_DESIGN_FABLE.md) — current
  dependency order, hardware unknowns and software-now/box-day split.
- [Runtime concurrency and clocks](RUNTIME_CONCURRENCY_AND_CLOCKS.md) — threads,
  queues, clock domains and scheduling limits.
- [Integrity-gate corrective TODO](../scrum/20260822/INTEGRITY_GATES_TODO.md) — exact
  current closure work.

The engineering rule for every future status update is simple: name the exact
artifact, default configuration, evidence environment and highest maturity level
actually passed. Implemented is not wired; wired is not verified; simulator-verified
is not hardware-commissioned; fluent narration is not physical truth.
