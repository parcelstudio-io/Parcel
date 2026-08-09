# Research report — camera/LiDAR all-terrain navigation for Parcel

**As of:** 2026-08-09  
**Method:** repository audit at `19c922662add83959ea2e97693e29251437d09b6`
plus a read-only review of the concurrent dirty worktree and independent primary-source
research. The concurrent files were not modified or attributed to task_7.

## Executive answer

The best development direction is a hybrid hierarchy, not one “navigation model”:

- retain Parcel's deterministic command/task compiler, typed arbitration,
  `LocomotionController`, `ControlManager`, and simple voice input;
- replace simulator-truth pose and 2-D-only geometry with synchronized 6-DoF
  LiDAR/camera/IMU state estimation, a probabilistic elevation map, and a complementary
  3-D clearance map;
- use capability-constrained global routing plus a terrain-aware predictive local
  planner that prefers turn-and-forward motion but permits lateral recovery;
- retain Unitree Sport as the initial flat/mild-terrain physical backend;
- train one narrow learned subsystem—a perceptive Go2 locomotion controller for rough
  ground, slopes, and stairs—because the research audit found no ready-to-ship,
  permissively licensed, verified Go2 checkpoint for that role;
- train in Isaac Lab, independently replay the frozen policy in Unitree MuJoCo, retain
  Parcel's MuJoCo city for fast regressions, and use dynamic-city/indoor simulators as
  distribution tests rather than pretending one engine models everything; and
- put a post-shaper raw-sensor/stability admission layer after every planner/controller.

This program can make Parcel good across a deliberately broad, held-out simulated ODD.
It cannot guarantee no collision in arbitrary simulations and cannot establish real-
world safety before sensor calibration, actuator identification, physical commissioning,
and controlled hardware tests.

## 1. Updated codebase audit

### 1.1 What is genuinely strong today

The flat navigation prototype has useful production-shaped seams:

- `src/parcel_robot/navigation/base.py:47-101` separates `NavObservation` from a
  mid-level `(vx, vy, vyaw)` command.
- `src/parcel_robot/mujoco_lidar.py:416-545` performs occlusion-correct MuJoCo ray
  casting, self-hit rejection, noise/dropout, and range envelopes. This is genuine
  simulated sensing rather than direct obstacle coordinates.
- `src/parcel_robot/navigation/grid_planner.py:372-782` maintains rolling log-odds
  occupancy and plans A* routes over hard and dynamic costs.
- `src/parcel_robot/navigation/grid_navigator.py:405-585` replans, aligns before moving,
  uses forward-only autonomous tracking (`vy=0`), and provides bounded scan recovery.
- dynamic-agent infrastructure predicts circle TTC and applies a cost layer; it is a
  useful deterministic social-navigation regression even though actors are scripted.
- `src/parcel_robot/control/base.py:24-60`, `control/models.py`, and
  `control/manager.py` define a replaceable, leased controller boundary, typed feedback,
  timing, limits, stop confirmation, faults, and exclusive motion ownership.
- `control/unitree_sport.py` maps body velocity to Unitree Sport `Move`, delegating gait
  and balance to the onboard closed loop. This is the right first physical boundary.
- current evaluators preserve run metadata and often state their `does_not_prove`
  limitations honestly.

These should be extended, not thrown away.

### 1.2 What is live/default

`configs/navigation/default.yaml` selects `grid_v1`; the model config declares a CPU
rolling 2-D grid/A* and disables RL. The model factory supports only the stub and grid
navigators; CityWalker/NaVILA/NoMaD/ViNT YAMLs are declarations, not live inference.

The effective navigation observation is:

- exact simulator pose from `TruthPoseProvider` (`pose.py:190-241`);
- a 360-degree horizontal MuJoCo LiDAR scan;
- exact MJCF-derived semantic regions/objects;
- scripted dynamic actors and motion feedback.

IMU tilt is consumed by the control-manager fault gate, not terrain estimation. The
Sport feedback schema includes foot forces and joint state fields, but the Sport adapter
currently populates foot forces without joint positions/velocities, and navigation does
not consume either for terrain or stability planning.

