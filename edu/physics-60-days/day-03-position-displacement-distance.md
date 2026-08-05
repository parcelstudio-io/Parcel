# Day 03: Position, Displacement, and Distance

## Mental model

Position describes where something is relative to an origin. Displacement is the vector from an initial position to a final position. Distance is the scalar length of the path traveled. They answer different questions.

A dog that walks once around its owner and returns to the starting point has nearly zero displacement but a substantial traveled distance. A task verifier that checks only final position cannot prove the orbit occurred. Conversely, integrating commanded speed cannot prove the body traveled that distance.

Robotics needs all three: position for localization and goals, displacement for progress, and path length for energy, wear, and task semantics.

## Quantities, units, and assumptions

Planar position is commonly written:

~~~text
p = (x, y) in metres, in a named frame
~~~

Displacement is:

~~~text
Δp = p_final - p_initial
~~~

Distance traveled is the sum of small path segments. It is nonnegative and never smaller than displacement magnitude. Position also needs a timestamp because the dog, owner, and obstacles move.

Assumptions matter. Odometry position can drift; map position may jump after localization correction; an owner-relative position changes when either participant moves. Define which frame supplies progress and how discontinuities are handled.

## Core equations

For two planar positions:

~~~text
Δp = (x₂ - x₁, y₂ - y₁)
|Δp| = √((x₂ - x₁)² + (y₂ - y₁)²)
distance ≈ Σ |p_k - p_(k-1)|
~~~

For a perfect circle of radius r:

~~~text
circumference = 2πr
net displacement after one full orbit = 0
~~~

Every term has units of metres.

## ASCII diagram

~~~text
              curved path distance
         .-------------------------.
 start ●                             ● finish
        \___________________________/
          straight displacement Δp

 orbit case: start ● = finish ●, yet path distance > 0
~~~

## Worked Parcel / Go2 example

Suppose the user asks, “Walk around me once,” and the planner chooses an illustrative radius of 1.5 m after checking clearance. The ideal path length is:

~~~text
L = 2πr = 2π(1.5 m) ≈ 9.42 m
~~~

After one orbit the dog can finish near its initial point, so final displacement might be only 0.08 m. A valid completion predicate needs more than that final proximity. It can combine accumulated angle around a continuously tracked owner, collision-free path execution, owner-distance tolerance, and settled measured motion.

The chosen radius, tolerance, and speed are illustrative; they are not commissioned Go2 limits. In a narrow room the system may need to reject or adapt the orbit rather than force the same geometry.

## Software-engineering analogy

Position resembles current database state. Displacement resembles a diff between snapshots. Distance resembles an event-log aggregate. Current state alone cannot prove the history of a workflow; an event count alone cannot prove the final state.

Localization resets are similar to rebasing an event stream. If a map-frame correction suddenly moves the reported pose, blindly summing samples invents traveled distance. Preserve frame epochs and reject discontinuous segments.

## Parcel / Go2 bridge

Parcel navigation should verify semantic tasks with predicates appropriate to their meaning. “Stand by the lamppost” can use final safe-region membership and settled speed. “Circle owner once” requires trajectory history around a fresh owner track. The controller acknowledgement proves neither.

Companion reading: [Robotics Day 30 — Sidewalk, Lamppost, and Owner-Orbit](../robotics-60-days/day-30-synthesis-sidewalk-lamppost-owner.md).

## Failure and safety note

Do not use accumulated commanded speed as a physical odometer. Slip, clamps, stalls, and packet loss break that assumption. Also avoid requiring an exact point near people or street furniture; define a safe goal region and keep collision margins independent of task tolerance.

## Retrieval questions

1. How can traveled distance be nonzero while displacement is zero?
2. Why is final pose insufficient to prove a completed owner orbit?
3. What can make a sum of localization samples overestimate physical path length?

## Optional 10-minute exercise

Sketch four points forming a 2 m by 1 m rectangle. Compute the path distance for one lap, final displacement, and straight-line distance from the first to the third corner. Then write one completion predicate for “circle once” that cannot pass while standing still.
