# Day 12: Free-Body Diagrams

## Mental model

A free-body diagram isolates one physical system and draws every external force acting on it. It is a debugging tool for mechanics. Before writing equations, draw the body, axes, and forces. Missing or double-counted forces become visible.

For a whole robot standing on the floor, gravity pulls downward and the floor applies ground-reaction forces through the feet. Joint forces are internal to that whole-system boundary. If you isolate one leg instead, forces and torques at its joints cross the boundary and must appear.

An arrow represents a force acting **on** the isolated body, not a motion command and not necessarily the direction of motion.

## Quantities, units, and assumptions

Each force arrow needs:

- Point or region of application.
- Direction and sign convention.
- Magnitude in newtons, known or unknown.
- Source: gravity, contact, cable, aerodynamic drag, and so on.

Choose axes that simplify the problem. On a slope, axes parallel and perpendicular to the surface are often easier than horizontal and vertical.

State assumptions: static or accelerating, level or inclined floor, how many stance feet, rigid or compliant contact, and whether air drag is negligible. “Standing still” implies zero acceleration but does not mean no forces.

## Core equations

After drawing the diagram, apply:

~~~text
ΣF_x = ma_x
ΣF_y = ma_y
ΣF_z = ma_z
~~~

For static translational equilibrium:

~~~text
ΣF = 0
~~~

Rotational equilibrium also requires zero net torque, introduced more fully on Days 19–20:

~~~text
Στ = 0
~~~

A diagram is incomplete if the equations require a “mystery force” that has no physical interaction.

## ASCII diagram

~~~text
               whole dog boundary
             +-------------------+
             |       body        |
             +-------------------+
               ↓ W = mg
        ↑N₁   ↑N₂   ↑N₃   ↑N₄
       foot  foot  foot  foot
   ───────────────────────────── floor

 horizontal contact forces would be drawn at the feet
~~~

## Worked Parcel / Go2 example

Assume, illustratively, a 16 kg dog-plus-payload standing motionless on a level floor. Its weight magnitude is approximately:

~~~text
W = mg = (16 kg)(9.81 m/s²) ≈ 157 N
~~~

Static vertical equilibrium requires:

~~~text
N₁ + N₂ + N₃ + N₄ ≈ 157 N
~~~

If the center of mass were perfectly centered and the geometry symmetric, a crude estimate would be about 39 N per foot. A real quadruped rarely shares load exactly equally: posture, payload position, calibration, compliance, and gait phase shift forces. These values are illustrative and not commissioned Go2 loads or limits.

The diagram shows why adding a computer near the rear changes more than total mass. It moves the center of mass and therefore changes the normal-force distribution even while total upward force still balances weight.

## Software-engineering analogy

A free-body diagram resembles a dependency graph scoped to one service. Internal function calls disappear at the service boundary; only external inputs and outputs remain. Changing the boundary changes which interactions are visible.

Writing equations before the diagram resembles debugging from aggregate CPU alone. You may obtain a number, but you cannot attribute it correctly.

## Parcel / Go2 bridge

Parcel primarily commands high-level motion, but payload, tilt, foot-force, and stop telemetry are easier to interpret with a free-body model. Unitree Sport handles contact control; application engineers still need to recognize when a mounting change, slope, or loss of a stance contact invalidates an outer-loop assumption.

Companion reading: [Robotics Day 17 — Rigid-Body Dynamics, Contact, and Friction](../robotics-60-days/day-17-rigid-body-dynamics-contact.md).

## Failure and safety note

Never place hands or tools under a powered or merely standing robot to “feel” load distribution. It can change posture or collapse without warning. Use the vendor-safe unpowered state, approved stands, and rated lifting/support equipment for physical inspection.

## Retrieval questions

1. Why do joint forces disappear from a whole-dog free-body diagram?
2. Does standing still imply every force is zero? Explain.
3. What changes in the diagram when the system boundary shrinks to one leg?

## Optional 10-minute exercise

Draw free-body diagrams for: a book on a desk, the whole robot on level ground, and one robot foot during stance. Label all known units and circle every assumption. This is an unpowered paper exercise.
