# Day 37: Robot Power Budgets

## Mental model

A power budget is a time-aware accounting model for every electrical and mechanical load. It distinguishes **average power**, which drives mission energy and long-term heat, from **peak coincident power**, which drives voltage sag, converter sizing, connector limits, and resets. Robot loads are heterogeneous: compute and sensors are fairly steady; locomotion and speakers are bursty; radios and inference can spike.

A credible budget traces power from the battery through protection and converters to each load, including conversion loss. It also specifies operating modes: standing, walking, climbing, speaking, heavy inference, degraded mode, and emergency stop.

## Quantities, units, and assumptions

- Power `P`: watts (`W`).
- Energy `E`: watt-hours (`Wh`) or joules (`J`).
- Converter efficiency `eta`: dimensionless.
- Current `I = P/V`: amperes (`A`) under a DC approximation.
- Duty cycle `D`: fraction of time a load is active.

We use mode averages and conservative coincidence factors. Real traces require instrumentation at the battery and branches. Nominal values from separate datasheets may not share the same test conditions.

## Core equations

```text
branch input power:       P_in = P_load / eta
mode average:             P_avg = sum(D_i P_i)
mission energy:           E = integral(P_total dt)
constant-mode estimate:   E approximately P_avg t
DC current estimate:      I approximately P/V
```

Peak total is not always the sum of every published peak, but assuming peaks never coincide is equally unsafe. Measure correlations.

## ASCII diagram

```text
 battery/BMS
     |
 protection + bus ----------------------+
     |             |          |         |
 actuators      compute     sensors    audio
 bursty         steady+GPU  steady     speech bursts

average sum -> energy + temperature
coincident peak -> sag + converter/cable/protection sizing
```

## Worked Parcel / Go2 example

**These are illustrative teaching loads, not measured Parcel or Go2 consumption.** Suppose one walking-and-talking mode contains:

```text
locomotion: 120 W average, 500 W short peak
compute:     35 W average,  55 W peak
sensors:     15 W average,  18 W peak
audio:        5 W average,  12 W peak
```

The simple average is `175 W`. A conservative fully coincident teaching peak is `585 W`. With the Day 36 imaginary `168 Wh` usable energy:

```text
idealized runtime = 168 Wh / 175 W approximately 0.96 h
```

That is not a deployment prediction: walking power changes with surface, gait, payload, slope, and speed; converter loss and reserve reduce runtime. If a `90%` efficient converter supplies the `35 W` compute load, its bus input is about `38.9 W`, not `35 W`.

## Software-engineering analogy

Average power is monthly cloud spend; coincident peak is admission-control capacity. Duty cycle is workload mix. Load shedding is graceful degradation: lower model rate or audio volume before compromising control, sensing freshness, watchdogs, or the safe-stop path.

## Parcel / Go2 bridge

Power modes should become observable state tied to latency metrics and behavior policy. Low battery may suppress expensive optional perception, shorten conversation, reduce speed, or command a safe posture—subject to an explicit priority order. Safety sensing, control communication, and stopping authority remain non-sheddable. Measure query latency alongside power so optimization does not quietly trade responsiveness for brownout risk.

Companion reading: [Electricity, batteries, power, and heat](../robotics-60-days/day-05-electricity-batteries-power-heat.md), [Observability and latency](../robotics-60-days/day-39-observability-latency.md), and [Open-weight model deployment](../robotics-60-days/day-49-open-weight-model-deployment.md).

## Failure and safety note

A design sums average values, selects a converter with no transient margin, and passes a stationary demo. During a climb, GPU first-token inference and a loud speech response coincide with motor load; voltage collapses. Budget operating modes and peaks, then validate with qualified instrumentation. Do not insert an unapproved meter or adapter into the robot power path.

## Retrieval questions

1. Which design questions are driven by average power versus peak power?
2. How does converter efficiency change the upstream budget?
3. Which Parcel loads should never be shed merely to keep conversation running?

## Optional 10-minute exercise

Create a spreadsheet with the four illustrative loads. Add standing, walking, climbing, silent, and speaking modes; assign duty cycles and compute mission Wh for 30 minutes. Mark every unmeasured value as an assumption rather than a fact.
