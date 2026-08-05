# Day 17: Power and Efficiency

## Mental model

Energy tells how much physical change is possible; power tells how quickly energy is transferred. A robot may have enough battery energy for a task but lack the instantaneous power to climb, accelerate, run perception, and speak at the same time. Peak power and average power answer different design questions.

Efficiency is the fraction of input power that becomes useful output under a stated boundary. The rest is not lost from physics—it becomes heat, sound, vibration, radio emission, or another unwanted form. Efficiency varies with motor speed, torque, voltage, temperature, gearing, and gait.

Power couples software scheduling to hardware. Starting a large GPU inference during a current-heavy maneuver can increase voltage sag and thermal load even if both components work independently in a block diagram.

## Quantities, units, and assumptions

Power is measured in watts:

~~~text
1 W = 1 J/s
~~~

Relevant forms include:

- Mechanical translational power in W.
- Mechanical rotational power in W.
- Electrical power in W.
- Energy capacity in J or Wh.
- Efficiency η, dimensionless and between zero and one for ordinary conversion.

Always define input and useful output. “Motor efficiency” differs from battery-to-foot or battery-to-mission efficiency. Assume steady values only for a short estimate; walking power is strongly time varying.

## Core equations

~~~text
average power P = ΔE/Δt
translational power P = F · v
rotational power P = τω
electrical power P = VI
efficiency η = P_useful/P_input
P_input = P_useful/η
~~~

Dimensional checks:

~~~text
[N][m/s] = [J/s] = [W]
[V][A] = [W]
~~~

Average energy over a mission:

~~~text
E = integral of P dt
~~~

## ASCII diagram

~~~text
 battery power P_in
       |
       +--> compute + radio + audio
       |
       v
 electronics → motors → gears → feet → useful motion
       \________ losses at every stage ________/
                         ↓
                        heat
~~~

## Worked Parcel / Go2 example

Assume an illustrative 16 kg system gains height at 0.10 m/s. The minimum gravitational mechanical power is:

~~~text
P_useful = mgv_vertical
         = (16 kg)(9.81 m/s²)(0.10 m/s)
         ≈ 15.7 W
~~~

If a deliberately simplified end-to-end mechanical conversion efficiency were 50%:

~~~text
P_input_for_lift ≈ 15.7 W / 0.50 = 31.4 W
~~~

Compute, sensing, audio, horizontal gait work, balance, and losses add more. Real quadruped efficiency is not a single constant, and these teaching numbers are not Go2 power, climb, or runtime specifications.

A 200 W burst lasting 3 s uses 600 J, while 50 W sustained for 60 s uses 3,000 J. The burst may still be more likely to trigger a current or voltage limit.

## Software-engineering analogy

Energy is total compute quota; power is request rate. A service can fit within its daily quota and still overload a dependency during a burst. Thermal state resembles a rolling rate-limit window that remembers recent load.

Efficiency is end-to-end useful throughput divided by provisioned input. Moving work between services changes where loss appears, not whether the physical battery pays.

## Parcel / Go2 bridge

Parcel should observe latency, compute utilization, battery and thermal state together. Low battery behavior can reduce speed, defer nonessential perception, acknowledge the user, and seek a safe pose through typed policy. Unitree’s controller remains responsible for actuator-level constraints; the companion brain must not demand constant peak performance.

Companion reading: [Robotics Day 05 — Electricity, Batteries, Power, and Heat](../robotics-60-days/day-05-electricity-batteries-power-heat.md).

## Failure and safety note

Never estimate safe current, wire rating, battery runtime, or thermal headroom from a lesson efficiency. Use vendor electrical specifications and measured profiles. Do not open battery packs, probe live power connectors, or attach unapproved loads.

## Retrieval questions

1. How can a mission have sufficient energy but insufficient power?
2. Where does conversion inefficiency appear physically?
3. Why does average power fail to characterize a short high-current event?

## Optional 10-minute exercise

For illustrative loads of 40 W compute, 10 W audio, and 80 W average locomotion over 20 minutes, estimate total energy in Wh. Then add a 200 W, 5 s burst and compare its energy with its peak power.
