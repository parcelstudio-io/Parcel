# Day 21: Rotational Inertia

## Mental model

Mass resists linear acceleration. **Rotational inertia**—also called moment of inertia—resists angular acceleration. It depends on both how much mass an object has and how far that mass lies from the chosen rotation axis. Moving a payload outward can therefore change turning and balance behavior even when total mass is unchanged.

This is the first question to ask about a new computer, battery, or audio enclosure on Parcel: not only “how heavy is it?” but also “where is it relative to the roll, pitch, and yaw axes?” A high payload increases its distance from the roll and pitch axes; a forward payload especially increases pitch and yaw inertia. Every claim is axis-specific. Unitree Sport closes the fast balance loop, but it cannot repeal the changed plant physics.

## Quantities, units, and assumptions

- Mass `m`: kilograms (`kg`).
- Perpendicular distance to an axis `r`: metres (`m`).
- Rotational inertia `I`: `kg m²`.
- Torque `tau`: newton metres (`N m`).
- Angular acceleration `alpha`: radians per second squared (`rad/s²`).

We first model payloads as point masses and the chassis as a rigid body. Real brackets flex, wiring moves, and the Go2 has articulated legs. The chosen axis must always be named: inertia about yaw is not inertia about pitch.

## Core equations

```text
point masses about an axis:       I = sum(m_i r_i²)
fixed-axis, constant-I form:      sum(tau) = I alpha
parallel-axis theorem (parallel axes): I_axis = I_CoM + m d²
rotational kinetic energy:        K_rot = (1/2) I omega²
```

The square on `r` matters. Double the distance and that mass contributes four times the inertia.

## ASCII diagram

```text
                 2 kg payload
                       *
                       | r = 0.25 m
 pitch axis  ----------O----------> body x
                       |
                    chassis

 same payload at r = 0.05 m: small contribution
 same payload at r = 0.25 m: 25 times that contribution
```

## Worked Parcel / Go2 example

**All numbers here are illustrative, not Go2 limits or measured inertias.** Suppose a `2.0 kg` compute/audio payload is first mounted `0.05 m` from a pitch axis, then moved to `0.25 m` away. Treat it as a point mass:

```text
I_near = 2.0 kg * (0.05 m)² = 0.005 kg m²
I_far  = 2.0 kg * (0.25 m)² = 0.125 kg m²
ratio  = 25
```

For the same illustrative angular acceleration `alpha = 2 rad/s²`, the payload's idealized contribution to required torque would be:

```text
tau_near = I_near alpha = 0.010 N m
tau_far  = I_far  alpha = 0.250 N m
```

These are incremental payload terms, not total robot torque or a response prediction. The chassis, legs, contacts, controller, gravity, and other masses also contribute. The useful result is the ratio: the farther placement requires 25 times the payload-related torque contribution for the same angular acceleration.

## Software-engineering analogy

Total mass is like total database size; rotational inertia is like the cost of the access pattern. Two systems can contain the same bytes yet have very different latency because one scatters data across a slow boundary. `kg` alone is incomplete performance metadata. You need `kg m²` about a declared axis.

## Parcel / Go2 bridge

Parcel should continue to request bounded body motion through Unitree Sport. Payload layout becomes part of the physical robot profile and commissioning evidence, not an LLM-controlled parameter. A simulator model should place added masses at their real locations instead of merely increasing one chassis mass value. Otherwise yaw and tip responses can look falsely agile.

Companion reading: [Rotational mechanics and balance](../robotics-60-days/day-04-rotational-mechanics-balance.md) and [The reality gap](../robotics-60-days/day-37-reality-gap.md).

## Failure and safety note

A team validates a body gesture with the compute box centered, then moves the box forward to clear a sensor. The total mass check still passes, but pitch inertia and center of mass both change. The same transient now overshoots and approaches a tilt fault. Never infer hardware safety from this lesson’s point-mass estimate. Rebuild the mass model, follow a vendor-approved low-energy commissioning procedure in a controlled area, and keep an operator at the E-stop.

## Retrieval questions

1. Why can two robots with equal total mass have different yaw acceleration under equal torque?
2. What axis and unit must accompany every quoted moment of inertia?
3. Why is adding payload mass only to the chassis total insufficient in simulation?

## Optional 10-minute exercise

Use two coins or washers on a ruler. Without powering any robot, place them near the ruler’s center and then near its ends. Rotate the ruler gently by hand about its center and compare the feel. Calculate `sum(m r²)` for both layouts; explain why the outer layout resists angular acceleration more.