### 1.3 Camera and semantics are not yet sensor-real

The D455-shaped `CameraChannel` and MuJoCo-EGL backend can emit synchronized RGB/depth
and optional segmentation. They are tested as standalone components, but no live
camera capture exists in `runtime.py`, `sim.py`, or `headless_city.py`.

The dirty worktree also contains concurrent Task 4 foundation work that corrects the
MuJoCo free-camera frustum/extrinsics, adds a detector-agnostic pixel/depth localizer and
segmentation-truth detector, and adds an additive `T-cam-foundation` geometry pack. That
is useful progress toward trustworthy camera geometry, but it still does not attach
camera capture/detections to the mission runtime or provide real-texture recognition.
Task 7 therefore treats it as an upstream in-progress dependency, not as a completed
navigation sensor path.

Instead, `runtime.py:4879` and `headless_city.py:931` call
`semantic_candidates_from_observation`. `city_semantics.py:45-170,294-314` reads object
IDs, exact coordinates, support polygons, and goal regions from MJCF; its visibility
test is range plus horizontal FOV, with no pixel render, depth or occlusion test. It
then stamps high confidence and a camera-like source. This is evaluator/oracle-quality
metadata, not camera perception.

Task 4 correctly owns the pixels → detection → grounding → semantic lock-on transition.
Task 7 consumes that future semantic layer but must not depend on it to build geometric
terrain locomotion.

### 1.4 Localization is a seam, not a localizer

`pose.py` explicitly supplies exact zero-covariance simulator truth. There is no SLAM,
EKF/factor graph, LiDAR-inertial odometry, or time-indexed `map -> odom` implementation.
`grid_navigator.py:340-355` notes that MAP goals are effectively used as ODOM because
truth makes the frames coincide. That assumption breaks after a real estimator drifts
or relocalizes.

### 1.5 There is no current terrain locomotion

The current city scene contains a plane and shallow boxes, not a stair/hill curriculum.
`headless_city.py:111-119,463-496` explicitly describes and implements a kinematic base:
it integrates only planar x/y/yaw, writes root state directly, and checks planar
clearance. `sim.py:214-237,510-526` similarly repositions the base around MuJoCo steps.
`gait.py` and `sim_control.py` author leg poses visually, without contact feedback or
dynamic balance. `rl/env.py` is a stub and cannot observe motion or terminate on a fall.

Consequences:

- stair traversal can be a sliding/teleportation artifact;
- no foot–terrain contact, slip, torque, energy, body collision, fall, or recovery is
  meaningfully evaluated;
- a 2-D scan/map cannot represent slope, stair tread, drop-off, overhang, or foothold;
- current success metrics cannot qualify a low-level learned controller.

Unitree terrain assets already vendored under `third_party/unitree_mujoco` are useful
inputs, but Parcel does not execute its controller/evals in those articulated scenes.

### 1.6 Dynamic city is useful but not physical

`dynamic_city.py` moves seven pedestrians and a cyclist on deterministic loops. The
MJCF actor geometries are non-contact. The MetaUrban wrapper identifies itself as a
kinematic scaffold and raises `NotImplementedError` when the real backend is requested.
These can test perception, TTC and planning, but not person contact dynamics or social
generalization.

### 1.7 Existing evals answer narrower questions

- NAV_INSTRUCT measures semantic/instruction outcomes in the kinematic/oracle city. It
  explicitly does not prove camera/VLA perception. Recent recorded candidate results
  show modest instruction success, not terrain capability.
- FOLLOW_BENCH's 9/9 follow result is valuable arbitration/trajectory evidence, but its
  report disclaims real sensing, quadruped contact physics, and reactive humans.
- the BARN adapter is sensor-only and useful for planar clutter, but its native runner
  uses circular unicycle/Go2-oriented planar kinematics; the official benchmark is a
  Jackal with 2-D sensing. It cannot score stairs, legs, or body stability.
- the Habitat smoke renders/moves but does not yet run Parcel's full goal/policy scorer;
  its proposed bridge collapses depth to a planar scan.

