# Day 05: Acceleration

## Mental model

Acceleration is the rate at which velocity changes. Because velocity includes direction, a body accelerates when it speeds up, slows down, or turns—even if its speed stays constant. A robot feels smooth when acceleration changes are bounded; an instantaneous velocity step would require an impossible impulse.

Navigation often outputs a desired velocity. The locomotion controller and physical body cannot adopt it immediately. Acceleration limits, traction, motor torque, payload, slope, and balance determine how quickly measured velocity can follow. Jerk, the rate of change of acceleration, captures how abruptly that force demand begins.

“Negative acceleration” is not automatically braking. Its meaning depends on the selected positive axis. Use “acceleration opposite the current velocity” when describing deceleration physically.

## Quantities, units, and assumptions

Linear acceleration is a vector measured in m/s². Jerk is measured in m/s³.

~~~text
average acceleration = change in velocity / elapsed time
a = Δv/Δt
jerk j = Δa/Δt
~~~

Acceleration must be expressed in a frame. During a turn, body-frame components rotate relative to the map. A finite-difference estimate assumes timestamps are correct and velocity estimates are comparable. Noise is amplified by differentiation, so raw sample-to-sample acceleration can be misleading.

Gravity has magnitude about 9.81 m/s² near Earth’s surface, but an accelerometer does not simply report “world acceleration”; IMU-specific-force physics arrives on Day 50.

## Core equations

For approximately constant acceleration in one direction:

~~~text
a = (v₂ - v₁)/(t₂ - t₁)
v₂ = v₁ + a Δt
average velocity = (v₁ + v₂)/2
displacement = average velocity × Δt
~~~

Dimensional check:

~~~text
([m/s] - [m/s])/[s] = [m/s²]
~~~

Changing velocity from zero to a finite value in zero time would make the denominator zero and acceleration unbounded. Real actuators and contact make that impossible.

## ASCII diagram

~~~text
velocity
  ^
  |             ______ desired
  |          __/
  |       __/        measured ramp
  |    __/
  |___/____________________________> time
      acceleration = slope

smooth command → bounded slope → feasible contact force
~~~

## Worked Parcel / Go2 example

Suppose an illustrative motion profile ramps from 0 to 0.60 m/s in 1.20 s:

~~~text
a = (0.60 - 0) m/s / 1.20 s = 0.50 m/s²
~~~

With a linear ramp, average velocity is 0.30 m/s, so progress during the ramp is:

~~~text
d = (0.30 m/s)(1.20 s) = 0.36 m
~~~

If measured velocity reaches only 0.48 m/s, the tracking shortfall may reflect traction, a safety clamp, slope, payload, or estimator lag. It does not mean the outer planner should increase acceleration blindly. These numbers are illustrative and are not commissioned Go2 limits.

A turn at constant 0.40 m/s speed also requires acceleration because the velocity arrow continually rotates. That lateral acceleration must ultimately come from foot-ground forces.

## Software-engineering analogy

Velocity is system throughput; acceleration is how quickly throughput changes. A rate limiter bounds velocity, while a ramp limiter bounds acceleration. Jerk resembles change-rate limits that prevent a sudden traffic surge from shocking a downstream dependency.

Differentiation amplifying noise resembles computing request-rate change from two jittery counters. Use time windows and filtering carefully, while remembering that filtering adds delay.

## Parcel / Go2 bridge

Parcel shapes high-level velocity requests before Unitree Sport turns them into gait and contact forces. Safety stops may need a different path from comfort smoothing: a pleasant ramp cannot outrank an imminent collision response. Logs should retain requested, shaped, and measured velocity so an engineer can identify which layer introduced a change.

Companion reading: [Robotics Day 03 — Linear Mechanics](../robotics-60-days/day-03-linear-mechanics.md).

## Failure and safety note

Never tune acceleration or jerk on hardware by repeatedly increasing values until motion “looks responsive.” Begin with vendor-supported modes and conservative commissioning procedures, instrument tilt and measured velocity, clear the area, and keep an E-stop operator present. Payload and surface changes invalidate prior observations.

## Retrieval questions

1. How can a dog accelerate while maintaining constant speed?
2. Why is an instantaneous velocity change physically impossible?
3. Why does differentiating a noisy velocity estimate make the result noisier?

## Optional 10-minute exercise

Plot a velocity ramp from 0 to 0.5 m/s over 2 s. Compute its acceleration and area under the graph. Then sketch a smoother S-shaped ramp with the same endpoints and explain qualitatively where its jerk is smaller.
