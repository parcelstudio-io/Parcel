# Day 10: Synthesis — One Command Through the Physical Chain

## Mental model

Trace one spoken command through Parcel until feet push the ground — and classify **every value** as command, ack, measurement, estimate, or belief. If you cannot classify a wire field, you do not yet understand that hop.

Worked intent: *“Walk in a small circle around me, then sit.”* (`edu/INTRO.md`). Structured meaning first; motors last. Module 1’s topics are not a quiz list — they are the checklist you apply at each hop: units, energy, morphology, sensing modality, and state kind.

The SE takeaway: success is a **predicate on measured/estimated state under budgets**, not a log that a message was sent.

## Software-engineering analogy

This is a request through API gateway → workflow engine → admission control → sidecar policy → leased worker → machine. Each hop has a schema, a TTL, and a failure mode. The LLM is an untrusted planner; deterministic layers validate before physics — the same separation argued in `edu/INTRO.md` and the authority ladder in `docs/MOTION.md`.

## Light equations (budget check, not a controller)

```text
v ≲ max_vx                 # configs/robot.yaml motion.max_vx
ω ≲ max_vyaw
d_stop ≈ v² / (2 a_decel)  # smoothing / shaping decelerations
age_track < heading_stale_after_s
age_state < state_timeout_s
E_draw ~ P_avg * duration  # battery SoC must cover the bit
CoM recoverable under gait + yaw demand   # Day 04 qualitative gate
```

If any budget fails, the physical chain should inhibit — not “try the orbit anyway.”

## ASCII diagram

```text
audio → ASR → LLM belief
           ↓
    typed task (circle_entity + pose sit)
           ↓
    validator / executive / arbiter     [belief → command candidate]
           ↓
    nav trajectory in metric frames     [estimate owner + free space]
           ↓
    VelocitySmoother / SCurve / gates   [shaped command]
           ↓
    ControlManager TimedVelocitySetpoint [leased command]
           ↓
    Unitree Sport → motors/gearing      [vendor cmd / electrical]
           ↓
    feet → forces → body motion         [actual]
           ↑
    encoders/IMU → RobotMotionState     [measured]
    camera/LiDAR → SimObservation       [measured → tracks/estimates]
```

## Map to Parcel / Go2 (end-to-end)

1. **Speech / intent** — duplex/voice stack produces text; reasoner emits structured actions (not torques). PlanIR / skill names validated in `src/parcel_robot/brain/validator.py`.
2. **Behavior** — orbit knobs from `spatial_behaviors` (`default_orbit_radius_m`, clearances) in `configs/robot.yaml`; owner estimate from exteroception (`SimObservation.owner`, LiDAR/camera tracks).
3. **Arbitration** — `CommandArbiter` (`src/parcel_robot/core/arbiter.py`) picks one motion source by priority/TTL (`docs/MOTION.md`).
4. **Shaping & safety** — `VelocitySmoother` (`core/velocity_smoother.py`), collision/TTC gates, `SCurveVelocityShaper` (`navigation/velocity_shaping.py`).
5. **Control boundary** — `ControlManager` publishes leased `TimedVelocitySetpoint` (`vx,vy,vyaw` in `base_link`); watches `RobotMotionState` age, tilt (`max_tilt_rad`), faults (`POWER`/`COMMS`/`TILT`).
6. **Actuation** — Sport (`control/unitree_sport.py`, `ControllerCapabilities.low_level_joint_control=False`) closes gait/balance; 12 geared actuators move links (`RobotProfile` naming in `robot_profile.py`).
7. **Energy/heat** — `BatteryStateSnapshot` / `FaultReason.POWER` can abort before the sit (`configs/robot.yaml` `battery:`).
8. **Sit** — named pose / skill after navigation completes and velocity stop is confirmed (`stop_confirmed`, settled measured speeds). Pose path must not fight an active velocity lease (`docs/MOTION.md`).
9. **Completion** — success from measured/estimated predicates (owner-relative geometry, posture), never from “we emitted N commands.”

Classify examples:

| Value | Kind |
| --- | --- |
| LLM “user wants orbit” | belief |
| `circle_entity` args | command (semantic) |
| `VelocityCommand(vx=…)` | commanded |
| Sport RPC OK | acked |
| `RobotMotionState.velocity` | measured |
| owner track pose | estimated |
| body on the floor | actual (unobserved directly) |

## Failure story

The stack marked the orbit done when the yaw integrator in navigation reached 2π, then commanded sit. Measured yaw from `RobotMotionState` had lagged on carpet slip; the dog sat after a partial arc beside a bench. Multi-hop “success” used the wrong state kind at the behavior boundary. Fix: completion couples odometry/IMU yaw *and* owner-bearing change from LiDAR/camera, with timeout fallback to replan — Day 01 rules at system scale.


## Building habit

For every new companion skill, draw the chain from belief to feet and tag each hop’s state kind before writing code. Put completion predicates next to the hop that can observe them—usually `RobotMotionState` + `SimObservation`, never the LLM turn that requested the skill. Re-read `docs/MOTION.md` whenever you add a second way to move the body; split-brain writers are how Module 1 lessons get rediscovered the hard way. Keep a demo checklist: units/frames commissioned, speed/stop budgets, tilt gate live, battery policy exercised, Sport lease healthy, owner-track freshness OK. If any box is yellow, the dog stays on the stand.

Module 1 complete means you can narrate one voice command through energy, joints, motors, proprioception, and exteroception without confusing commanded with actual. Modules 2+ will add clocks, geometry, and control math on top of this spine—not instead of it.

## Retrieval questions

1. Pick three hops in the chain above and label the primary state kind each hop should trust for *go/no-go*.
2. Where does Parcel’s Python authority end for this command, and which config/doc states that?
3. (Days 03–05) Name one linear, one rotational/balance, and one power reason to abort the orbit early.

## Optional 10-minute exercise

Read the authority diagram at the top of `docs/MOTION.md`. On paper, write the orbit command beside each box and tag `cmd/ack/meas/est/belief`. Star any box where your tag was previously wrong. Optionally open `configs/robot.yaml` and list the numeric budgets you would check before arming the demo.
