# Day 17: Rigid-Body Dynamics, Contact, and Friction

## Mental model

Kinematics can say a foot *could* be at a point. Dynamics asks whether forces and contact can put it there without slipping or tipping.

```text
Newton / Euler (sketch):
  F = m a
  τ = I α   (plus cross terms when rotating)
```

Contact is unilateral: the ground can push up, not pull (unless sticky). Friction cones limit horizontal force relative to normal force — exceed the cone and the foot slides. A quadruped’s support polygon (or time-varying support during gait) must keep the center-of-pressure / wrench feasible. Gait is a schedule of contact modes: which feet are stance vs swing.

Unitree Sport’s value proposition for Parcel: the hard contact-control problem stays onboard. Parcel still designs as if contact can fail — slip, soft terrain, missing footholds — because outer commands assume traction that physics may deny.

## Software-engineering analogy

Dynamics is capacity planning under hard resource constraints. Contact modes are state machines with illegal transitions (you cannot “borrow” negative normal force). Friction limits are rate quotas: bursts above quota drop packets — here, they drop traction. Ignoring contact is like ignoring disk full: the API returns 200 while the durable write never happened (Day 01: ack ≠ actual).

## Light equations

Coulomb sketch:

```text
|F_tangential|  ≤  μ F_normal
F_normal ≥ 0
```

Quasi-static tip intuition: if the vertical projection of CoM leaves the support region, gravity produces a tipping moment. Dynamic gaits borrow angular momentum — still bounded.

## ASCII diagram

```text
          body CoM
             |
        ____/_\____
       /           \      friction cone at stance foot
      foot         foot     /|\
       ▲             ▲     / | \
       | normal      |    /  |  \ tangential limit

Parcel command: body twist (assumes contacts can realize it)
Sport: choose contacts + forces  -->  motors
If ice: same Move ACK, less actual acceleration (measure to detect)
```

## Map to Parcel / Go2

**Codebase anchors (contact-aware supervision, not a contact solver):**

- `docs/MOTION.md`: Unitree Sport owns “fast balance, gait, foot placement, and motor control”; Parcel owns semantic goals and environmental gates — not friction-cone QP.
- `RobotMotionState.foot_forces` populated from Sport `foot_force` in `UnitreeSportStateSource._on_message` — useful telemetry/future estimators; not currently a Parcel stance machine.
- Stop confirmation uses measured body speed thresholds (`ControlTiming.settled_linear_speed_mps`, `settled_yaw_speed_rad_s`) and sequenced fresh samples — dynamics-aware in the weak sense that “commanded stop” ≠ “settled.”
- Tilt fault (`max_tilt_rad`) is a coarse tip proxy after contact/balance has already struggled.
- Simulation (`backends/mujoco.py`, `edu/INTRO.md` reality gap): contact solvers differ from hardware; never treat sim footholds as proof of friction on tile.


## Why builders care

If you only test on carpeted sim or dry lab floors, every velocity schedule looks feasible. Cities add wet stone, grates, and slopes. Design completion logic and thermal/power budgets assuming contact sometimes lies. `foot_forces` and measured velocity are hints for future estimators; today, timeouts on owner-relative progress and tilt/fault supervision are your practical dynamics alarms. Do not confuse Sport’s willingness to accept `Move` with a feasible contact wrench.

When reading MuJoCo behavior, ask what contact parameters were used and whether the scenario injects slip. Reality-gap humility is part of the dynamics lesson.

Impulse intuition: a foot hitting early creates a velocity jump the kinematic plan did not schedule. Sport’s contact handling absorbs much of that; your outer loop still sees attitude and speed glitches—do not interpret every glitch as a nav bug. Conversely, if measured speed stays near zero while `Move` remains nonzero for seconds, believe contact/traction or a mode fault before believing the plan.

Support changes each gait phase; quasi-static polygons are teaching tools, not a claim that Sport walks statically stable every instant.

Remember: energy and heat (Day 05) couple to contact too—slipping gaits waste battery and warm actuators without advancing the task.

Keep the mental model crisp: equations guide reviews; code and commissioning make them real. If contact telemetry is empty in logs, you are flying without one of the few dynamics hints Sport exposes—turn `foot_forces` logging on during commissioning.

## Failure story

On polished lobby stone, a follow controller kept issuing `vx` because Sport accepted `Move` and odometry crept forward via slip+gait chatter. Owner-relative progress stalled; the dog “worked hard” in place and heated actuators. Software thought dynamics were fine because the transport and mode bits looked healthy. Fix: progress predicates from fused pose/perception with timeouts; treat persistent command-without-progress as traction or tracking failure, not success.

## Retrieval questions

1. Why can a kinematically valid footstep still fail on real ground?
2. What does a friction cone constrain, and who closes that loop on Go2 with Sport?
3. (From Day 03/04) How do stopping distance and tip-over relate to why Parcel caps `max_vx` / watches tilt?

## Optional 10-minute exercise

Read the “Why use Sport first” table in `docs/MOTION.md`. In three bullets, separate: (a) contact problems Sport absorbs, (b) signals Parcel supervises (`foot_forces`, tilt, settled speed), (c) environmental collision gates that are *not* contact physics.