Therefore terrain work needs a new evaluator *kernel and scenarios*, while preserving
these existing harnesses as non-regression and semantic/flat slices.

## 2. Immediate safety implications from the audit

These are blockers independent of which learned policy wins:

1. Missing/malformed LiDAR may fall back to point-goal translation. Required geometry
   must instead assert a physical/default exact hold.
2. Environmental collision veto currently occurs before final S-curve shaping, which
   can leave residual velocity on the actual handoff tick. Admission must be final and
   non-relaxable.
3. There is no negative-obstacle, overhang, support, terrain, or foothold safety layer.
4. `map -> odom` is missing and truth currently conceals that frame error.
5. simulated 360-degree FOV conflicts with some planned/reported rear-blind profiles.
6. current missing/stale telemetry behavior may preserve yaw; that is not safe until a
   rotational swept body/leg envelope is validated.
7. simulator semantic truth and exact pose can leak into learned training/evaluation
   unless evaluator and policy schemas are made structurally different.
8. two low-level writers would be catastrophic; Sport-to-learned switching needs exact
   hold, stop confirmation, exclusive lease, and watchdog-enforced mutual exclusion.

These motivate P0 before policy optimization.

## 3. State-of-the-art pattern: hierarchy beats monolith here

Prominent successful systems separate capabilities even when learning is used heavily:

- perceptive locomotion research commonly trains a privileged terrain teacher and a
  noisy, recurrent exteroceptive/proprioceptive student;
- quadruped field planners consume elevation/traversability maps and model reachability
  rather than letting a language model reason about foot contacts;
- modern visual-language navigation systems often use a slow semantic planner plus a
  fast trajectory/navigation system;
- mobile navigation stacks keep a raw-sensor collision monitor below the planner; and
- sim-to-real locomotion programs cross-check a frozen learned policy in a second
  physics engine before hardware.

This matches Parcel's existing propose/dispose and `LocomotionController` seams. A
monolithic language/image-to-joints policy would couple sparse language errors, visual
domain shift, localization, collision avoidance, gait stability, and safety into one
artifact that is difficult to debug or qualify. It also puts large-model latency in the
wrong loop.

## 4. Sensor and mapping research

### 4.1 State estimation candidates

**GLIM** is the lead research candidate: current, MIT-licensed, ROS 2, LiDAR/range-
inertial factor-graph mapping with GPU support and multiple LiDAR/RGB-D forms. It is a
candidate, not an adoption decision; reproduce it on simulated Go2 motion, dynamic
scenes, stairs, time skew and calibration perturbation.

**FAST-LIO2** remains a strong throughput/accuracy comparator, including Unitree's own
Point-LIO adapter lineage, but GPL-2.0 and ROS 1 orientation complicate product reuse.
The experiment interface should allow it without making GPL code a shipped dependency.

Camera visual odometry/loop closure can complement LiDAR, particularly in semantically
rich indoor areas, but the low-level balance policy cannot require camera availability.

### 4.2 Two complementary maps

**Elevation Mapping CuPy** most closely matches legged navigation needs: probabilistic
GPU elevation fusion, visibility cleanup, height-drift compensation, multimodal layers,
and traversability plugins. Its current ROS 2 Jazzy release is promising. A ROS-neutral
core extraction exists but is newer; audit it before depending on it.

**Isaac ROS nvblox** supplies GPU TSDF/ESDF-style 3-D reconstruction from depth and/or
3-D LiDAR and includes people/general dynamic reconstruction modes. It complements,
rather than replaces, elevation mapping: a sliced 2-D navigation costmap does not encode
foot support or stair capability.

**Wavemap** is a permissive CPU/multiresolution 3-D fallback, but its public integration
is ROS-oriented and would need an adapter.

The selected design therefore uses an elevation/traversability grid for support,
slope, steps and roughness, and a 3-D occupancy/distance map for overhang/body clearance.
It explicitly represents uncertainty and unknown coverage.

## 5. Planner research

**Nav2 MPPI** is mature, predictive, supports omni/differential/Ackermann motion,
actuator delay, footprint validation, customizable critics and forward-preference. It
is a valuable flat/locally planar algorithm and baseline. Its SE(2) motion models do not
make it a foothold/stair planner.

