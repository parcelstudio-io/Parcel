# Day 13: Gravity, Weight, and Normal Force

## Mental model

Mass is the amount of inertia in an object; weight is the gravitational force acting on that mass. A 2 kg payload remains 2 kg on a ramp, but the direction of gravity relative to the floor changes how contact supports it.

The normal force is a contact force perpendicular to a surface. It is not automatically equal to weight. It can be distributed unevenly among feet, become larger during vertical acceleration, become smaller during unloading, or fall to zero when a foot leaves the ground.

On a slope, gravity splits into a component perpendicular to the surface and a component down the slope. Friction or another constraint must oppose the downslope component if the robot is to remain stationary.

## Quantities, units, and assumptions

Mass m is in kg. Gravitational acceleration g is approximately 9.81 m/s² near Earth. Weight W is a force in N:

~~~text
W = mg
~~~

Normal force N is also in N. Surface angle θ is in radians or clearly labeled degrees.

For the simplest slope analysis, assume a rigid body, planar incline, no vertical acceleration relative to the surface, and a center of mass that remains within a stable region. Dynamic gait requires a richer contact model.

## Core equations

On a level surface in static equilibrium:

~~~text
ΣN = mg
~~~

On an incline of angle θ:

~~~text
gravity perpendicular magnitude = mg cosθ
gravity downslope magnitude = mg sinθ
ΣN = mg cosθ        under the simple static assumptions
~~~

Dimensional check:

~~~text
[kg][m/s²] = [N]
~~~

Sine and cosine are dimensionless. The force components recombine to magnitude mg.

## ASCII diagram

~~~text
                    ↑ N, perpendicular
                  [ dog ]
                    ╲
                     ╲  slope
                      ╲________
                       ↘ mg sinθ, downslope
                    ↓ mg, vertical
~~~

## Worked Parcel / Go2 example

Assume an illustrative 16 kg system on a 10-degree slope:

~~~text
mg = (16)(9.81) ≈ 157 N
N_total ≈ 157 cos(10°) ≈ 155 N
F_downslope ≈ 157 sin(10°) ≈ 27.3 N
~~~

Contact must provide roughly 27.3 N uphill merely to prevent sliding under this simplified static model. The total normal force is distributed across stance feet according to posture and center-of-mass position.

These are illustrative calculations, not claims that a Go2 may stand or walk on a particular slope. Real safety depends on friction, surface irregularity, dynamic gait, payload position, actuator capacity, perception, and vendor restrictions.

If the robot accelerates upward over a bump, normal forces can temporarily exceed static weight. That extra contact load helps explain why a mount designed only for quiet standing can fail in motion.

## Software-engineering analogy

Mass is stable configuration; weight is environment-dependent load produced when that configuration interacts with gravity. Normal force is backpressure from a dependency—it responds to the current state rather than being a fixed constant.

Decomposing gravity along slope axes resembles changing basis to simplify a query. The underlying vector is unchanged; the useful components become obvious.

## Parcel / Go2 bridge

Slope changes stopping, traction, power, and balance budgets simultaneously. Parcel’s planning layer should use traversability estimates and conservative policies rather than treating every geometrically empty cell as equally drivable. Unitree Sport manages fast stance and balance, but it cannot make an unobservable or low-friction surface safe.

Companion reading: [Robotics Day 04 — Rotational Mechanics and Balance](../robotics-60-days/day-04-rotational-mechanics-balance.md).

## Failure and safety note

Do not infer an allowable slope from this equation or attempt progressively steeper hardware trials. Use vendor guidance, a controlled test facility, high-friction containment, fall protection approved for the robot, low energy, and a trained operator. Never stand downhill of the robot.

## Retrieval questions

1. What is the difference between mass and weight?
2. Why is normal force not always equal to mg?
3. Which gravity component must contact oppose to prevent downslope sliding?

## Optional 10-minute exercise

For an illustrative 12 kg body on 0°, 5°, and 15° slopes, calculate perpendicular and downslope gravity components. Plot how each changes. Do not convert the results into hardware slope limits.
