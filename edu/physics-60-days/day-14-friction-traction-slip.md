# Day 14: Friction, Traction, and Slip

## Mental model

Friction is the tangential contact force that resists relative sliding. Static friction applies while surfaces do not slip; it takes whatever value is needed up to a limit. Kinetic friction applies after sliding begins and is often lower. “Friction equals μN” is therefore usually a limit model, not the force always present.

Traction is the usable tangential force the feet obtain from contact. To accelerate, brake, turn, or stand on a slope, the robot needs traction. If requested force exceeds what the current contacts can supply, feet slip and commanded motion diverges from measured motion.

Friction depends on materials, contamination, surface texture, normal load, foot condition, and speed. A single coefficient is an approximation, not a property the camera can safely guess.

## Quantities, units, and assumptions

~~~text
normal force N             newtons
tangential friction F_t    newtons
coefficient μ              dimensionless
~~~

Simple Coulomb limits are:

~~~text
|F_static| ≤ μ_s N
|F_kinetic| ≈ μ_k N during sliding
~~~

Often μ_k is smaller than μ_s, but not universally. Each stance foot has its own contact and normal load. The full three-dimensional traction limit is often visualized as a friction cone.

Assume dry, uniform, rigid contact only when explicitly justified. Wet tile, loose gravel, grass, grates, and deformable soil violate that simplicity.

## Core equations

For a simple point mass on level ground:

~~~text
maximum tangential force ≈ μ_s N
ideal acceleration ceiling ≈ μ_s g
~~~

For static equilibrium on a slope:

~~~text
mg sinθ ≤ μ_s mg cosθ
tanθ ≤ μ_s
~~~

These relations describe an idealized slip threshold, not a safe operating envelope. Balance, motor torque, foot placement, and uncertainty impose tighter limits.

## ASCII diagram

~~~text
             body acceleration →
                   [dog]
            ↑ N       ↓ mg
 floor ─────●────────────────
            → F_t from ground

 required F_t inside limit: grip
 required F_t beyond limit: slip
~~~

## Worked Parcel / Go2 example

Assume illustratively that total normal force is 157 N and a rough model uses μ_s = 0.50:

~~~text
F_t,max ≈ (0.50)(157 N) = 78.5 N
a_ideal,max ≈ 78.5 N / 16 kg ≈ 4.9 m/s²
~~~

This is emphatically not a Go2 acceleration limit. It ignores time-varying foot loads, balance, actuator limits, compliance, uncertainty, and safety near people. A locomotion controller should operate with margin, and product speed/acceleration limits may be far lower.

If measured body progress stalls while commands continue and foot-force or IMU signals fluctuate, slip is one hypothesis. The system should stop or recover safely rather than integrate command duration and declare success.

## Software-engineering analogy

Friction is a capacity quota that changes with the environment. Static friction is elastic capacity up to a threshold; crossing it changes the operating regime. A controller tuned below the quota on carpet may overload the dependency on wet stone.

Command-without-progress resembles accepted jobs that never commit. Completion must consult durable evidence, not submission count.

## Parcel / Go2 bridge

Unitree Sport handles fast contact and gait control, while Parcel bounds environmental intent and watches measured progress, attitude, faults, and obstacle risk. Terrain perception can classify likely hazards but should not manufacture a precise friction coefficient from appearance. Unknown surfaces deserve conservative motion.

Companion reading: [Robotics Day 17 — Rigid-Body Dynamics, Contact, and Friction](../robotics-60-days/day-17-rigid-body-dynamics-contact.md).

## Failure and safety note

Never perform slip testing near stairs, roads, people, or without approved containment. Do not apply liquids to a test floor or pull a powered robot manually. Friction commissioning requires a controlled facility, vendor-approved procedure, fall protection where applicable, and an E-stop operator.

## Retrieval questions

1. Why is static friction not always equal to μ_sN?
2. Name four factors that can change available traction.
3. Why can the ideal μg estimate not serve as a commanded acceleration limit?

## Optional 10-minute exercise

Using a block-on-slope simulator or paper only, compare the ideal slip angle for μ_s values 0.2, 0.5, and 0.8 using θ = arctan μ_s. Label every result “model estimate, not robot limit.”
