# Day 19: State-Space and Constrained Control

## Mental model

PID looks at one error channel. **State-space** thinks in vectors:

```text
ẋ = A x + B u
y = C x + D u
```

Linearization: real robots are nonlinear; you approximate about a trim (standing, steady walk). **Controllability** asks whether \(u\) can drive \(x\) between states; **observability** whether \(y\) reveals \(x\).

**LQR** picks \(u = -K x\) to minimize a quadratic cost on state error and effort — a principled multi-input PID cousin. **MPC / trajectory optimization** repeatedly solves a short-horizon constrained problem: stay in friction/tilt/velocity limits while tracking a reference. Constraints are first-class, not afterthought clips.

Cascaded controllers assign each timescale a model and authority (Days 11, 18, 20). Parcel’s production choice: constrained *supervision* and shaping in Python; constrained *locomotion MPC/RL* inside Sport (opaque) or a future native custom controller — not an LLM-in-the-loop QP.

## Software-engineering analogy

State-space is a typed system model: \(x\) is the durable entity, \(u\) the command API, \(y\) the metrics you can scrape. LQR is an autoscaler that jointly weights SLO error and cost. MPC is an online planner with a reservation system: every tick it re-plans under quotas (CPU, rate limits) and commits only the first action — exactly receding-horizon scheduling. Violating constraints is OOM-kill, not “best effort 200.”

## Light equations

Discrete LQR intuition:

```text
min Σ (xᵀ Q x + uᵀ R u)
u = -K x
```

MPC sketch:

```text
min_{u_0..u_H}  tracking + effort
s.t.  x_{k+1} = f(x_k, u_k)
      u ∈ U,  x ∈ X     (velocity, tilt, friction proxies, ...)
apply u_0; replan next tick
```

## ASCII diagram

```text
        reference trajectory
                 |
                 v
        +------------------+
        |  MPC / policy    |  s.t. constraints X,U
        +--------+---------+
                 | u
                 v
              plant x  ---- sensors ----> y ---- estimator ----> x̂
                 ^
                 |  (Sport internal; Parcel does not solve this QP)

Parcel constraints (outer):
  ControlLimits, shaping, TTLs, proximity/TTC, E-stop latch
```

## Map to Parcel / Go2

**Codebase anchors (constraints & cascade, not an MPC solver):**

- Hard envelopes: `ControlLimits` (`max_vx/vy/vyaw`, `max_tilt_rad`) validated on setpoints (`control/models.py`); manager tilt/fault checks (`manager.py`).
- Time constraints: `TimedVelocitySetpoint.valid_until`, `ControlTiming` timeouts — temporal “state constraints.”
- Priority/TTL arbitration: `CommandArbiter` (`src/parcel_robot/core/arbiter.py`) + runtime collision/TTC gates — constrained command selection, not optimal control.
- `docs/MOTION.md`: nested loops; Sport absorbs high-rate constrained balance; Parcel does not claim MPC at the Sport layer.
- Custom locomotion path: replace Sport only with a controller that privately runs estimator + constrained whole-body/gait optimization behind the same `LocomotionController` interface (`control/base.py`).
- UNVERIFIED: exact onboard Unitree algorithm (MPC vs RL vs hybrid) — treat as opaque; design to the `Move` + `SportModeState` contract.


## Why builders care

Constrained control is how you say “no” in physics. Parcel already says no with limits, TTLs, tilt faults, and collision gates—the vocabulary of MPC without the solver. When someone proposes “just run MPC in the brain,” translate the request into: which states, which constraints, which Hz, which process, which exclusive writer, what happens on solver timeout. If those answers are vague, the proposal is not production-ready.

LQR/MPC literacy still helps you read papers and Unitree-era research, and to design the *interface* of a future custom gait module so QPs cannot bypass `ControlManager`.

Observability link to Module 3: if a state is not observable from Sport telemetry plus camera/LiDAR, do not pretend MPC can regulate it. Controllability link: body-velocity authority cannot create arbitrary CoM wrenches on ice—constraints must include environment uncertainty, not only actuator U.

For Parcel now, the practical “cost matrices” are product choices: how hard we decelerate near people (TTC), how short leases are, how small max tilt is. Write them down as if they were Q and R.

When constraints conflict (follow vs proximity), priority must be explicit—`CommandArbiter` and safety latch, not an implicit soft cost.

Keep the mental model crisp: equations guide reviews; code and commissioning make them real.

## Failure story

A research spike ran a toy MPC in the runtime process at “best effort” 15 Hz with a 20-step horizon, allocating from the same GIL as ASR. When the solver overrun, it published the last \(u\) without refreshing the lease logic consistently; `ControlManager` and MPC disagreed about authority during a stop. The dog braked late. Fix: any real MPC/gait optimizer gets a dedicated real-time process, bounded solve time, and the same exclusive-writer contract as Sport — never a best-effort co-tenant of conversation.

## Retrieval questions

1. What do \(x\), \(u\), and \(y\) represent in a locomotion state-space model?
2. How does MPC differ from LQR in its handling of constraints?
3. (From Day 18) Which Parcel components enforce constraints without being an MPC solver?

## Optional 10-minute exercise

Skim `ControlLimits`, `ControlTiming`, and `CommandArbiter`. Write a four-row table: constraint type (magnitude, age, priority, environment), code owner, failure action. Mark which rows would move into a future native MPC versus stay in Python supervision.
