# Sprint 2026-08-09 · task_7 — perceptive all-terrain navigation program

**Status:** independent research and design complete; ready for Claude Fable audit;
implementation, model downloads, and training are intentionally not started

**Owner ask:** keep the existing simple voice-command path, leave full-duplex audio
out of scope, and make Parcel learn collision-averse navigation from camera, LiDAR,
IMU, odometry, and proprioception in simulated indoor, city, stair, hill, and rough-
terrain environments before physical hardware exists.

## Decision

Parcel should not replace its whole navigation stack with one end-to-end model and
should not pretend that the present MuJoCo city rig can train a quadruped to use
stairs. Build a **hierarchical perceptive-navigation stack** with two independent,
testable learning problems:

1. **Navigation:** camera + depth/3-D LiDAR + state estimation produce uncertain
   2.5-D elevation/traversability and 3-D clearance maps; a capability-aware global
   route planner and terrain-aware local MPPI/lattice controller choose a safe body
   trajectory.
2. **Locomotion:** Unitree Sport remains the flat/mild-terrain baseline. In parallel,
   reproduce Unitree's official Go2 rough-terrain PPO baseline in Isaac Lab, then
   train a privileged-teacher/noisy-student controller for slopes and stairs behind
   Parcel's existing replaceable `LocomotionController` boundary.

The learned components may estimate terrain, propose routes, or produce joint targets
inside the experimental locomotion process. They do **not** own the final collision,
drop-off, stability, freshness, or stop decision. A deterministic post-shaper safety
admission layer sees fresh raw geometry and robot state and can assert exact hold.

No finite simulation campaign can establish collision-free behavior in *any*
environment. The release claim must be: performance over a versioned operational
design domain (ODD), held-out generator/asset/physics/sensor splits, and frozen
cross-simulator tests, with explicit fail-safe behavior outside that evidence.

## Why this is the independent recommendation

The updated code audit found a useful but flat-world system:

- `grid_v1` is a deterministic rolling 2-D occupancy grid, A*, and rotate-first /
  forward tracker; autonomous lateral travel is currently zero.
- simulated LiDAR is real MuJoCo ray casting, but it is one horizontal 2-D scan;
- runtime pose is exact simulator truth, not SLAM or LiDAR-inertial odometry;
- semantic candidates are MJCF geometry truth with a camera-like label, not pixels;
- the camera channel can render synchronized RGB/depth and concurrent Task 4 work adds
  calibrated pixel/depth localization, but it is still not mission-wired;
- the headless and UI bases directly overwrite planar position/yaw; legs use an
  open-loop visual gait, so there is no contact-dynamic stair, slope, slip, or fall;
- the MetaUrban and RL paths are scaffolds, not active trained policies; and
- the Unitree Sport adapter is a strong future hardware seam but is uncommissioned.

These facts make the current harness valuable for fast semantic and planar navigation
regression, but they also make a separate articulated-physics terrain program
non-negotiable. Full evidence and line-level references are in
[RESEARCH_REPORT.md](RESEARCH_REPORT.md).

## Binding scope

### In scope

- camera, depth/3-D LiDAR, IMU, joint state, contact/foot force, and odometry contracts;
- time synchronization, calibration epochs, uncertainty, coverage, and health;
- localization, 2.5-D elevation/traversability, 3-D occupancy/ESDF, dynamic tracks;
- capability-aware multi-level routing and predictive terrain-aware local control;
- stair, curb, ramp, hill, rough-ground, negative-obstacle, and overhang handling;
- a replaceable vendor/learned locomotion boundary and teacher-student RL;
- Isaac Lab training, MuJoCo sim-to-sim, dynamic-city/indoor sidecars, and evaluation;
- deterministic final safety, failure recovery, latency, and artifact provenance.

### Explicitly out of scope

- full-duplex speech, new audio models, microphones, and conversational redesign;
- a runtime LLM/VLM in a hard real-time motion loop;
- a monolithic language-to-joint or pixels-to-joints companion policy;
- downloading weights or starting long training before contracts and baselines pass;
- claiming sim-to-real safety, certified functional safety, or universal navigation;
- deleting the current MuJoCo city, `grid_v1`, voice command compiler, or Unitree Sport
  controller; they remain baselines and regression surfaces.

The existing voice path may compile a short utterance into a validated semantic task or
goal. After that boundary, terrain planning is identical to a UI/manual request. Voice
never emits joint commands, terrain modes, safety priority, or arrival truth.

Camera/depth and LiDAR remain the robot's external-environment sensors. IMU, encoders,
contacts and odometry are internal body-state feedback needed for closed-loop balance
and localization; they are not new external knowledge sources. A future online map may
propose a coarse route, but it remains a placeholder and can never assert local free
space, traversability, collision clearance, or task completion.

## Target system

```text
simple voice/text/UI command
            |
     TaskRequestV1 / goal region
            |
 camera + depth/3-D LiDAR + IMU + odom + joints/contacts
            |
 timestamped state estimator + sensor health / calibration
            |
  local 2.5-D elevation map + 3-D occupancy/ESDF
  semantics + dynamic tracks + uncertainty / unknown space
            |
 capability-aware global / multi-floor terrain route
            |
 terrain local controller (MPPI first, learned challenger in shadow)
            |
 LocomotionCommandV1: desired body trajectory/twist + gait hint
            |
 Unitree Sport baseline OR isolated learned Go2 controller
            |
 FINAL raw-sensor + stability MotionAdmissionV1
            |
        ControlManager / simulator or robot

Simulator truth --------------------------> evaluator only
Privileged terrain/physics ---------------> teacher only during training
```