**Nav2 Collision Monitor** establishes the right lower-layer pattern: raw laser/point
cloud/range inputs bypass costmaps and planners for stop/slow/TTC zones and source
timeouts. Its own documentation explicitly says it is not a hard-real-time safety-
certified component. Parcel should adopt the pattern and its test philosophy, not copy
a safety claim.

**ArtPlanner** plans over 2.5-D height maps with learned motion cost and is a strong
geometric reference. Its weights/simulator/follower are ANYmal/legacy-specific and are
not a ready Go2 product dependency.

**SCAN-Planner** is a particularly relevant 2026 challenger: spatial collision-aware,
LiDAR/depth inputs, multi-floor keypoints, and reported Go2 defaults. The code is very
new, Apache-2.0, and primarily ROS Noetic; pinned dependencies and reproducibility still
need audit before adoption.

**Wild Visual Navigation** can add an online/self-supervised visual traversability cost,
but that signal should remain uncertain and non-authoritative. **ViPlanner** has useful
depth/semantic planning ideas and weights, but its repository's restrictive rights
statement blocks default product adoption.

Recommended selection: an inspectable geometric/capability-aware planner and terrain
MPPI first; MPPI/SCAN/learned planner challengers run in shadow against the same frozen
episodes. Language/VLN models only propose semantic goal regions or short corridors.

## 6. Locomotion/open-weight research

### 6.1 What is available

- Isaac Lab exposes an official Unitree Go2 rough-velocity environment, procedural
  slopes/stairs/obstacles/gaps, contact/IMU/ray sensors, headless GPU training and
  domain randomization.
- RSL-RL provides GPU PPO and teacher/student workflows used across Isaac Lab and other
  legged systems.
- Unitree RL Lab is Apache-2.0 and explicitly targets Go2, with a Train → Play → Unitree
  MuJoCo sim-to-sim → sim-to-real workflow. Exact Go2 deploy/export coverage still must
  be verified because public deployment examples are G1-heavy.
- Unitree MuJoCo supplies Go2 models, low-level SDK2/DDS-shaped control, and terrain
  generation for stairs, rough ground and heightmaps. It is an excellent independent
  physics/API gate, not an emulator of the onboard Sport controller.
- Unitree's SportClient remains the supported high-level closed-loop body-motion API for
  initial physical use.

### 6.2 Why an existing checkpoint is not enough

The audit found excellent references but no verified, permissively licensed,
production-ready perceptive Go2 terrain checkpoint:

- Robot Parkour Learning is MIT and offers Go1 checkpoints/training plus a Go2 guide,
  but the guide expects a user-trained distilled log, D435i and low-level control.
- Extreme Parkour releases broad training code and strong terrain behaviors, but its
  non-commercial license is incompatible with a default product dependency.
- Agile But Safe provides a valuable recovery/reach-avoid switching pattern but is
  non-commercial and Go1-specific.
- DreamWaQ++ reports a compelling 10 Hz point-cloud / 200 Hz proprioceptive architecture
  and terrain results, but no code/checkpoints were found.
- Walk These Ways provides pretrained sim-to-real policies for Go1/legacy Isaac Gym,
  not the required Go2 perceptive-terrain artifact.

Accordingly, “find a better open-weight model” is not sufficient for this lower layer.
The justified training scope is narrow: start from the official Go2 rough task and
distill a camera/LiDAR/proprioception student. Do not train language or semantic task
reasoning with it.

### 6.3 Teacher/student and fallback rationale

A privileged teacher can learn efficient contact behavior from exact terrain and
physics. A student must infer a latent terrain/state belief from noisy delayed sensors
and proprioception. Recurrent history is important when a footstep or camera view
temporarily hides terrain. Training sensor outages permits a stable proprioceptive
fallback; it does not authorize blind route progress. Navigation holds when route
geometry is missing, while the controller continues balance/stand/recovery.

Physics and sensor domain randomization plus Isaac → Unitree MuJoCo frozen-policy tests
reduce simulator exploitation. They do not erase real actuator/sensor identification.

