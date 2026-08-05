# Day 04: Velocity and Relative Velocity

## Mental model

Velocity is the rate and direction at which position changes. Relative velocity describes how one object moves as observed from another. Companion navigation lives in relative motion: the owner can walk, turn, stop, and cross behind an obstacle while the dog moves too.

A follower should not merely chase the owner’s last position. It should regulate a useful relationship: distance band, bearing, side or behind formation, visibility, and collision clearance. Relative velocity predicts whether the gap is closing before a position error becomes dangerous.

Instantaneous velocity is local in time. Average velocity over a long interval can hide stops, reversals, and oscillation.

## Quantities, units, and assumptions

Velocity is a vector in m/s:

~~~text
v = dp/dt
average velocity = displacement / elapsed time
speed = |v|
~~~

For dog D and owner O, expressed in the same frame and timestamp:

~~~text
relative position r = p_D - p_O
relative velocity v_rel = v_D - v_O
~~~

If the vectors are not time-aligned, apparent relative motion includes sensor delay. Owner velocity estimated from images also carries association and depth uncertainty. A prediction should have a short validity period.

## Core equations

In one dimension behind the owner, define gap g as owner position minus dog position:

~~~text
g = x_O - x_D
dg/dt = v_O - v_D
closing speed = v_D - v_O, when positive
time to close Δg ≈ Δg / closing_speed
~~~

Dimensions:

~~~text
[m] / [m/s] = [s]
~~~

This constant-velocity estimate ignores acceleration and should only be used over a short horizon.

## ASCII diagram

~~~text
 x direction →

 dog D ● -------- gap g -------- ● owner O
        v_D →                     v_O →

 v_D > v_O  : gap closes
 v_D = v_O  : formation holds
 v_D < v_O  : gap grows
~~~

## Worked Parcel / Go2 example

Assume, illustratively, the owner walks straight at 0.80 m/s while the dog moves at 1.00 m/s in the same direction. The closing speed is:

~~~text
v_close = 1.00 - 0.80 = 0.20 m/s
~~~

If the current gap is 2.0 m and the desired following distance is 1.5 m, the dog must close 0.5 m:

~~~text
t ≈ 0.5 m / 0.20 m/s = 2.5 s
~~~

This is not a command to run open loop for 2.5 s. Acceleration, owner motion, obstacles, and latency change the result. A closed-loop follower repeatedly estimates the owner relationship, limits speed, and slows before entering the desired band. All numbers are illustrative, not commissioned Go2 limits.

## Software-engineering analogy

Position error is backlog; relative velocity is whether backlog is growing or shrinking. An autoscaler that sees only queue length reacts late and oscillates. A follower that sees only owner distance behaves similarly.

Tracks are leases, not durable records. A stale owner velocity should expire rather than be extrapolated indefinitely. Identity association is analogous to routing a request to the correct tenant: an accurate velocity for the wrong person is still a severe error.

## Parcel / Go2 bridge

Parcel’s owner-following logic can turn a fresh owner track into a bounded goal or velocity proposal. Navigation and reactive safety still account for obstacles and people. Behavior planning decides whether “follow behind,” “walk beside me,” or “wait” is active; the locomotion layer should not infer that intent.

Companion reading: [Robotics Day 29 — Dynamic Obstacles and Owner Tracking](../robotics-60-days/day-29-dynamic-obstacles-owner-tracking.md).

## Failure and safety note

Do not extrapolate an occluded owner indefinitely or accelerate toward a low-confidence identity. On stale or ambiguous tracks, slow, stop, and enter a bounded reacquisition behavior. Relative-motion calculations must never override independent collision and stopping gates.

## Retrieval questions

1. What is the difference between speed, velocity, and average velocity?
2. Why must dog and owner velocities share a frame and timestamp?
3. What does positive closing speed imply about the owner gap?

## Optional 10-minute exercise

Calculate closing time for an initial 3.0 m gap, desired 1.5 m gap, dog speed 0.7 m/s, and owner speed 0.5 m/s. Then repeat if the owner speeds up to 0.75 m/s. State why neither result is safe as an open-loop timer.
