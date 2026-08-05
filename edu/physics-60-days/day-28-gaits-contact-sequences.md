# Day 28: Gaits and Contact Sequences

## Mental model

A **gait** is a repeating schedule of which feet support the body (**stance**) and which move to a new location (**swing**). Contact is not a boolean property of the whole robot. Each foot enters and leaves contact at a phase within a cycle. The schedule changes the support region, available traction, body oscillation, and how much force each stance foot must provide.

The **duty factor** is the fraction of a gait cycle a particular foot spends in stance. Slow walks commonly have overlapping support and higher duty factors; a trot often pairs diagonal feet and can include smaller support regions or brief flight, depending on speed and controller.

## Quantities, units, and assumptions

- Gait period `T`: seconds (`s`).
- Frequency `f = 1/T`: hertz (`Hz`).
- Stance time `t_stance`: seconds (`s`).
- Duty factor `beta = t_stance/T`: dimensionless.
- Foot force `F`: newtons (`N`).
- Impulse `integral(F dt)`: newton seconds (`N s`).

We use an ideal periodic level gait at steady average height and speed. Real contact transitions are compliant, terrain changes timing, and Sport adapts the schedule.

## Core equations

```text
f = 1/T
beta = t_stance/T

steady vertical impulse over one cycle:
sum_over_feet integral_0^T(F_z,i dt) approximately m g T
```

Average vertical force equals weight over a steady cycle, but instantaneous forces can be much larger or smaller. A foot contributes zero ground force while in swing.

## ASCII diagram

```text
time ->        0          T/2          T

FL stance      [==========]............
RR stance      [==========]............   diagonal pair A
FR stance      ............[==========]
RL stance      ............[==========]   diagonal pair B

"=" stance/contact       "." swing
idealized alternating trot; real transitions may overlap
```

## Worked Parcel / Go2 example

**These values describe an illustrative teaching gait, not a Go2 command or vendor specification.** Let assembled mass be `18 kg`, gait period `T = 0.50 s`, and an ideal alternating-diagonal trot give each foot `t_stance = 0.25 s`, so `beta = 0.50`.

The required total vertical impulse per cycle is:

```text
J_z,total approximately m g T
          = 18 kg * 9.81 m/s² * 0.50 s
          = 88.3 N s
```

If the two diagonal pairs share the cycle equally and each pair has two equally loaded feet, each foot contributes roughly one quarter of the cycle impulse: `22.1 N s`. Spread across its `0.25 s` stance, its average stance force is about `88.3 N`. Impact transients and body vertical acceleration make peak force larger. The calculation cannot select a safe gait; it only checks impulse accounting.

## Software-engineering analogy

A gait is a periodic distributed schedule with changing quorum membership. Stance feet are active workers holding a hard invariant; swing feet are temporarily unavailable and being repositioned. Duty factor resembles utilization, while touchdown is a state transition that can fail or arrive early.

## Parcel / Go2 bridge

Unitree Sport owns gait choice, contact timing, foot placement, and rapid balance correction. Parcel requests a bounded body twist and supervises measured progress, tilt, freshness, and faults. A simulator’s decorative leg animation is not evidence that contact impulses, motor effort, or stability are realistic.

Companion reading: [Rigid-body dynamics, contact, and friction](../robotics-60-days/day-17-rigid-body-dynamics-contact.md), [Unitree Sport nested loop](../robotics-60-days/day-20-synthesis-unitree-sport-nested-loop.md), and [What a simulator computes](../robotics-60-days/day-36-what-simulator-computes.md).

## Failure and safety note

A simulator moves the base kinematically while feet animate out of phase. Navigation metrics look smooth, but the animation supplies neither supporting impulse nor traction evidence. On hardware, a premature gesture changes loading during swing and triggers a stumble. Never blend unverified joint theatre into an active Sport gait.

## Retrieval questions

1. What does duty factor measure for one foot?
2. Why can average vertical force equal weight while peak foot force is much higher?
3. Which gait responsibilities belong to Sport rather than Parcel’s voice or navigation layer?

## Optional 10-minute exercise

Draw contact timelines for a four-beat walk and the idealized trot above. Compute duty factor for each foot. Then change the teaching trot to `T = 0.40 s` with the same `beta`; calculate stance time and total vertical impulse per cycle.
