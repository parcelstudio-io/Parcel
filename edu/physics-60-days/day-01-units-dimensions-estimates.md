# Day 01: Units, Dimensions, and Estimates

## Mental model

Units are runtime types for the physical world. Metres and seconds may both be stored as floating-point numbers, but adding them is meaningless. Dimensional analysis catches whole classes of robotics bugs before simulation: millimetres parsed as metres, degrees passed as radians, milliseconds treated as seconds, or watt-hours confused with watts.

An estimate is equally important. Before running a detailed model, calculate an order of magnitude. If code predicts that a companion-size robot stops in 20 m from walking speed or consumes one joule during a long mission, the implementation is wrong or its assumptions are wildly inappropriate.

Use SI internally and convert once at a boundary. Names such as distance_m, speed_mps, and timeout_s make implicit types visible.

## Quantities, units, and assumptions

The most useful SI base units here are:

| Quantity | Unit | Symbol |
| --- | --- | --- |
| length | metre | m |
| mass | kilogram | kg |
| time | second | s |
| electric current | ampere | A |
| temperature | kelvin | K |

Common derived units are:

~~~text
velocity       m/s
acceleration   m/s²
force          newton, N = kg·m/s²
energy         joule, J = N·m
power          watt, W = J/s
torque         N·m
voltage        volt, V = W/A
~~~

Torque and energy both reduce to N·m dimensionally, but they are different physical concepts and must not be interchanged. Angles in radians are dimensionless ratios, yet retaining “rad” in names prevents dangerous degree/radian mistakes.

Prefixes matter: milli is 10⁻³, centi is 10⁻², kilo is 10³, and mega is 10⁶. A 20 ms delay is 0.020 s.

## Core equations

~~~text
v = d/t                 [m/s]
a = Δv/Δt              [m/s²]
F = m a                [kg·m/s²] = [N]
E = F d                [N·m] = [J]
P = E/t                [J/s] = [W]
~~~

For an order-of-magnitude estimate, round inputs to one significant digit, compute, and ask whether the scale is plausible. Precision should reflect evidence. Writing 0.487213 m from a sensor accurate only to centimetres invents confidence.

## ASCII diagram

~~~text
 raw number → attach unit → attach frame → attach uncertainty
    500         500 mm       body x          ±5 mm
                   │
                   ▼ convert once
                0.500 m

 dimensional check: (m/s) × s = m  ✓
~~~

## Worked Parcel / Go2 example

Assume, illustratively, a 16 kg dog-plus-payload moving at 0.60 m/s. Its kinetic energy estimate is:

~~~text
E = ½ m v²
  = 0.5(16 kg)(0.60 m/s)²
  = 2.88 kg·m²/s²
  = 2.88 J
~~~

At 1.20 m/s, the estimate becomes 11.52 J, four times larger because speed is squared. These are teaching values, not Go2 operating limits. The important review insight is that doubling a speed cap changes impact energy much more than a dashboard slider suggests.

Suppose a configuration mistakenly interprets 600 mm/s as 600 m/s. An order-of-magnitude check immediately rejects it: that is aircraft-scale speed, not companion walking speed.

## Software-engineering analogy

Using bare floats for physical values is like using strings for both HTML and database identifiers. The representation is compatible while the semantics are not. Unit suffixes are lightweight nominal types; parse-time validation and strongly typed quantity libraries are stronger ones.

Dimensional analysis resembles static type checking. Estimation resembles a capacity sanity check before load testing. Both are inexpensive filters, not substitutes for integration evidence.

## Parcel / Go2 bridge

Parcel motion contracts distinguish metres per second from radians per second, and timestamps determine whether a measurement is fresh enough to use. Configuration values should expose units in their names and document frames. Conversion from a vendor representation belongs in one adapter, not scattered through behavior and navigation code.

Companion reading: [Robotics Day 02 — Units and Dimensional Analysis](../robotics-60-days/day-02-units-dimensional-analysis.md).

## Failure and safety note

A unit error at an actuator boundary can create violent motion. Reject non-finite values, unknown units, and unreasonable magnitudes before commands reach hardware. Do not “test which unit it meant” on a powered robot. Confirm the vendor contract and first validate with logs, mocks, or simulation.

## Retrieval questions

1. Express a newton and a watt in SI base or derived units.
2. Why are torque and energy not interchangeable even though both have dimensions N·m?
3. What happens to kinetic energy when speed doubles while mass stays fixed?

## Optional 10-minute exercise

Convert 750 mm, 35 ms, and 45 degrees into metres, seconds, and radians. Then audit five numeric motion or timing names in Parcel and note whether each exposes its unit and frame. Use no powered hardware.
