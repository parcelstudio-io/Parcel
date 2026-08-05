# Day 09: Angular Motion

## Mental model

Angular motion describes changing orientation. For a robot dog, yaw turns the body in the horizontal plane, roll tilts side to side, and pitch tilts nose up or down. Navigation often commands yaw rate; balance controllers respond to roll and pitch disturbances much faster.

Radians connect rotation to distance naturally. One radian is the angle that subtends an arc equal to the radius. A full revolution is 2π rad. Using radians makes equations for arc length and tangential speed dimensionally clean.

Angular velocity is not the same as the linear velocity around a turn. The farther a point is from the rotation axis, the faster it travels for the same angular rate.

Angular acceleration changes yaw rate over time. Bounding it prevents a planner from asking the body to begin or end a turn instantaneously, just as linear acceleration bounds smooth translation.

## Quantities, units, and assumptions

~~~text
angle θ                  rad
angular velocity ω       rad/s
angular acceleration α   rad/s²
radius r                 m
~~~

Positive rotation depends on the frame convention. In a common planar right-handed frame, positive yaw is counterclockwise viewed from above.

Angles wrap: +π and -π represent the same heading boundary. Subtracting raw headings can produce a nearly 2π error when the physical difference is tiny. Normalize angle errors to a documented interval.

## Core equations

~~~text
arc length s = rθ
ω = dθ/dt
α = dω/dt
tangential speed v_t = rω
period T = 2π/|ω|
centripetal acceleration a_c = v_t²/r = rω²
~~~

Radians are dimensionless, so:

~~~text
[m] × [rad/s] → [m/s]
~~~

The centripetal acceleration points toward the center even when speed is constant.

## ASCII diagram

~~~text
                     v_t tangent →
                 dog ●
                    /|
                   / | r
                  /  |
             owner ● |

 ω advances angle around owner
 a_c points inward along the radius
~~~

## Worked Parcel / Go2 example

Suppose an illustrative owner orbit uses radius 1.5 m and tangential speed 0.45 m/s:

~~~text
ω_orbit = v_t/r = 0.45/1.5 = 0.30 rad/s
T = 2π/0.30 ≈ 20.9 s
a_c = v_t²/r = 0.45²/1.5 = 0.135 m/s²
~~~

This orbital angular rate is the rate of position around the owner; it is not automatically the body yaw command. The dog may face tangent to the path, partly toward the owner, or along a collision-free local trajectory. A controller coordinates heading with translation.

The radius and speeds are illustrative, not commissioned Go2 limits. Real feasibility depends on available space, owner motion, obstacles, and traction.

## Software-engineering analogy

Wrapped angles resemble cyclic sequence numbers. Ordinary subtraction fails at the rollover boundary; comparison needs modular arithmetic. Angular rate resembles change throughput, while radius converts that shared rate into different linear loads for different points.

Yaw, pitch, and roll are distinct namespaces. Reusing an “angle” float without axis and frame is the rotational version of mixing tenant IDs.

## Parcel / Go2 bridge

Parcel can prefer turn-first motion for a distant goal: reduce heading error, then move mainly forward while continuing bounded corrections. Lateral velocity remains available but should not become the default substitute for heading alignment. Unitree Sport owns fast balance and gait, while Parcel supervises semantic path and environmental safety.

Companion reading: [Robotics Day 04 — Rotational Mechanics and Balance](../robotics-60-days/day-04-rotational-mechanics-balance.md).

## Failure and safety note

Do not test an unknown radians/degrees convention on powered hardware. A value intended as degrees per second can become about 57 times larger when interpreted as radians per second. Verify schemas, normalize angles in software tests, and commission turns at low energy with clear space.

## Retrieval questions

1. Why are radians convenient for connecting angular and linear motion?
2. How can an object accelerate while moving around a circle at constant speed?
3. Why can direct subtraction of two headings near ±π be wrong?

## Optional 10-minute exercise

Compute arc length, period, and centripetal acceleration for radius 2 m and tangential speed 0.4 m/s. Then write the wrapped shortest heading error from +179 degrees to -179 degrees.
