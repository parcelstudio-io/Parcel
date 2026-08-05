# Day 29: Dynamic Balance

## Mental model

Static balance asks whether a stationary center-of-mass projection lies inside a support region. Walking adds momentum: the center of mass may move outside a current support polygon and still be recoverable by changing force or taking a step. **Dynamic balance** asks whether available contacts, friction, torque, and future footsteps can redirect the robot’s state before it falls.

Two teaching tools make this less vague. The **zero-moment point** (ZMP) is a point on the support plane where the modeled net ground-reaction wrench has no moment about axes tangent to that plane. Under restrictive assumptions, keeping it inside the support region indicates a feasible contact wrench. The **capture point** is where a simplified inverted-pendulum robot would need to place support so its motion can be brought to rest without another step.

## Quantities, units, and assumptions

- Center-of-mass position `x`: metres (`m`).
- Center-of-mass velocity `x_dot`: metres per second (`m/s`).
- Center-of-mass height `h`: metres (`m`).
- Horizontal acceleration `x_ddot`: metres per second squared (`m/s²`).
- Gravity `g`: about `9.81 m/s²` near Earth.

The equations below use a linear inverted pendulum: constant CoM height, level ground, massless leg, no angular-momentum change, and adequate friction. A real quadruped violates several assumptions; Sport uses richer state and contact control.

## Core equations

```text
natural rate:       omega_0 = sqrt(g/h)
capture point:      x_cp = x + x_dot/omega_0
simple ZMP relation:x_zmp = x - (h/g) x_ddot
```

The capture-point offset grows with velocity and with CoM height. It is an intuition for recoverability, not a universal fall detector.

## ASCII diagram

```text
                    CoM * ----> x_dot
                        |\
                      h | \ simplified massless leg
                        |  \
ground -----------------+---X--------------------
                     stance  capture point

if X lies beyond available step/contact region,
the simplified model cannot stop in one step
```

## Worked Parcel / Go2 example

**Every number is illustrative and is not a Go2 balance or gait limit.** Suppose the simplified CoM height is `h = 0.30 m` and forward velocity is `0.40 m/s`:

```text
omega_0 = sqrt(9.81 / 0.30) approximately 5.72 1/s
capture offset = 0.40 / 5.72 approximately 0.070 m
```

The teaching model says support would need to move about `7 cm` ahead of the CoM position to capture that forward motion in one ideal step. At `0.80 m/s`, the offset doubles to about `14 cm`. Actual feasibility also depends on swing time, foothold geometry, friction, joint speed, body angular momentum, controller state, and terrain. Parcel cannot turn this number into a hardware speed cap without measurement and vendor constraints.

## Software-engineering analogy

Static stability resembles checking current capacity; dynamic balance resembles recoverability under queued work and latency. Capture point is a rough “where must the next replica come online before backlog becomes unrecoverable?” estimate. A healthy present snapshot is insufficient when momentum carries state forward.

## Parcel / Go2 bridge

Sport’s high-rate closed loop estimates attitude and motion, schedules contacts, and adjusts foot placement. Parcel supplies slower semantic/navigation objectives and applies safety fences. It should not implement a ZMP or capture-point controller in prompt logic. These concepts instead explain why abrupt speed changes, late commands, payload shifts, and unavailable footholds challenge the onboard controller.

Companion reading: [Rotational mechanics and balance](../robotics-60-days/day-04-rotational-mechanics-balance.md), [Rigid-body dynamics and contact](../robotics-60-days/day-17-rigid-body-dynamics-contact.md), and [Closed-loop task execution](../robotics-60-days/day-46-closed-loop-task-execution.md).

## Failure and safety note

A team treats “CoM projection inside polygon” as a walking safety assertion. During braking the projection is inside for one frame, but forward momentum requires a foothold beyond an obstacle. The static dashboard stays green while the recoverable set has vanished. Dynamic-balance formulas are also unsafe if their assumptions are hidden. Preserve Sport authority, bound application commands, and use only vendor-approved low-energy commissioning procedures in a controlled area.

## Retrieval questions

1. Why can a moving CoM outside the current support region still be recoverable?
2. In plain language, what do ZMP and capture point each describe?
3. Name three real effects omitted by the linear inverted-pendulum example.

## Optional 10-minute exercise

Calculate capture-point offset at speeds `0.2`, `0.4`, and `0.8 m/s` for illustrative heights `0.25` and `0.35 m`. Plot or tabulate the results. State why the table is not a Go2 commissioning artifact.
