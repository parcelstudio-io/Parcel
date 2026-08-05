# Day 22: Rigid-Body Pose and Twist

## Mental model

A **rigid body** is an approximation in which distances between points on the body never change. Its **pose** says where it is and how it is oriented. Its **twist** says how that pose is changing now: linear velocity plus angular velocity. Pose is state; twist is a rate. Neither has meaning without a coordinate frame and timestamp.

Parcel’s navigation layer usually uses the planar subset: position `(x, y)`, yaw `theta`, and body twist `(vx, vy, yaw_rate)`. The physical Go2 still moves in six body degrees of freedom—translation along three axes and rotation about three axes—while Sport handles roll, pitch, height, and leg coordination underneath that narrow command.

## Quantities, units, and assumptions

- Position `p`: metres (`m`) in a named frame such as odometry.
- Orientation `theta` in the planar model: radians (`rad`).
- Linear velocity `v`: metres per second (`m/s`).
- Angular velocity `omega`: radians per second (`rad/s`).
- Twist: a stacked linear and angular velocity, plus an expressed-in frame.

Assume a rigid chassis and short timesteps. A twist is locally valid; integrating it for a long interval without feedback accumulates error. Body-frame velocity axes rotate with the dog, while odometry-frame axes do not.

## Core equations

For planar yaw:

```text
p_world = R(theta) p_body + t

R(theta) = [ cos(theta)  -sin(theta) ]
           [ sin(theta)   cos(theta) ]

velocity of body point P:
v_P = v_origin + omega cross r_P

small-step integration:
theta_(k+1) approximately theta_k + omega_k Delta_t
```

The cross product means a point away from the rotation axis has tangential velocity even when the body origin has none.

## ASCII diagram

```text
                 world y
                    ^
                    |       front microphone P
                    |          * ---> omega x r
                    |       [ dog ] ---> body x
                    |          O  body origin
                    +------------------------> world x

pose: where O is + body orientation
twist: velocity of O + angular velocity
```

## Worked Parcel / Go2 example

**The following values are illustrative, not commissioned Go2 limits.** Parcel requests body-frame `vx = 0.40 m/s`, `vy = 0`, and yaw rate `omega = 0.60 rad/s`. An audio array sits `0.25 m` in front of the modeled body origin. Rotation alone gives that point a sideways speed magnitude:

```text
v_tangent = omega r = 0.60 rad/s * 0.25 m = 0.15 m/s
```

So the microphone’s world motion is not identical to the body origin’s motion. If the dog is yawed `90 degrees`, body-forward `0.40 m/s` points primarily along world `+y`, not world `+x`. This matters for motion blur, acoustic vibration measurements, obstacle clearance at body extremities, and transforming a sidewalk goal into a body command.

## Software-engineering analogy

Pose resembles a record snapshot; twist resembles its derivative/event rate. Replaying a constant rate without fresh state is dead reckoning, like reconstructing a database from an event stream while silently dropping timestamps. Frames are schemas: two numeric arrays can share a shape and still be incompatible types.

## Parcel / Go2 bridge

At the application boundary, `VelocityCommand` carries a planar body-motion request. Once leased for control, its frame is `base_link`; planners reason over pose observations in an odometry-like frame. The adapter and navigation code must make transformations explicit. Sport maps the bounded twist request into gait and joint behavior; Parcel must not pretend `(vx, vy, vyaw)` directly specifies foot motion.

Companion reading: [Coordinate frames and planar transforms](../robotics-60-days/day-13-coordinate-frames-planar.md) and [Three-dimensional rotations](../robotics-60-days/day-14-3d-rotations.md).

## Failure and safety note

A planner subtracts a world-frame goal from the robot position and publishes the result directly as body-frame velocity. It works while yaw is near zero, then drives sideways or backward after a turn. The arrays and units are valid; the frame contract is not. Frame errors can produce immediate unsafe motion, so reject unknown frames, cap commands, and verify direction in simulation before fenced hardware testing.

## Retrieval questions

1. What is the conceptual difference between pose and twist?
2. Why does a sensor mounted away from the body origin move during an in-place yaw?
3. What additional information does `(0.4, 0.0, 0.6)` need before it is a physical command?

## Optional 10-minute exercise

On paper or in a small calculator, place the dog at world `(2, 1)` with yaw `90 degrees`. Transform a body point `(0.25, 0)` into world coordinates. Then transform body-forward velocity `(0.4, 0)` into world velocity. Do not command hardware.
