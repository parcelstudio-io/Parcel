# Day 31: Charge, Current, and Voltage

## Mental model

Electric **charge** is a conserved physical quantity. **Current** is the rate at which charge crosses a boundary. **Voltage** is electric potential-energy difference per unit charge. A voltage can exist with no current, just as pressure difference can exist behind a closed valve. Current flows only when a circuit provides a path and its components respond to the applied voltage.

For a robot, voltage describes the electrical “height” available across a device; current describes how quickly charge is moving through its branch. Their product is electrical power. Neither number alone describes the load.

## Quantities, units, and assumptions

- Charge `q`: coulombs (`C`). One coulomb is one ampere-second.
- Current `I`: amperes (`A = C/s`).
- Voltage `V`: volts (`V = J/C`).
- Energy `E`: joules (`J`).
- Power `P`: watts (`W = J/s`).

We begin with a lumped, direct-current circuit: wires are treated as ideal connections and voltage/current are summarized at component terminals. Real wiring has resistance and inductance; converters switch rapidly; motor phases carry changing current.

## Core equations

```text
current:               I = dq/dt
voltage difference:    Delta V = Delta E / q
electrical power:      P = V I
energy over time:      E = integral(P dt)

for constant current and power:
q = I t
E = V I t
```

Current is not “used up”; charge entering a steady component also leaves it. Energy is transformed into computation, sound, motion, or heat.

## ASCII diagram

```text
          current I ->
    +  ------------------- [ load ] --------+
  source V                                    |
    -  <--------------------------------------+

voltage: energy difference per charge
current: charge per second around closed path
load: converts electrical energy to another form
```

## Worked Parcel / Go2 example

**The values below are illustrative and are not ratings for Parcel, Go2, or a specific USB device.** Suppose a small computer peripheral receives `5.0 V` and draws `0.50 A` steadily:

```text
P = V I = 5.0 V * 0.50 A = 2.5 W

over 10 s:
q = I t = 0.50 A * 10 s = 5.0 C
E = P t = 2.5 W * 10 s = 25 J
```

The source does not “push 10 A into” this load merely because it is capable of supplying up to 10 A. With compatible voltage, the circuit and load determine the current; the source rating says what it can provide within conditions. Faults can still draw dangerous current, which is why protection matters.

## Software-engineering analogy

Voltage is analogous to energy available per request, while current is request throughput. Capacity and demand are different: a server able to handle 10,000 QPS does not force every client to send that rate. Power is the actual burn rate—energy per second.

## Parcel / Go2 bridge

Parcel combines actuator, compute, sensing, radio, and future audio loads. Every branch must declare required voltage, typical and peak current, connector, polarity, conversion path, and power-source authority. Application software should consume normalized battery/power state rather than infer electrical health from one raw voltage.

Companion reading: [Electricity, batteries, power, and heat](../robotics-60-days/day-05-electricity-batteries-power-heat.md) and [Typed hardware and controller boundaries](../robotics-60-days/day-31-typed-hardware-controller-boundaries.md).

## Failure and safety note

A developer sees that two devices both use USB-C connectors and assumes their power requirements are interchangeable. Connector shape does not prove voltage negotiation, current capability, cable rating, or data support. A wrong power path can damage hardware or start a fire. Do not probe, open, charge, or modify the Go2 battery as a course exercise; follow official vendor documentation and qualified electrical procedures.

## Retrieval questions

1. What physical rate does one ampere represent?
2. Why can voltage exist when current is zero?
3. What additional facts are needed beyond “it uses USB-C” before connecting a payload?

## Optional 10-minute exercise

For an imaginary `9 V`, `0.30 A` device, calculate power, charge moved in two minutes, and energy in joules. Then write a typed payload-power record containing voltage, typical current, peak current, connector, and source. Do not connect any hardware.