## 7. Simulator research and selection

### 7.1 Primary training: Isaac Lab / Isaac Sim

Why selected:

- official Go2 rough task and Unitree-maintained derivative;
- vectorized GPU contact physics and procedural terrain curriculum;
- cameras, contact sensors, IMU, fast mesh ray casting, and RTX camera/LiDAR;
- physics and sensor randomization; and
- headless execution suitable for nightly exposure.

Use fast static-mesh ray casting for large teacher batches and smaller RTX-sensor
batches for sensor-faithful student/release tests. The fast ray caster's static-mesh
limitation means dynamic actors need RTX or another sensor path.

### 7.2 Daily/cross-physics: MuJoCo

Retain the current kinematic Parcel scene for high-speed deterministic instruction and
planar regression. Add a distinct articulated Unitree MuJoCo backend for controller
physics and sim-to-sim. Do not retrofit contact claims into the kinematic harness. MJX
is an optional later GPU-training challenger, not a prerequisite for the Isaac baseline.

### 7.3 Integration: Gazebo Harmonic

Gazebo is useful later for ROS 2 TF/QoS/topic timing, sensor noise, message loss and HIL.
It is not the high-throughput RL engine. Gazebo visual actors are not contact-dynamic
people; safety scenarios require physics-enabled bodies.

### 7.4 Urban and indoor sidecars

**MetaUrban** supplies permissively licensed procedural urban layouts, sidewalks,
traffic, pedestrians, RGB/depth/semantic/LiDAR observations, and social navigation. It
is the strongest immediate city-distribution sidecar, not a Go2 contact authority.

**URBAN-SIM** is especially interesting because it is Isaac/PhysX and explicitly uses
Go2 in urban locomotion/navigation research. The public repository still marks several
long-horizon/dynamic/checkpoint features TODO; treat it as a challenger, not a critical
dependency.

**Habitat** and **iGibson/OmniGibson** contribute scanned/interactive indoor semantics,
ObjectNav/VLN and social tasks. Habitat's official repositories state maintenance is
frozen beyond v0.3.4; pin it for evaluation, not the central training engine. These
benchmarks usually abstract navigation and do not qualify quadruped stair contacts.

### 7.5 External terrain evidence

Google DeepMind's **Barkour** provides an open MuJoCo obstacle course/scorer and useful
agility taxonomy. Parcel's Go2 adaptation must be reported as adapted—not an official
Barkour leaderboard comparison—because embodiment/course assumptions differ.

**RoboGauge** is a promising new Go2 MuJoCo terrain suite (flat, slope, stair up/down,
obstacles/wave, progressive difficulty), but it is immature and anonymous/new as of the
review date. Audit its code and metric sensitivity before using it as a trust anchor.

Existing BARN remains a flat-clutter planner metric only. No single score should merge
BARN, semantic instruction, social navigation, and legged terrain performance.

## 8. Vision-language and navigation foundation models

The best open candidate for later high-level shadow evaluation is **InternNav**:
MIT-licensed code, model zoo/training, Habitat/Isaac coverage, continuous trajectory and
dual-system VLN, and public Go2 deployment material. It can propose a goal or corridor;
it cannot own local terrain safety or joints.

**Qwen-RobotNav** is a useful dual-system architecture reference with short waypoint
outputs and reported Go2 deployment, but its official repository says weights will not
be released. It is not an installable solution.

**NavDP**, **NaVILA**, and **CityWalker** are useful challengers for short trajectories,
language navigation, or urban priors. Each has embodiment, dependency, license, or
terrain-authority limitations. They should be scored through the same proposer adapter,
never wired directly to velocity or joints.

This task does not require any of them for stairs/hills. They become relevant after
sensor-real mapping, local safety, and semantic goal-region contracts exist.

## 9. Alternatives considered

### Rewrite all navigation as end-to-end RL/VLA — rejected

It entangles language, perception, geometry, route choice and joint stability; makes
hard stops/lineage difficult to inspect; needs vastly more diverse data; and gives no
clear advantage over a hierarchy for deterministic commands and safety constraints.

