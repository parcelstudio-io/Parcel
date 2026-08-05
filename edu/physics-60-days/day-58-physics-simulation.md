# Day 58: What a Physics Simulator Computes

## Mental model

A physics simulator repeatedly approximates the next state from equations of motion, controls, contacts, and constraints. It does not “run reality.” It chooses body shapes, masses, joints, friction laws, solver tolerances, timestep, and numerical integration. Every choice defines a different executable model.

For a quadruped, contact is the hard part. Feet repeatedly appear, stick, slip, push, and leave the ground. A simulator may enforce nonpenetration with constraints or approximate contact with stiff forces. Too-large timesteps, weak solver convergence, unrealistic friction, or a kinematic body shortcut can produce sliding motion that would not survive hardware.

## Quantities, units, and assumptions

- generalized position `q`: metre and radian components
- generalized velocity `v`: `m/s` and `rad/s`
- mass matrix `M(q)`: entries carry the units needed to map each generalized acceleration to generalized force; translational blocks resemble `kg`, rotational blocks `kg m²`, and mixed blocks depend on coordinates
- applied/generalized force `tau`: newton and newton-metre components
- constraint/contact force `J^T lambda`
- timestep `Delta t`: second (`s`)
- penetration `delta`: metre (`m`)
- solver tolerance and iteration count: implementation-defined

Rigid bodies, Coulomb friction, and point or convex contacts are approximations. Rendering rate, control rate, sensor rate, and physics rate are separate clocks.

## Core equations

A compact constrained equation is:

~~~text
M(q) v_dot + C(q,v) = tau + J(q)^T lambda
q_dot = mapping(q) v
~~~

Two simple integration sketches:

~~~text
explicit Euler:      q_next = q + Delta_t v
                     v_next = v + Delta_t a(q,v)
semi-implicit Euler: v_next = v + Delta_t a(q,v)
                     q_next = q + Delta_t v_next
penalty contact:     F_n approximately max(0, k delta + c delta_dot)
~~~

Here `delta >= 0` is penetration and `delta_dot` is positive while penetration grows. The clamp encodes unilateral contact: this simple ground model may push but not pull. Smaller timestep usually reduces integration error but costs compute; it does not repair a wrong contact model or mass.

## ASCII diagram

~~~text
 behavior tick ----> body command
                         |
 physics substeps: [forces -> constraints -> integrate] x many
                         |
 sensor clocks ----> delayed/noisy observations
 render clock -----> pixels for a human (optional in headless eval)

 simulator-private truth must not leak into production dog APIs
~~~

## Worked Parcel / Go2 example

Consider one second of ideal free fall with semi-implicit Euler, initial rest, `a = -9.81 m/s^2`, and illustrative `Delta t = 0.020 s`. The exact displacement is `-4.905 m`. For constant acceleration, this update yields approximately:

~~~text
x_sim = (1/2) a (t^2 + t Delta_t)
      = 0.5(-9.81)(1.0 + 0.020) = -5.003 m
error magnitude = about 0.098 m
~~~

Reducing `Delta t` reduces this particular error. Quadruped contact can be more sensitive: a stiff foot model may require much smaller steps or an implicit/constraint solver. An illustrative simulation might run physics at 500 Hz, body control at 10 Hz, LiDAR on its own clock, and rendering at 30 Hz. Those are teaching rates, not Parcel configuration claims.

A dynamic city adds moving people as physical/kinematic agents, occlusions, and prediction uncertainty. It should not grant the dog exact pedestrian state. Headless tasks must score observable predicates—sidewalk membership, lamppost vicinity, orbit progress, collisions—not simulator command completion.

## Software-engineering analogy

A simulator is an executable specification with a lossy database engine. Timestep is transaction frequency; a contact solver is the constraint engine; tolerance is consistency budget. Higher throughput does not fix a bad schema. Exposing world truth to the agent is like testing production code with database internals unavailable in deployment.

## Parcel / Go2 bridge

Parcel should keep the same navigation, arbitration, and `LocomotionController` contracts across simulator and Sport adapters. Simulator-only observations belong to eval assertions, never model inputs. Read [Day 36: What a Simulator Computes](../robotics-60-days/day-36-what-simulator-computes.md), [Day 38: Testing and Evaluation](../robotics-60-days/day-38-testing-evaluation.md), and [`docs/MOTION.md`](../../docs/MOTION.md).

## Failure and safety note

A stable-looking simulation can conserve the wrong quantities or use hidden kinematic motion. Check energy, momentum, contact penetration, foot slip, and timestep convergence—not visuals alone. Never interpret simulator stability as hardware commissioning evidence. Keep learned or experimental control behind the same limits and hardware-disabled by default.

## Retrieval questions

1. What distinct jobs do the dynamics equation, contact solver, and integrator perform?
2. Why can reducing timestep fail to fix unrealistic robot motion?
3. Which simulator values may eval code read but production Parcel behavior must not consume?

## Optional 10-minute exercise

Recompute the free-fall example for timesteps of 0.1, 0.02, and 0.002 s. If a headless simulator is already configured, vary only its timestep in an offline copy and compare a passive object's energy/contact penetration; do not alter the robot behavior under evaluation.
