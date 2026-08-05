# Day 15: Forward and Inverse Kinematics

## Mental model

Kinematics asks *where* bodies are, not *why* they move (that is dynamics).

- **Forward kinematics (FK):** joint angles → foot (or tool) pose in a body or world frame. For one Go2 leg with hip abduction, hip flexion, and knee, FK is a short chain of SE(3)/planar transforms along the links.
- **Inverse kinematics (IK):** desired foot pose → joint angles. Often multiple solutions (knee bent vs stretched), or none (unreachable). Numerical IK iterates; analytical IK uses geometry of the specific leg.

Configuration space \(q \in \mathbb{R}^{12}\) for the Go2’s twelve actuated joints. Task space for one foot is typically a 3D point (or a pose). Locomotion repeatedly solves “put this foot here while the body moves like that.”

With Unitree Sport, Parcel does **not** run leg IK. Sport owns foot placement. Parcel must still understand FK/IK so it never asks the wrong layer for joint miracles, and so a future custom controller has a clear boundary.

## Software-engineering analogy

FK is a pure function from internal state to a public DTO. IK is searching for preimage under constraints — like resolving a desired API response into database rows that satisfy unique indexes and foreign keys. Multiple valid row sets = redundant IK; no valid set = unreachable goal. Caching the last IK solution is warm-start; jumping to a distant seed can flip to another local minimum (wrong knee bend) — a logic bug that looks like a random twitch.

## Light equations

Serial chain (sketch):

```text
T_base_foot(q) = T_base_hip T_hip_thigh(q1) T_thigh_shank(q2) T_shank_foot(q3)
p_foot = translation(T_base_foot)
```

IK feasibility:

```text
find q  s.t.  FK(q) ≈ p_des,   q_min ≤ q ≤ q_max
```

If \(\|p_{des} - p_{hip}\|\) exceeds leg length, no solution exists — fail closed, do not clamp silently into a stretched singularity.

## ASCII diagram

```text
body (base_link)
   |
   +-- hip abduct  -- hip flex -- knee -- foot   } ×4 legs
   |         q1           q2       q3
   |
   FK:  q ------------------> foot points in base_link
   IK:  desired footholds --> q (or "unreachable")

Parcel today:  VelocityCommand(vx,vy,vyaw) --> Sport (internal IK/gait)
Future custom: same VelocityCommand --> your estimator + IK + joint loop
```

## Map to Parcel / Go2

**Codebase anchors (kinematics boundary):**

- Go2 morphology: 12 DoF (Day 06); `edu/INTRO.md` hip abduct/flex + knee per leg.
- Product motion DTO is `VelocityCommand`, not joint angles (`src/parcel_robot/models.py`). `Pose` exists for named postures (`name`, `joints` dict) used by sim/skills — not as LLM→motor authority on hardware.
- `RobotMotionState.joint_positions` / `joint_velocities` are optional fields for a future low-level source; `UnitreeSportStateSource` currently fills pose, rpy, body velocity, `foot_forces`, mode/error — not a full joint FK pipeline in Parcel Python.
- `ControllerCapabilities.high_level_balance=True`, `low_level_joint_control=False` on `UnitreeSportController` (`unitree_sport.py`): Sport owns balance/gait/IK.
- `RobotRuntime._run_pose` / `_run_trajectory`: on physical (non-sync) control, stop and raise that poses/trajectories must be implemented by the selected locomotion controller (`runtime.py`); `docs/MOTION.md` same rule.
- Custom controller sketch in `docs/MOTION.md`: same leased body-velocity in, private high-rate FK/IK/joint loop out — never expose `LowCmd` beside active Sport.


## Why builders care

Senior SE instinct is to “just solve for the joints.” On Parcel that instinct is a safety smell unless you are writing a commissioned custom controller behind `LocomotionController`. Your job in the companion stack is to keep task space (owner, path, body twist) well-posed and leave leg IK to Sport—or to a future native module that exclusively owns actuators. Knowing FK/IK lets you review PRs that accidentally grow a second motor writer, and to specify foothold interfaces later without leaking them into the LLM.

When reading `Pose.joints` in skills, ask: is this sim-only choreography, or a hardware path? Physical `_run_pose` already answers for the Sport-era runtime: stop locomotion and reject direct backend actuation.

Workspace reminder: body velocity can request a motion whose internal footholds are awkward (tight spins on low friction). That is not an IK bug in Parcel; it is a command envelope / behavior issue—tighten `ControlLimits` and planner caps before inventing joint overrides.

## Failure story

A demo skill mapped “sit” to a fixed joint vector copied from a simulator screenshot and published beside Sport velocity. Sport and the pose publisher fought: legs stiffened mid-gait, error codes spiked, and `ControlManager` faulted. The kinematics were “valid” as a static pose and illegal as a concurrent command path. Fix: one actuator owner; posture transitions are controller-owned actions with a confirmed handoff, or vendor APIs commissioned separately — never a second writer inventing IK in the skill layer.

## Retrieval questions

1. What does FK compute from what inputs? What does IK attempt?
2. Why can a kinematically reachable foot target still be the wrong thing to command from Parcel’s Python brain?
3. (From Day 06) How many actuated joints does the Go2 have, and which Parcel type is the supported physical motion contract today?

## Optional 10-minute exercise

Open `src/parcel_robot/control/base.py` and `unitree_sport.py`. Note `LocomotionController.update(TimedVelocitySetpoint, ...)` versus any joint API (there should be none on Sport). Skim `RobotRuntime._run_pose` and write one sentence on how physical pose requests fail closed.
