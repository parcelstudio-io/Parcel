# Day 36: Batteries and Stored Energy

## Mental model

A battery is an electrochemical energy source, not an ideal voltage constant. Chemical reactions maintain an open-circuit voltage; internal resistance and reaction limits make terminal voltage sag under current. Capacity describes stored charge, while watt-hours better estimate stored electrical energy. Neither number alone predicts safe runtime.

Cells are combined in series to raise pack voltage and in parallel to raise charge/current capacity. A battery-management system (BMS) supervises cell voltage, current, temperature, balancing, and protective cutoffs. Software state of charge is an estimate influenced by current history, voltage, temperature, age, and the cell model.

## Quantities, units, and assumptions

- Cell or pack voltage `V`: volts (`V`).
- Current `I`: amperes (`A`).
- Capacity: ampere-hours (`Ah`), a unit of charge.
- Energy: watt-hours (`Wh`) or joules (`J`); `1 Wh = 3600 J`.
- Internal resistance `R_internal`: ohms (`ohm`).
- State of charge (`SoC`): percent or fraction, model-dependent.

We use a constant nominal voltage and lumped internal resistance. Real discharge curves are nonlinear; usable capacity changes with rate, temperature, cutoff, health, and cell balance.

## Core equations

```text
planning energy estimate: E_Wh approximately V_nominal * capacity_Ah
loaded terminal voltage during discharge (I > 0):
                          V_load approximately V_open - I R_internal
internal heating:         P_loss approximately I² R_internal
idealized runtime:        t_hours approximately usable_Wh / average_W

series:   matched-cell voltages add; Ah rating does not
parallel: matched-cell Ah ratings add; voltage does not
          (only in a protected pack designed for that connection)
```

Do not use these equations to assemble or modify a pack.

## ASCII diagram

```text
ideal chemical source V_open ---- R_internal ---- robot load
                                  |                I ->
                                  +-- sag + heat

resting voltage can look healthy
high current -> lower terminal voltage -> BMS/converter cutoff risk
```

## Worked Parcel / Go2 example

**This is an imaginary pack, not a Go2 battery specification or runtime claim.** Suppose a nominal `24 V`, `10 Ah` pack has planning energy:

```text
E_nominal = 24 V * 10 Ah = 240 Wh
```

If a conservative teaching assumption makes only `70%` available to a mission, usable energy is `168 Wh`. At an illustrative `120 W` average load, idealized runtime is `1.4 h`. That omits reserve policy, converter losses, temperature, aging, and variable locomotion.

Now assume lumped internal resistance `0.08 ohm` and a `20 A` burst:

```text
voltage sag = 20 A * 0.08 ohm = 1.6 V
internal heat = 20² * 0.08 = 32 W
```

The burst can trigger a cutoff or brownout while resting voltage and displayed percentage still look acceptable.

## Software-engineering analogy

Battery energy resembles a storage quota; current capability resembles burst IOPS; terminal voltage resembles service quality under load. SoC is an estimate from imperfect telemetry, not a transactionally correct counter. BMS cutoff is a kernel-enforced circuit breaker.

## Parcel / Go2 bridge

Parcel already models battery state as a typed runtime input with low and critical policies. Hardware integration should replace simulated percentage with a validated vendor state source and preserve fail-safe behavior. Mission planning must budget locomotion plus compute, sensing, radio, and future audio—not bolt payload watts onto a runtime estimate afterward.

Companion reading: [Electricity, batteries, power, and heat](../robotics-60-days/day-05-electricity-batteries-power-heat.md), [Safety engineering](../robotics-60-days/day-35-safety-engineering.md), and [Voice to safe motion](../robotics-60-days/day-50-synthesis-voice-to-safe-motion.md).

## Failure and safety note

A follow mission begins at a reassuring displayed SoC. An uphill torque burst coincides with GPU inference, voltage sags, and the compute node resets. Treat low voltage, overcurrent, temperature, or BMS faults as motion-safety events. Never open, puncture, parallel, charge with an unapproved charger, or alter a robot battery.

## Retrieval questions

1. What is the difference between ampere-hours and watt-hours?
2. Why can loaded terminal voltage be much lower than resting voltage?
3. Why is SoC a state estimate rather than direct ground truth?

## Optional 10-minute exercise

For an imaginary `18 V`, `8 Ah` pack, calculate nominal Wh and joules. Estimate runtime at `60`, `120`, and `240 W` using an illustrative `75%` usable fraction. Then calculate sag at several currents for `0.10 ohm`. Do not touch a battery.
