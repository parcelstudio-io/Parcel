# Day 07: Motors, Gearing, and Actuator Modes

## Mental model

Each Go2 joint is an **actuator package**: brushless DC (BLDC) motor + gear reduction + encoder + current sensing + motor driver. Software at different layers speaks different dialects to that package:

- **Position mode**: move toward an angle `q_des`
- **Velocity mode**: regulate joint rate `q̇_des`
- **Torque / effort mode**: apply rotational force `τ_des` (often via current)

Gearing trades motor speed for output torque and usually adds backlash and reflected inertia. Compliance (intentional softness or gearbox springiness) changes how contact feels — useful for terrain, dangerous if your controller assumed a rigid transmission.

Parcel’s companion stack should almost always stop at **body-velocity or carefully owned named poses** to Unitree Sport, not reinvent field-oriented current control in Python.

The contract is explicit: `LocomotionController` in `src/parcel_robot/control/base.py` plus `ControllerCapabilities` (`high_level_balance=True`, `low_level_joint_control=False` on Sport in `control/unitree_sport.py`).

## Light equations

```text
τ_out ≈ N * τ_motor     # gear ratio N (ideal)
ω_out ≈ ω_motor / N
P ≈ τ_out * ω_out ≈ τ_motor * ω_motor   # power (ideal)
τ ~ k_t * I_motor       # current↔torque proxy (model-dependent)
```

Backlash: a deadband in `q` when reversing direction — encoder at the motor may not equal load angle. Stretchy transmissions make “position reached” false even when motor ticks look good (Day 01 state split). Heat is the integral of losses: chatter and stalled high-current holds cook gearboxes even when the trajectory “looks fine” in logs.

## Software-engineering analogy

Motor drivers are firmware microservices with strict SLAs (kHz loops). Sport is an orchestrator exposing a coarse API (`vx, vy, vyaw`, mode changes). Parcel is a product BFF. Implementing torque PD in Python at 10–50 Hz is like running a DB storage engine in the API gateway — wrong latency domain, wrong failure domain.

Actuator mode switches are schema migrations: do them under an explicit lifecycle (`ControlLifecycle`: `DISARMED` → `ARMING` → `IDLE`/`ACTIVE` in `control/manager.py` / `control/models.py`), never mid-flight from a chat intent. Two writers on one gearbox is split-brain.

## ASCII diagram

```text
  Parcel VelocityCommand / TimedVelocitySetpoint
                 │
                 v
          ControlManager (lease, limits, E-stop)
                 │
                 v
          Unitree Sport (gait / balance)
                 │
                 v
     per-joint mode: pos / vel / τ   (vendor-owned schedule)
                 │
                 v
  ┌──────────────────────────────────┐
  │ driver → BLDC → gearbox → joint  │
  │    ^        ^        ^           │
  │  current  encoder  load/foot     │
  └──────────────────────────────────┘
```

## Map to Parcel / Go2

- Authority ladder in `docs/MOTION.md`: behaviors propose; `CommandArbiter` (`src/parcel_robot/core/arbiter.py`) picks; smoothers/gates shape; `ControlManager` is the exclusive velocity writer; Sport owns feet/motors.
- `configs/robot.yaml` → `control.controller` (`simulator` for the browser stack; unitree path constructed by commissioning tools) and `control.unitree_sport` (`state_topic: rt/sportmodestate`, `allowed_modes`, `lateral_sign`, `yaw_sign`). Empty `allowed_modes` fails closed until commissioned.
- Simulator pose/trajectory channels are separate from the velocity lease; the physical runtime rejects whole-body joint handoff that is not controller-owned (`docs/MOTION.md`).
- `SafetyLimits` clamps tool-level `set_velocity` and pose joint magnitudes (`src/parcel_robot/safety.py`) before anything reaches actuators.
- Reality gap: MuJoCo may look perfect while backlash, thermal foldback, and grass slip disagree.

When debugging “won’t walk,” ask: mode armed? lifecycle active? setpoint fresh within `command_timeout_s`? thermal/power derate? — before retuning navigation gains.

## Failure story

A prototype bypassed Sport and streamed position targets from a Python PD loop at ~50 Hz “to get more control.” Latency jitter and a missing contact model caused high-frequency torque chatter; a calf gearbox overheated and tripped. The SE instinct (“I can close the loop myself”) ignored gearing thermal limits and the vendor’s current controller. Rollback to Sport velocity mode restored stability. Lesson: custom joint authority is a research project with a support stand, not a weekend flag on a companion dog.


## Building habit

Debug locomotion bottom-up: lifecycle and lease (`ControlManager`), then Sport mode allow-list (`control.unitree_sport.allowed_modes`), then thermal/power faults, then navigation gains. Do not “just close a PD loop” on geared joints from the Parcel brain—wrong timescale and wrong ownership. Commission axis signs and velocity frames before claiming the dog is tuned. When enabling any pose path on hardware, require an explicit ownership handoff after velocity stop confirmation. Review `LocomotionController` invariants on every adapter PR: `activate` passive, `stop`/`emergency_stop` safe during in-flight `update`, I/O bounded. Gearboxes fail from chatter and stalls, not from mean tracking error looking small.


Power and heat couple directly to mode choice: holding a static pose against gravity in a high-ratio joint draws continuous current even when `ω≈0`. That is why “just freeze the joints” is not a free pause. Prefer Sport’s idle/stand modes and Parcel’s leased zero velocity with stop confirmation over inventing a custom hold-torque from the application layer. Document commissioning of `allowed_modes` before any public demo claims Sport authority.

## Retrieval questions

1. Ideal gearing: if `N` increases, what happens to output torque and output speed?
2. Why is commanding joint torque from the LLM/behavior layer a layering violation given `ControllerCapabilities`?
3. (Day 06) How many actuator packages does a Go2 walk with, and which naming pattern does `RobotProfile` use?

## Optional 10-minute exercise

Read the `LocomotionController` docstring in `src/parcel_robot/control/base.py`. List three invariants (`stop` during `update`, passive `activate`, bounded I/O). For each, write one failure mode if broken on a geared BLDC joint.
