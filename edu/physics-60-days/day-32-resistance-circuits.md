# Day 32: Resistance and Circuits

## Mental model

Resistance relates voltage difference to current in the simplest circuit model. Wires and connectors are not perfect: their resistance causes voltage drop and turns electrical power into heat. Circuit topology matters too. Components in series carry the same current; parallel branches share terminal voltage and draw currents that add at a node.

Kirchhoff’s laws are conservation rules. Current cannot disappear at a junction, and energy per charge must balance around a closed loop. They are the circuit equivalents of accounting invariants.

## Quantities, units, and assumptions

- Resistance `R`: ohms (`ohm = V/A`).
- Voltage `V`: volts (`V`).
- Current `I`: amperes (`A`).
- Electrical power `P`: watts (`W`).

Assume steady DC and ohmic elements whose resistance is constant. Real motors, converters, batteries, speakers, and protection circuits are nonlinear or time-varying. Wire resistance rises with length and often with temperature.

## Core equations

```text
Ohm's law:                  V = I R
resistive heating:          P = V I = I² R = V²/R

Kirchhoff current law:      sum(I entering node) = sum(I leaving)
Kirchhoff voltage law:      sum(Delta V around loop) = 0

series resistors:           R_eq = R1 + R2 + ...
parallel resistors:         1/R_eq = 1/R1 + 1/R2 + ...
```

Use `V = IR` only for the element whose voltage, current, and resistance you have defined.

### Capacitors, inductors, and transients

Resistance describes dissipation, but circuits also store field energy. A **capacitor** stores energy in an electric field and resists an instantaneous change in its terminal voltage. An **inductor** stores energy in a magnetic field and resists an instantaneous change in its current:

```text
capacitor: i = C dV/dt       E_C = (1/2) C V²
inductor:  V = L dI/dt       E_L = (1/2) L I²
```

Capacitance `C` is measured in farads (`F`); inductance `L` is measured in henries (`H`). Local **decoupling capacitors** can supply a short current transient and reduce a payload’s immediate supply dip, but they are not extra batteries. Motor windings and long power paths are inductive. When a controller switches their current, stored magnetic energy needs an engineered path; otherwise a large voltage transient can damage electronics or inject noise. These time-dependent effects explain why a steady `V = IR` calculation can pass while a walking robot still resets or corrupts audio.

## ASCII diagram

```text
 source + ---- R_wire ----+---- load A ----+
                          |                |
                          +---- load B ----+---- source -
                              parallel

same branch: same current
same two nodes: same voltage
wire resistance: drop + heat before loads
```

## Worked Parcel / Go2 example

**These illustrative values describe an imaginary circuit, not the Go2 power bus.** A `12 V` source supplies a load drawing `4.0 A` through cable and connector resistance totaling `0.15 ohm`:

```text
wire drop = I R = 4.0 A * 0.15 ohm = 0.60 V
load terminal voltage = 12.0 V - 0.60 V = 11.4 V
wire heat = I² R = (4.0 A)² * 0.15 ohm = 2.4 W
```

If current briefly doubles to `8 A`, voltage drop doubles to `1.2 V`, but heating becomes `9.6 W`—four times larger. This square-law explains why a marginal connector can become hot during actuator or compute bursts even when average operation looks fine.

## Software-engineering analogy

Kirchhoff current law resembles flow conservation at a message-router node. Voltage drop resembles backpressure or lost budget along an imperfect link. `I²R` heating is a nonlinear operational cost: doubling traffic can quadruple one infrastructure burden.

## Parcel / Go2 bridge

A retrofit needs a documented power tree: battery/vendor output, fuse or protection, converters, branch connectors, cable gauges, grounding, and peak loads. The voice/audio path may be logically independent but electrically coupled through shared supply impedance. Motor-current bursts can sag compute or inject noise. Separate software processes do not imply separate physics.

Companion reading: [Electricity, batteries, power, and heat](../robotics-60-days/day-05-electricity-batteries-power-heat.md) and [Real-time and distributed failure](../robotics-60-days/day-33-realtime-distributed-failure.md).

## Failure and safety note

A desktop prototype works with a short cable. The robot retrofit uses a thinner, longer extension; transient current creates extra drop, the compute node resets, and a stale motion lease survives until its watchdog. Never solve repeated brownouts by bypassing protection or installing a larger fuse without engineering the load path. Use qualified components and measure terminal voltage and temperature under an approved procedure.

## Retrieval questions

1. Why does doubling current quadruple resistive heating?
2. What is conserved at an electrical node under Kirchhoff’s current law?
3. How can a shared supply couple motor activity into voice-compute reliability?

## Optional 10-minute exercise

For an imaginary `5 V`, `2 A` load, calculate voltage drop and cable heating for `0.05`, `0.10`, and `0.25 ohm` round-trip resistance. Repeat at `4 A`. Use a spreadsheet only; do not modify robot wiring.
