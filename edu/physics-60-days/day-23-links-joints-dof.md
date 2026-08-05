# Day 23: Links, Joints, and Degrees of Freedom

## Mental model

A legged robot is an articulated graph. **Links** are approximately rigid bodies. **Joints** constrain how adjacent links move. A **degree of freedom** (DoF) is one independent coordinate needed to describe configuration. Counting DoF tells you the size of the configuration, not whether every desired motion is achievable under joint limits and ground contact.

Each Go2 leg has three actuated rotary joints, giving twelve actuated joint coordinates across four legs. The unbolted body also has six floating-base coordinates in the world. Those body coordinates are not six extra motors: during supported locomotion, joint action changes body motion by creating external forces and torques through contacts. Gravity and existing momentum also affect the body.

## Quantities, units, and assumptions

- Joint angle `q_i`: radians (`rad`).
- Joint rate `q_dot_i`: radians per second (`rad/s`).
- Link length: metres (`m`).
- Joint torque: newton metres (`N m`).
- Configuration vector `q`: all independent coordinates under the selected model.

Assume revolute joints and rigid links for the lesson. Real joints have backlash, compliance, friction, limits, velocity limits, and torque limits. Contact adds constraints that change through the gait.

## Core equations

```text
Go2 actuated joint count = 4 legs * 3 joints/leg = 12

floating body pose DoF = 3 translations + 3 rotations = 6

configuration sketch:
q = [body pose, q_FL, q_FR, q_RL, q_RR]
```

DoF is a count, not a unit. A task can require fewer coordinates than the robot owns, leaving redundancy, or demand a direction unavailable at a particular configuration.

## ASCII diagram

```text
                       floating body
                +-----------------------+
                  /      /       \      \
               hip    hip       hip    hip
                |       |         |      |
              thigh   thigh     thigh  thigh
                |       |         |      |
              calf   calf       calf   calf
                |       |         |      |
               foot    foot      foot   foot

      4 branches x 3 actuated revolute joints = 12
```

## Worked Parcel / Go2 example

**The dimensions and angles below are illustrative, not a Go2 specification or safe pose.** Consider one simplified leg with three rotary joints. Its joint vector is:

```text
q_leg = [q_hip, q_thigh, q_calf]
      = [0.10, 0.80, -1.55] rad
```

Changing `q_hip` primarily moves the leg laterally in this simplified interpretation; thigh and calf angles strongly affect fore-aft and vertical foot position. Four such vectors produce twelve actuator coordinates. Yet Parcel’s high-level request “move forward at 0.3 m/s” contains no desired joint angles. Sport chooses time-varying configurations, contact phases, and forces consistent with balance and vendor limits.

The floating body’s six coordinates explain another apparent mismatch: twelve motors can move an unactuated body because feet exchange forces with the ground. With all feet airborne, internal leg motion can redistribute angular momentum but cannot change the system center of mass away from the ballistic path set by external forces such as gravity.

## Software-engineering analogy

Morphology is a typed dependency graph. Links are stateful nodes; joints are edges with constrained interfaces. Counting fields in a struct tells you its state dimension, but not which state transitions are legal. Ground contact is a runtime constraint that changes which operations are available.

## Parcel / Go2 bridge

`RobotProfile` is the morphology authority in Parcel: model selection, joint ordering, limits, link dimensions, and stand geometry should enter through one validated boundary. High-level behaviors should speak typed skills and body goals. They must not manufacture joint arrays from conversational text. Sport advertises high-level balance capability, while Parcel intentionally does not claim low-level joint-control authority in normal operation.

Companion reading: [Links, joints, and degrees of freedom](../robotics-60-days/day-06-links-joints-dof.md) and [Typed hardware and controller boundaries](../robotics-60-days/day-31-typed-hardware-controller-boundaries.md).

## Failure and safety note

A pose file assumes a different vendor joint ordering. Every number falls within a plausible range, but front-right calf data is sent to another actuator in a low-level experiment. Shape validation passes while semantics fail. Keep names and ordering centralized, use vendor-documented limits, and never test an educational joint vector on powered hardware. Wrong joint commands can cause falls and damage immediately.

## Retrieval questions

1. Why are the floating body’s six DoF not six directly actuated joints?
2. What does the number twelve tell you—and not tell you—about Go2 motion?
3. Why should a voice planner never emit raw joint arrays?

## Optional 10-minute exercise

Build a two-link paper leg with two strips and pushpins, or simply sketch one. Count its configuration coordinates. Lock one joint and recount. Place the endpoint against a table and note how the contact constraint removes possible motion. Keep the robot unpowered.
