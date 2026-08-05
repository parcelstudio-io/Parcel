# Day 19: Torque and Levers

## Mental model

Torque measures a force’s tendency to rotate a body about an axis. The same force creates more torque when applied farther from the axis or more perpendicular to the lever arm. This is why payload placement matters: a modest camera or speaker mounted far from the body center can create meaningful pitch or roll moment.

A joint motor produces torque, but the torque required at a joint depends on posture. Extending a leg or carrying a load farther out increases lever arms. Static torque is only the beginning; acceleration, impacts, gait, and vibration add dynamic loads.

Torque is not force. It is also not energy, despite sharing the derived unit N·m.

## Quantities, units, and assumptions

~~~text
force F             N
lever-arm vector r  m
torque τ            N·m
angle φ between r and F   rad
~~~

Torque has an axis and direction given by the right-hand rule. In planar problems, it can be treated as positive or negative rotation out of the page.

A **moment arm** is the perpendicular distance from the rotation axis to the force’s line of action. Assume rigid geometry and static loading for simple estimates. Real mounts need dynamic load factors, stiffness, fastener preload, fatigue, and safety retention.

## Core equations

~~~text
vector torque τ = r × F
magnitude |τ| = rF sinφ
static rotational equilibrium: Στ = 0
rotational work for constant aligned torque: W = τθ
~~~

Dimensional check:

~~~text
[m][N] = [N·m]
~~~

Torque and energy differ because torque is a directed rotational effect, while work integrates torque through an angle. Writing joules for a torque value hides that distinction.

## ASCII diagram

~~~text
 pivot ●──────────────● payload
       <---- r ------->
                      ↓ F = mg

 torque magnitude about pivot = rF when perpendicular
 move payload inward → smaller torque
~~~

## Worked Parcel / Go2 example

Assume an illustrative 1.0 kg payload whose center of mass lies 0.20 m horizontally from a mounting reference:

~~~text
F = mg = (1.0 kg)(9.81 m/s²) = 9.81 N
τ = rF = (0.20 m)(9.81 N) ≈ 1.96 N·m
~~~

Moving the same payload to 0.10 m halves the static torque. During acceleration or a foot impact, effective loads can be larger. The reference axis may also differ from a real joint or mount fastener.

These values are illustrative, not an approved Go2 payload, mount, or joint-torque specification. Never compare this crude body-level moment directly with a vendor joint-torque limit without a full load path and posture model.

## Software-engineering analogy

Torque is force multiplied by leverage, much like the blast radius of a permission depends on where it is applied. The same request at a deeper or more privileged boundary can have a larger system effect.

Moving a payload inward is architectural locality: reduce the lever arm before attempting to provision stronger components. Geometry can solve problems that control tuning cannot.

## Parcel / Go2 bridge

The audio array, speaker, camera, LiDAR, compute, enclosure, and cables all alter body mass distribution and moments. A retrofit plan should record component mass, center-of-mass location, mounting axes, dynamic environment, cable forces, and retention. Unitree Sport compensates within its supported embodiment; it does not authorize arbitrary payload geometry.

Companion reading: [Robotics Day 04 — Rotational Mechanics and Balance](../robotics-60-days/day-04-rotational-mechanics-balance.md).

## Failure and safety note

Do not hang test weights from a powered robot or use a motor joint as a fixture. Obtain vendor payload guidance and qualified mechanical review. Test mounts unpowered with approved supports and retention before any controlled, low-energy robot trial.

## Retrieval questions

1. Which three geometric quantities determine torque magnitude?
2. Why does moving a payload closer to the body reduce static joint or mount load?
3. Why is N·m for torque not interchangeable with J for energy?

## Optional 10-minute exercise

For a 5 N force applied 0.1 m from a pivot, calculate torque at angles 0°, 30°, and 90°. Draw the force line and moment arm for each. Use paper only.