The complete algorithms, interfaces, loop rates, state machines, and phase gates are in
[DESIGN_PLAN.md](DESIGN_PLAN.md). Primary sources, licenses, availability, and adoption
rulings are recorded in [SOURCE_LEDGER.md](SOURCE_LEDGER.md).

## Execution sequence

| phase | deliverable | hard promotion gate | parallel work |
|---|---|---|---|
| P0 | honest sensor/frame/capability contracts; truth isolation; final exact-hold safety | missing/stale/skewed geometry cannot translate; no post-veto re-expansion; truth-leak mutants fail | contracts, eval manifests, Isaac environment bootstrap |
| R0 | freeze current flat regressions and add articulated terrain smoke scenarios | current T0/grid/follow baselines stay unchanged; articulated Go2 stands, receives a leased body command, and reports contacts | P0 safety + scenario generation |
| R1 | reproduce official Unitree/Isaac Go2 rough-terrain PPO baseline | pinned upstream commit/config; seeded flat/rough/slopes/stairs results and artifact hash; no Parcel tuning yet | mapper prototype + metric implementation |
| R2 | synchronized sensor fusion and uncertain elevation/3-D map | held-out elevation/traversability/drop-off/overhang metrics; no sim truth in deployable observations | student policy + planner baseline |
| R3 | capability-aware route planner, stair/hill state machine, terrain MPPI | every commanded segment lies within a versioned capability envelope; stair up/down and hills pass separately | student distillation + cross-sim adapter |
| R4 | noisy-student locomotion and proprioceptive fallback | sensor delay/dropout/OOD physics gates; no regression to vendor/teacher baseline; policy-time deadlines | dynamic-city integration |
| R5 | frozen-policy Isaac → Unitree MuJoCo and ROS/timing cross-sim | no target-simulator tuning; no new safety-failure class; exact same action/sensor schema | semantic/urban composite scenarios |
| R6 | indoor/city composite and external terrain evaluations | paired held-out seeds, confidence intervals, immutable ledger, failure replays; release thresholds ratified from baseline | documentation + hardware-readiness checklist |

## Work that can proceed in parallel

After P0 freezes frames, clocks, sensor/action schemas, and evaluator-only truth, five
workstreams can run concurrently:

1. **Simulation/locomotion:** Isaac Lab + Unitree RL Lab reproduction, curricula,
   distillation, ONNX/TorchScript export, Unitree MuJoCo sim-to-sim.
2. **Perception/state:** camera–LiDAR–IMU joins, pose estimation, elevation/3-D maps,
   traversability uncertainty, dynamic masking.
3. **Navigation:** capability graph, terrain route planner, MPPI critics, stair/hill
   state machines, recovery and fallback.
4. **Safety/evaluation:** raw-sensor shield, stability monitor, manifests, metrics,
   mutation tests, replay, ledger and promotion reports.
5. **World diversity:** procedural terrain, indoor assets, dynamic people, composite
   missions, sensor/physics randomization and cross-simulator adapters.

Task 4's pixels-to-detection/semantic-lock-on work supplies semantic observations to
this task. Task 7 must not duplicate it or wait for it: geometry-only terrain training
and contact dynamics can proceed while semantic perception is developed.

## First dispatchable cards after audit approval

1. **T7-P0A — truth and frame contract:** introduce the simulator-neutral envelopes and
   prove policy inputs cannot contain evaluator truth.
2. **T7-P0B — final safety ordering:** implement typed post-shaper `MotionAdmissionV1`,
   exact hold, fresh required geometry, negative-obstacle and stability dispositions.
3. **T7-E0 — terrain eval kernel:** scenario manifest, collision/contact taxonomy,
   fixed seeds, metrics, replay and append-only ledger before tuning.
4. **T7-S0 — isolated Isaac stack:** supported Python/container, pinned Isaac Lab,
   Unitree RL Lab and RSL-RL; do not alter the desktop's Python 3.14 environment.
5. **T7-L0 — upstream reproduction:** reproduce the official Go2 rough policy exactly
   and record the untouched baseline before Parcel-specific rewards or sensors.
6. **T7-M0 — elevation-map spike:** fuse depth/3-D LiDAR into an uncertain local map
   behind a ROS-neutral interface; compare Elevation Mapping CuPy and nvblox roles.

Do not dispatch R3+ learning/model work until the corresponding evaluator mutation
panel is demonstrably sensitive to collisions, falls, drop-offs, truth leakage,
sensor staleness, and false completion.

## Owner decisions after the audit

1. Approve Isaac Lab as the primary articulated training engine, Unitree MuJoCo as the
   independent sim-to-sim gate, and current MuJoCo city as the fast regression engine.
2. Approve the vendor-first controller policy: Unitree Sport on its validated terrain;
   learned low-level control is opt-in and cannot silently replace it.
3. Approve the initial map pair: local multimodal elevation map for foothold/terrain
   feasibility plus 3-D occupancy/ESDF for overhang and body clearance.
4. Ratify the initial ODD and numerical promotion thresholds after the untouched R1
   baseline is measured; values in the design are proposed gates, not achieved claims.

## Claude Fable review handoff

Claude Fable is assigned the next action: independently audit this task before any
implementation. The ready-to-run review brief is
[CLAUDE_FABLE_AUDIT.md](CLAUDE_FABLE_AUDIT.md). The reviewer must create
`CLAUDE_FABLE_REVIEW.md` in this directory with a verdict of `APPROVE`, `REVISE`, or
`REJECT`, source-backed corrections, code-linked blockers, and a red-team assessment.
The audit is read-only unless the owner separately authorizes implementation.
