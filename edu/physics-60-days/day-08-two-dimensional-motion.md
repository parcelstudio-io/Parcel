# Day 08: Two-Dimensional and Relative Motion

## Mental model

City and indoor navigation is mostly planar: a goal has x and y separation, paths curve around obstacles, and owner-relative behaviors combine radial and tangential motion. Two-dimensional reasoning becomes simpler when vectors are decomposed into useful directions.

For goal seeking, one direction points toward the goal and another lies perpendicular to it. For orbiting an owner, the radial direction controls distance and the tangential direction advances around the circle. For following, relative velocity determines whether the formation is converging.

Decomposition does not grant physical feasibility. A computed lateral component may be mathematically valid while forward travel after turning is smoother, more legible to pedestrians, and easier for a quadruped.

Near a goal, the raw unit direction can change sharply from tiny position errors. A practical controller reduces speed and uses a tolerance region so sensor noise does not command endless corrections.

## Quantities, units, and assumptions

Let planar displacement to a target be:

~~~text
r = p_target - p_dog = (Δx, Δy) in m
distance R = |r|
unit direction r_hat = r/R
~~~

A unit vector has no units and magnitude one. Multiplying it by desired speed produces velocity in m/s.

Assume both positions share the same frame and timestamp. If the target moves, a pure line-of-sight direction is already aging; prediction should remain short-horizon and bounded.

## Core equations

Goal-directed velocity:

~~~text
v_goal = speed × r_hat
r_hat = (Δx/R, Δy/R)
~~~

A perpendicular unit direction in 2D is:

~~~text
t_hat = (-r_hat_y, r_hat_x)
~~~

Orbit-style command before safety and feasibility checks:

~~~text
v = k_r(R - R_desired) r_hat + v_tangential t_hat
~~~

Sign conventions must be chosen carefully: depending on how r is defined, the radial correction may need a minus sign. Test with a drawing before code.

## ASCII diagram

~~~text
                  t_hat (tangent)
                       ↑
 owner ● <---- r_hat --● dog
          radius R       \
                         \ desired curved path

 radial term: hold distance
 tangent term: progress around owner
~~~

## Worked Parcel / Go2 example

Suppose an illustrative map-frame target lies 3 m east and 4 m north of the dog:

~~~text
r = (3, 4) m
R = √(3² + 4²) = 5 m
r_hat = (0.6, 0.8)
~~~

At a proposed speed of 0.50 m/s:

~~~text
v_goal = (0.30, 0.40) m/s
~~~

That vector is a map-frame proposal, not necessarily the body command. A forward-preferred quadruped navigator can first rotate the body toward the path, then request mostly positive forward velocity, using bounded lateral velocity only when it improves local safety or formation. Obstacle avoidance may replace the direct vector entirely. All values are illustrative, not commissioned Go2 limits.

## Software-engineering analogy

Vector decomposition resembles separating a request into orthogonal concerns. One controller regulates owner distance; another advances task phase. Composition is useful only with an arbiter that understands shared resources and constraints.

A unit vector is normalized intent, while speed is a budget. Keeping them separate prevents geometry code from silently deciding aggressiveness.

## Parcel / Go2 bridge

Parcel can translate semantic goals into safe goal regions, then let navigation produce paths and short-lived body commands. Orbit, behind-owner, and sidewalk tasks reuse vector primitives but need distinct completion predicates. Dynamic obstacle prediction and collision monitoring remain downstream vetoes.

Companion reading: [Robotics Day 28 — Smooth Local Navigation](../robotics-60-days/day-28-smooth-local-navigation.md).

## Failure and safety note

Direct pursuit vectors can cut corners through obstacles or people. Never send a semantic line-of-sight vector directly to locomotion. It must pass map, traversability, dynamic-obstacle, footprint, and stopping checks. When owner identity or location is uncertain, do not use an orbit calculation to keep moving.

## Retrieval questions

1. What information does a unit direction contain, and what does it omit?
2. Which two components make an owner orbit controllable?
3. Why should a map-frame goal vector not be sent directly as a body velocity?

## Optional 10-minute exercise

For target displacement (-6, 8) m, calculate distance, unit direction, and a 0.25 m/s goal vector. Draw the vector and verify its speed from its components.
