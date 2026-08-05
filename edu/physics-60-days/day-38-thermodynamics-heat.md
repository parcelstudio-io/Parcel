# Day 38: Thermodynamics and Heat Transfer

## Mental model

Temperature describes thermal state; **heat** is energy transferred because of a temperature difference. Electrical and mechanical inefficiency becomes heat. A component’s temperature rises according to both how much heat it stores and how quickly heat can leave by conduction, convection, and radiation.

Thermal problems have timescales. A motor can tolerate a brief burst because its thermal mass delays temperature rise, yet overheat under a smaller sustained load. An enclosed computer can pass a one-minute test and throttle after twenty minutes. Steady temperature and transient temperature are different questions.

## Quantities, units, and assumptions

- Temperature `T`: kelvin (`K`) or degrees Celsius (`deg C`) for differences.
- Heat/thermal energy `Q`: joules (`J`).
- Heat flow `Q_dot`: watts (`W`).
- Specific heat `c_p`: `J/(kg K)`.
- Thermal resistance `R_theta`: `K/W`.
- Thermal capacitance `C_theta = m c_p`: `J/K`.

We use lumped temperatures and constant properties. Real robots have multiple heat sources, contact resistances, airflow paths, hot spots, controller derating, and temperature-dependent losses.

A temperature *difference* of one degree Celsius equals one kelvin, so either can describe `Delta T`; formulas involving absolute thermodynamic temperature require kelvin. Always distinguish ambient, case, junction, winding, and battery-cell temperature because they are different physical nodes.

## Core equations

```text
sensible heat:              Q = m c_p Delta T
first-order thermal model:  C_theta dT/dt
                            = P_loss - (T - T_ambient)/R_theta
initial heating rate:       dT/dt approximately P_loss/(m c_p)
steady thermal rise:        Delta T approximately P_loss R_theta
simple conduction:          Q_dot = k A Delta T / L
thermal time constant:      tau_theta approximately R_theta C_theta
```

Every term in the first-order model has units of watts: `(J/K)(K/s) = W`. Convection depends strongly on airflow and geometry; radiation grows nonlinearly with absolute temperature.

## ASCII diagram

```text
 electrical/mechanical loss P
              |
              v
         [ hot component ] -- conduction --> chassis
              |  \
              |   +-- radiation --> surroundings
              +------ convection --> moving air

thermal mass slows rise; thermal resistance sets steady rise
```

## Worked Parcel / Go2 example

**These illustrative values describe an imaginary payload enclosure, not a measured product.** A compute module dissipates `20 W`. Suppose its effective thermal resistance to ambient is `2.0 K/W`:

```text
steady rise estimate = 20 W * 2.0 K/W = 40 K
```

At `25 deg C` ambient, that crude model predicts `65 deg C` at the modeled node. If `0.50 kg` of nearby aluminum with `c_p approximately 900 J/(kg K)` initially absorbs the heat and none escapes:

```text
C_theta = 0.50 * 900 = 450 J/K
initial dT/dt = 20/450 approximately 0.044 K/s
              approximately 2.7 K/min
tau_theta = (2.0 K/W)(450 J/K) = 900 s = 15 min
```

Heat soon begins leaving, so the initial slope does not continue linearly. The example explains why both a cold-start transient and long soak test matter.

## Software-engineering analogy

Thermal capacitance is buffering; thermal resistance is drain throughput. A short benchmark can fit in the buffer while a sustained workload saturates it. Thermal throttling is physical backpressure, not random performance noise.

## Parcel / Go2 bridge

Power, temperature, model latency, and motion should be correlated in telemetry. Rising compute temperature may increase reasoning latency through clock throttling; hot motors may reduce available gait torque. Behavior planning must not interpret either slowdown as stubbornness. Payload commissioning needs soak tests in representative ambient temperature and airflow, with vendor limits and automatic safe degradation.

Companion reading: [Electricity, batteries, power, and heat](../robotics-60-days/day-05-electricity-batteries-power-heat.md), [Observability and latency](../robotics-60-days/day-39-observability-latency.md), and [Reality gap](../robotics-60-days/day-37-reality-gap.md).

## Failure and safety note

A sealed-looking enclosure protects electronics from fingers but traps heat. The desktop test passes with a fan nearby; the mounted robot’s airflow differs and compute throttles during navigation. Never assume touch-safe or component-safe temperatures from this lumped example. Use rated sensors and limits, avoid contact with hot hardware, and stop if temperature telemetry is missing or implausible.

## Retrieval questions

1. What is the difference between heat and temperature?
2. Which parameter controls initial temperature rise, and which controls a simple steady rise?
3. How can temperature affect voice and navigation latency?

## Optional 10-minute exercise

In a spreadsheet, simulate a first-order thermal model with `R_theta = 2 K/W`, `C_theta = 450 J/K`, ambient `25 deg C`, and losses of `10`, `20`, and `30 W`. Plot 30 minutes. This is a model exercise, not permission to heat hardware.