### Use only Unitree Sport APIs — insufficient but retained

Sport is the safest initial high-level gait/balance boundary, but it does not give
Parcel camera/LiDAR localization, semantic goal grounding, global route planning,
dynamic-city reasoning, or a measured arbitrary-stair capability. Keep it on supported
terrain and build perception/navigation above it.

### Use only Nav2/2-D costmaps — rejected for terrain

Mature for planar navigation; unable to encode support, drop-offs, cross-slope,
multi-level overlap and 3-D body clearance alone. Reuse MPPI/collision-monitor ideas
where assumptions hold.

### Use only elevation mapping — rejected

A single surface loses overhangs and multi-valued geometry. Pair it with a volume map.

### Use only camera or only LiDAR — rejected

Camera semantics and LiDAR geometry have complementary failure modes. Terrain support,
appearance, time/pose uncertainty and dynamic segmentation benefit from fusion;
proprioception is essential for actual foot interaction.

### Use one universal simulator — rejected

Contact throughput, sensor realism, city diversity, indoor semantics, ROS timing, and
independent physics validation are different strengths. A common adapter and frozen
policy make a heterogeneous ladder meaningful.

### Download a parkour checkpoint and declare success — rejected

Available artifacts are generally Go1-specific, non-commercial, paper-only, depend on
old stacks, or lack a verified Go2 sensor/deployment contract. They remain reference
and possible initialization material only after license/reproducibility audit.

## 10. Recommended phased result and expected evidence

The design sequence in `DESIGN_PLAN.md` deliberately yields incremental value:

1. P0 makes today's planar system safer and makes future results honest.
2. R0/R1 create an articulated, untouched Go2 baseline rather than tuning against an
   invented Parcel policy.
3. R2 makes camera/LiDAR/IMU geometry real and uncertainty-aware.
4. R3 makes routes reflect controller capability and adds explicit stairs/hills logic.
5. R4 adds learned contact performance only after its observations and evaluator exist.
6. R5 catches physics/API overfit in another engine.
7. R6 combines semantic tasks, crowds and terrain without making any one benchmark the
   product goal.

The success claim at the end of simulation is not “the dog will never collide.” It is a
reproducible Pareto improvement in task success, terrain completion, collision/fall/
near-miss exposure, motion quality and latency across frozen in-domain, OOD and cross-
simulator suites, with honest unsupported-terrain behavior and no regression in current
simple commands.

## 11. Research risks still unresolved

- Exact future Go2 hardware/sensor SKU, fields of view, compute target and mounting are
  unknown; simulation contracts must parameterize rather than assume them.
- Unitree Sport's measured stair/slope envelope is unknown until hardware/vendor-specific
  validation; do not guess it from Go2 mechanical ability.
- Learned contact policies can exploit simulator details and fail on compliant/loose or
  reflective/wet terrain despite broad randomization.
- LiDAR/camera failure on glass, water, vegetation, rain/fog/dust and sunlight remains
  incompletely simulated.
- Estimation and terrain mapping can share a failure source; fused maps are not
  statistically independent evidence.
- Dynamic humans are more varied and adversarial than simulator policies.
- A single GPU creates contention among RTX rendering, mapping, semantic perception and
  policy inference; latency isolation must be measured.
- Some promising 2026 repositories are young or license-ambiguous. Pin and audit before
  adoption.
- An evaluator can be gamed by collision taxonomy, tolerance, resets or truth leakage;
  mutation sensitivity and failure replay are mandatory.

## 12. Conclusion

Parcel should continue as a composable Python-first research stack around typed
interfaces, with C++/CUDA/ROS/native simulator components behind process boundaries as
needed. The decisive improvement is not a bigger conversational model. It is converting
the current flat, truth-assisted base into an honest perceptive hierarchy: timestamped
camera/LiDAR/state, uncertain 2.5-D + 3-D maps, capability-aware route/local planning,
isolated learned contact locomotion, and an independent final safety guard.

That architecture preserves the companion goal and simple voice UX while putting
learning exactly where simulation can add the most value before hardware arrives.
