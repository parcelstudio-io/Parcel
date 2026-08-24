# Day 06: Links, Joints, and Degrees of Freedom

## Mental model

A robot’s morphology is a graph: **rigid links** connected by **joints** that allow relative motion. Each independent actuated joint contributes one degree of freedom (DoF) to the configuration. The Go2’s walking body is not a holonomic base with magic wheels — it is **12 actuated joint angles** whose coordinated motion *produces* body velocity through contact.

Configuration space is the space of all joint coordinates (plus floating-base pose when the body can move in the world). Task space is where the feet and body need to be. Most Parcel features speak task-space language (“move forward”, “sit”); the vendor controller maps that into configuration space. Confusing those spaces is how an SE accidentally ships joint-angle authoring into a chat planner.

In Parcel, morphology lives in one place: `RobotProfile` in `src/parcel_robot/robot_profile.py`, selected by `robot.model: go2` in `configs/robot.yaml`.

## Light equations / counting

```text
n_dof_actuated = n_legs × n_joints_per_leg
Go2: 4 × 3 = 12          # RobotProfile.dof
```

Per leg (Unitree-style naming used in Parcel):

```text
hip_joint    → abduction/adduction (leg swings sideways)
thigh_joint  → hip flexion/extension (fore-aft)
calf_joint   → knee flexion/extension (shorten/extend leg)
```

Floating base (unactuated, estimated): position `(x,y,z)` + orientation — the world pose Sport and state estimation fight to control using the 12 actuators.

Link lengths bound reach; profile validation encodes:

```text
|stance_z| < upper_link + lower_link
# go2 defaults: 0.265 < 0.213 + 0.213  ✓
```

## Software-engineering analogy

Joints are like typed ports on a service mesh; the full posture is a 12-dimensional config object. Body velocity commands are a *facade API* that hides the microservice choreography of legs. Calling the facade is correct for Parcel application code. Reaching into each joint from the LLM is like letting a product chatbot issue raw SQL against every shard — unbounded and unsafe.

Porting robots should mean a new profile plus pose YAMLs under `configs/skills/`, not scattering link lengths through kinematics and animation code.

## ASCII diagram

```text
  FL_hip — FL_thigh — FL_calf — foot
  FR_hip — FR_thigh — FR_calf — foot
  RL_hip — RL_thigh — RL_calf — foot
  RR_hip — RR_thigh — RR_calf — foot
           \________ _______/
                    v
              floating base
           (x,y,z, roll,pitch,yaw)

  Parcel application API:  (vx, vy, vyaw)  or named Pose.joints
  Hardware reality:        q ∈ R^12  (+ base pose)
```

## Map to Parcel / Go2

- Defaults: legs `FL, FR, RL, RR`; suffixes `hip_joint`, `thigh_joint`, `calf_joint`; stand angles `(0.0, 0.9, -1.8)` rad; link lengths `0.213 m`; `stance_z_m=-0.265`.
- `motion/gait.py` imports `RobotProfile.go2().stand_joints()` so stand posture is not a second hand-maintained table.
- Skill trajectories such as `configs/skills/trajectories/hop.yaml` list all twelve `*_joint` keys with radian targets; `Pose` in `src/parcel_robot/models.py` carries `joints: dict[str, float]`.
- `SafetyLimits.max_abs_joint_position` in `src/parcel_robot/safety.py` rejects absurd pose tool arguments before they reach a backend.
- Production path: typed body-velocity / pose intents → validation → Unitree Sport → joint controllers. Python must not own 1 kHz joint torque loops (`edu/INTRO.md`, `docs/MOTION.md`).
- `RobotMotionState.joint_positions` exists so a future low-level source can populate joints without changing the high-level contract; Sport’s adapter advertises `low_level_joint_control=False`.

Configuration-space obstacles include joint stops and self-collision; task-space obstacles include people and walls. Both can make a semantic skill infeasible even when the LLM is confident.

## Failure story

A sit trajectory authored in degrees was pasted into a YAML consumed as radians. Thigh targets near `90` instead of `~1.0` commanded absurd configurations in sim; on a bench test with a low-level pose API enabled for debugging, knees slammed toward joint stops. The morphology layer had no semantic “sit” — only numbers. Fix: store radians only, validate joint targets against profile/safety limits before arming any pose mode, and keep pose skills off the Sport velocity lease unless explicitly coordinated (`docs/MOTION.md`).


## Building habit

When adding a pose or trajectory skill, generate joint keys from `RobotProfile.joint_name` / `stand_joints` instead of hand-typing twelve strings—drift between YAML and profile is how legs go missing. Keep all joint angles in radians end-to-end; convert at the UI only. Reject LLM or tool outputs that emit raw joint maps unless they pass `SafetyLimits.max_abs_joint_position` and profile limit checks. Remember task-space feasibility ≠ configuration-space feasibility: a free orbit radius can still ask for an unreachable crouch. For hardware, prefer Sport body-velocity APIs; treat joint lists as sim/expression or future controlled handoff, not casual chat actuators.


Configuration space is also where self-collisions and joint stops live. A trajectory that looks smooth in task-space metres can still bang thigh against calf limits. When you author skills under `configs/skills/`, validate every keyframe against the profile before a human ever arms the robot. Prefer named poses (`Pose`) that the runtime can reason about over anonymous angle blobs from a notebook export.

## Retrieval questions

1. Name the three joints on one Go2 leg and what each primarily does.
2. Why is body-frame `(vx, vy, vyaw)` a better Parcel API than commanding 12 joint angles from the behavior layer?
3. (Day 02) Stand calf angle is `-1.8`. What unit is that, and how would you sanity-check it against a knee nearly folded?

## Optional 10-minute exercise

In `src/parcel_robot/robot_profile.py`, confirm `RobotProfile.go2().dof == 12` and list names via `joint_name`. Diff against keys in `configs/skills/trajectories/hop.yaml` — note any missing leg.
