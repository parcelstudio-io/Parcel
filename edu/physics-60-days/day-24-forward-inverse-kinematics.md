# Day 24: Forward and Inverse Kinematics

## Mental model

**Forward kinematics** answers: “Given joint angles, where is the foot?” **Inverse kinematics** (IK) answers: “Given a desired foot position, which joint angles could place it there?” These are geometry questions. They do not prove the pose is force-feasible, collision-free, balanced, or reachable at the requested speed.

Forward kinematics usually has one result for a fully specified joint configuration. IK may have several branches, one branch, or no solution. A robust system filters solutions through joint limits, collision constraints, continuity with the current pose, and later dynamics checks.

## Quantities, units, and assumptions

- Link lengths `l_1`, `l_2`: metres (`m`).
- Joint angles `q_1`, `q_2`: radians (`rad`).
- Foot coordinates `(x, z)`: metres in the hip frame.
- Kinematic function `p = f(q)`: maps configuration to task-space position.

We use a planar two-link leg to expose the idea. A Go2 leg is three-dimensional and the vendor controller uses a richer model. Links are assumed rigid, joints ideal, and no load or contact force is considered.

## Core equations

For a two-link planar chain:

```text
x = l1 cos(q1) + l2 cos(q1 + q2)
z = l1 sin(q1) + l2 sin(q1 + q2)

reachable-distance condition:
|l1 - l2| <= sqrt(x² + z²) <= l1 + l2
```

IK inverts these relationships. The elbow/knee sign commonly creates two branches. Numerical IK instead iteratively reduces task-space error.

## ASCII diagram

```text
 hip O ---- l1 ---- o ---- l2 ---- * foot
      q1            q2

 forward: [q1, q2] -------------> [x, z]
 inverse: [x, z] -----> zero, one, or several [q1, q2]

 outer circle radius l1+l2: geometric reach boundary
```

## Worked Parcel / Go2 example

**All numbers are illustrative teaching values, not Go2 dimensions or a safe pose.** Let `l1 = l2 = 0.20 m`, `q1 = -45 degrees`, and `q2 = -45 degrees`. Then `q1 + q2 = -90 degrees`:

```text
x = 0.20 cos(-45 deg) + 0.20 cos(-90 deg)
  approximately 0.141 m

z = 0.20 sin(-45 deg) + 0.20 sin(-90 deg)
  approximately -0.341 m
```

Forward kinematics predicts the foot roughly `0.141 m` forward and `0.341 m` below the hip in this planar model. A desired point `0.50 m` from the hip is unreachable because the maximum reach is `0.40 m`. An IK implementation should return a typed failure, not clamp the target silently and pretend the requested pose was achieved.

## Software-engineering analogy

Forward kinematics is a deterministic projection from an internal representation to an external view. IK is an inverse query over a non-bijective index: several rows may match, or none. Selecting a branch without continuity and limits is like accepting an arbitrary database result without ordering or validation.

## Parcel / Go2 bridge

Parcel normally delegates real-time foot trajectories and IK to Unitree Sport. Kinematic understanding is still essential for reviewing scripted simulation poses, robot profiles, collision geometry, and a future replaceable controller. Keep the interface layered: semantic behavior to body objective, body objective to locomotion controller, and only the authorized locomotion layer to joints.

Companion reading: [Forward and inverse kinematics](../robotics-60-days/day-15-forward-inverse-kinematics.md) and [Unitree Sport nested loop](../robotics-60-days/day-20-synthesis-unitree-sport-nested-loop.md).

## Failure and safety note

An IK solver chooses a mathematically valid alternate branch that flips the knee through the chassis. The endpoint is correct; the path and self-collision are not. Always enforce limits, branch continuity, collision checking, finite-value checks, and bounded rates. Educational solutions must remain in simulation or unpowered sketches unless a qualified hardware procedure authorizes them.

## Retrieval questions

1. Why can inverse kinematics have more than one answer?
2. What does the reach inequality prove, and what does it not prove?
3. Why is a correct foot position insufficient evidence for a safe leg motion?

## Optional 10-minute exercise

Use the equations with `l1 = 0.18 m`, `l2 = 0.22 m`, `q1 = -30 degrees`, and `q2 = -60 degrees`. Compute `(x, z)`. Then test whether targets `0.10 m`, `0.30 m`, and `0.45 m` from the hip pass the simple reach condition.
