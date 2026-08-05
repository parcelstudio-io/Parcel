# Day 33: Fields and Electromagnetism

## Mental model

An electric or magnetic **field** assigns an interaction tendency to every point in space. Charge responds to electric fields. Moving charge—current—creates and responds to magnetic fields. Motors exploit the resulting force; generators and motor back EMF exploit the reverse relationship, where changing magnetic flux induces voltage.

Fields also explain interference. High, rapidly changing motor and converter currents create electric and magnetic disturbances that can couple into sensor, radio, and audio wiring. “Separate software component” does not mean electromagnetically isolated component.

## Quantities, units, and assumptions

- Electric field `E`: volts per metre (`V/m`) or newtons per coulomb (`N/C`).
- Magnetic flux density `B`: teslas (`T`).
- Wire length vector `L`: metres (`m`).
- Magnetic flux per turn `Phi_per_turn`: webers (`Wb`).
- Induced voltage: volts (`V`).

We use uniform-field and ideal-coil sketches. Real motors have distributed windings, permanent magnets, switching controllers, iron saturation, eddy-current loss, and three-dimensional geometry.

## Core equations

```text
electric force on charge:       F = q E
magnetic force on moving charge:F = q (v cross B)
force on current-carrying wire: F = I (L cross B)
Faraday induction for N equal turns: V_induced = -N d(Phi_per_turn)/dt
```

The cross product means magnetic force is perpendicular to current and field. The minus sign in Faraday’s law expresses opposition to the flux change, an energy-conservation result.

Magnetic flux through one turn is the field passing through its oriented area, `Phi_per_turn = integral(B dot dA)`. Changing field strength, coil area, or orientation can therefore induce voltage. If turns do not share the same flux, the general law uses the derivative of total flux linkage rather than simply multiplying one flux by `N`. Coupling also depends on geometry and frequency: separating conductors, reducing loop area, and avoiding long parallel runs can matter as much as a software filter.

## ASCII diagram

```text
 magnetic field into page:  x x x x x

 current I upward                 force F left
       ^                                  <---
       | wire
       |

current + magnetic field -> sideways force -> motor torque
changing flux through coil -> induced voltage
```

## Worked Parcel / Go2 example

**The values are illustrative classroom values, not measurements of a Go2 motor.** Consider a coil with `N = 20` turns whose flux through each turn changes by `0.0005 Wb` over `0.010 s`:

```text
|V_induced| approximately N * Delta Phi / Delta t
            = 20 * 0.0005 Wb / 0.010 s
            = 1.0 V
```

That induced voltage is the same physical family as motor back EMF and inductive transients. A motor controller deliberately switches current through coils to produce torque; sudden interruption of current can create a voltage that must be handled by the driver circuitry. The simplified result does not size protection components.

## Software-engineering analogy

A field resembles an ambient function over space: a component can be affected without a direct logical call edge. Electromagnetic coupling is a hidden shared dependency, like contention through a cache or network fabric omitted from a service diagram.

## Parcel / Go2 bridge

Unitree’s motor drives and Sport controller own actuator commutation and fast control. Parcel interfaces above them. For future audio hardware, physical integration should route low-level microphone signals, USB data, antenna paths, and motor power with electromagnetic compatibility in mind. Shielding and grounding must follow hardware guidance; they are not prompt settings.

Companion reading: [Motors, gearing, and actuator modes](../robotics-60-days/day-07-motors-gearing-actuator-modes.md), [Proprioception](../robotics-60-days/day-08-proprioception.md), and [Full-duplex conversation](../robotics-60-days/day-43-full-duplex-barge-in.md).

## Failure and safety note

A microphone cable is bundled tightly beside a high-current switched motor cable. Speech quality degrades only while walking, so the issue is misdiagnosed as ASR latency. The actual fault is physical coupling. Do not open motor controllers, probe high-current conductors, or improvise shielding connections; poor grounding can worsen interference or create a safety hazard.

## Retrieval questions

1. How can a magnetic field exert force on a current-carrying wire?
2. What does Faraday’s law say happens when magnetic flux changes?
3. Why can motor operation affect audio without any software dependency?

## Optional 10-minute exercise

Draw a motor-power wire and a microphone/data cable in three routing arrangements: parallel and close, crossing at right angles, and separated. Predict relative coupling qualitatively. Optionally move a small permanent magnet near a compass, away from electronics and the robot, to visualize a field direction.
