# Day 31: Typed Hardware and Controller Boundaries

## Mental model

A robot stack is a ladder of *typed contracts*, not a pile of functions that happen to call motors. Each rung may speak only the vocabulary of the rung below it. The LLM speaks intents. The executive speaks skills. Navigation speaks body velocities in a named frame with a timestamp and TTL. The HAL speaks leased setpoints and E-stop. Unitree Sport speaks gait. Motor drivers speak current.

The central invariant for Parcel:

```text
LLM / planner  ↛  joint angles, torques, raw LowCmd, priority overrides
application    →  typed PlanIR / MotionIntent
ControlManager →  TimedVelocitySetpoint + lifecycle + feedback
vendor Sport   →  balance, feet, joints
```

If a layer can emit a symbol the next layer cannot validate, you do not have a boundary—you have a hope.

## Software-engineering analogy

Think of a payment system with PCI boundaries. The web frontend may never construct a raw card-authorization wire format. It emits a typed checkout intent; a vault service validates, rate-limits, and talks to the processor; a hardware HSM holds keys. Replacing the frontend must not redefine the processor API.

Parcel makes the same choice in D1 and D2 of `docs/DESIGN_DECISIONS.md`: model replacement must not redefine the actuator API. `ControlManager` is the sole body-velocity writer on the product path. Viewer hotkeys and direct simulator IPC are explicit debug bypasses—useful, but not the product contract.

**Tradeoff:** strict schemas reject creative or novel motions early. That is the point. Novel behavior must enter as a new admitted skill with tests, not as a freer string that reaches Sport.

## Light equations (boundary admissibility)

A setpoint is admissible only when all hold:

```text
finite(vx, vy, vyaw)
|vx| ≤ max_vx,  |vy| ≤ max_vy,  |vyaw| ≤ max_vyaw
age(cmd) = t_now − t_stamp  <  command_timeout
frame ∈ allowed_frames
capability(cmd) ⊆ controller.capabilities
¬emergency_latched
```

Fail any clause → refuse or stop. Do not “best-effort clamp and hope.” Clamping without a reason code hides who asked for an illegal act.

## ASCII diagram

```text
  voice/text → PlanIR (skills, args, success predicates)
                    |
                    v
           validator + executive
                    |
                    v
     navigation / follow / manual  →  MotionIntent (priority, TTL)
                    |
                    v
          CommandArbiter + reactive_safety veto
                    |
                    v
     jerk-shaped VelocityCommand → ControlManager (single writer)
                    |
                    v
        LocomotionController HAL  →  SimulatorBackend | Unitree Sport
                    |
                    v
              motors / encoders / IMU   (vendor-private)
```

## Map to Parcel / Go2

From `edu/INTRO.md`, `DESIGN_DECISIONS.md` (D1–D2, D10), and `src/parcel_robot/control/`:

- `PlanIR` forbids raw velocity, joint, torque, priority, and `force` fields. The model proposes semantic steps; deterministic code compiles them.
- `LocomotionController` in `control/base.py` is a Protocol: `activate` (passive), `update(TimedVelocitySetpoint, RobotMotionState)`, `stop`, `emergency_stop`. Implementations must serialize vendor I/O and remain safe if `update` races a stop.
- `ControlLimits` defaults roughly `vx ≤ 0.6`, `vy ≤ 0.4`, `vyaw ≤ 1.0`—last-line physical clamps, not “comfort preferences.”
- `ControlTiming.command_timeout_s` (~0.35 s) means a dead publisher decays to stop even if nobody cancels politely.
- `ControllerCapabilities` advertise what a backend can do; the manager must not ask Sport for a mode it does not expose.
- Python ~10 Hz owns behavior; Sport owns ~balance/gait. Parcel must never close a joint-torque loop from the LLM process.

**Design choice:** keep Python for orchestration (D10) and push hard real-time into vendor/native processes. Cost: GIL/GC can hurt tails; benefit: iteration speed and a clear process kill → safe decay story.

**Codebase anchors (HAL / typed boundary):**

- `brain/contracts.py` → `PlanIR` — closed skill steps; validator rejects forbidden motor-ish keys (`brain/validator.py` → `_reject_forbidden_argument_keys`).
- `core/commands.py` → `MotionIntent(command, source, ttl=0.35)` with `SOURCE_PRIORITIES` — application lease, not a joint API.
- `control/models.py` → `TimedVelocitySetpoint` (`issued_at`, `valid_until`, `frame="base_link"`, `expired()`); `ControlLimits.validate`; `ControlLifecycle`.
- `control/base.py` → `LocomotionController` / `RobotStateSource` Protocols; `control/manager.py` → `ControlManager` sole writer (`self.limits.validate(command)` before delivery).
- `control/adapters.py` → `BackendVelocityController`; `control/unitree_sport.py` → `UnitreeSportController` — Sport behind the same HAL.
- `backends/base.py` → `SimulatorBackend` Protocol (`observe`/`move`/`stop`) — sim/hardware seam without exposing torques upward.

## Failure story

A prototype “helpful” planner emitted JSON that included `"vx": 1.2` “just this once” for a sprint across a plaza. The schema was loosened to `dict` “temporarily.” A hallucinated lateral dodge of `vy = 2.0` reached the simulator kinematic base and looked fine; on a physical Go2 the same number would have been an out-of-envelope request into Sport. Worse, a later model swap reused the loose schema and started stuffing joint targets into `arguments`. The bug was not the model—it was the missing type boundary. Fix: restore closed PlanIR, validate at the executive, and keep `ControlLimits.validate` inside `ControlManager` as a second wall that never trusts upstream politeness.

## Retrieval questions

1. Why must an LLM never emit joint torque even if the vendor SDK allows `LowCmd`?
2. List four fields a leased body-velocity command needs besides `{vx, vy, vyaw}` (think stamp, TTL/timeout, frame, source/priority, capabilities).
3. (Week-back) How does “commanded ≠ measured ≠ actual” from Day 01 justify stop-confirmation via `RobotStateSource` sequence numbers rather than RPC success alone?

## Optional 10-minute exercise

Read `control/base.py` and `control/models.py`. Write a one-page “authority matrix”: for LLM, executive, `CommandArbiter`, `reactive_safety`, `ControlManager`, and Sport, mark each as **propose / admit / veto / write / execute**. Note one debug path that bypasses the matrix and what production gate must forbid it on hardware.
