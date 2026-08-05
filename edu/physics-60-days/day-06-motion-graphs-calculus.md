# Day 06: Motion Graphs and Calculus Intuition

## Mental model

Calculus gives two complementary views of motion:

- A **derivative** asks how rapidly a quantity changes now.
- An **integral** accumulates many small changes over an interval.

On a position-versus-time graph, slope is velocity. On a velocity-versus-time graph, slope is acceleration and signed area is displacement. On an acceleration-versus-time graph, signed area is velocity change.

Robot software performs these operations on samples rather than perfect continuous functions. Differentiation magnifies noise; integration accumulates bias. That is why a small IMU bias can become a large position drift and why odometry needs correction from other sensors.

## Quantities, units, and assumptions

Let position x be in m, time t in s, velocity v in m/s, and acceleration a in m/s².

~~~text
v = dx/dt
a = dv/dt
Δx = integral of v dt
Δv = integral of a dt
~~~

A graph’s axis labels are part of the model. The area of a speed graph is distance only when speed is nonnegative; the signed area of a velocity graph is displacement.

For sampled data, assume samples have reliable timestamps. A nominal 20 Hz stream does not guarantee every interval is exactly 0.05 s.

## Core equations

Finite-difference derivative:

~~~text
v_k ≈ (x_k - x_(k-1)) / (t_k - t_(k-1))
~~~

Trapezoidal integration:

~~~text
Δx_k ≈ ½(v_(k-1) + v_k)(t_k - t_(k-1))
x_k ≈ x_(k-1) + Δx_k
~~~

Dimensional checks:

~~~text
[m]/[s] = [m/s]
[m/s] × [s] = [m]
~~~

Smaller sample intervals can reduce approximation error, but they do not remove sensor bias or timestamp mistakes.

## ASCII diagram

~~~text
position x              velocity v
  ^        /              ^       /|
  |      /  slope=v       |     /  | area=Δx
  |    /                  |___/____|____> t
  +----------> t                 Δt

differentiate: x → v → a
integrate:     a → v → x
~~~

## Worked Parcel / Go2 example

Assume illustrative measured velocities:

| time (s) | velocity (m/s) |
| ---: | ---: |
| 0.0 | 0.0 |
| 0.5 | 0.3 |
| 1.0 | 0.6 |

Using trapezoids:

~~~text
Δx₁ = ½(0.0 + 0.3)(0.5) = 0.075 m
Δx₂ = ½(0.3 + 0.6)(0.5) = 0.225 m
total ≈ 0.300 m
~~~

The average acceleration over the full second is 0.60 m/s². If every velocity sample had a +0.02 m/s bias, integrated position would accumulate +0.02 m of error each second. Over a minute that simple bias contributes 1.2 m.

These numbers are illustrative and not commissioned Go2 timing or motion limits.

## Software-engineering analogy

A derivative resembles the rate computed from a monotonically increasing metric; an integral resembles the cumulative count reconstructed from rates. Noise in two adjacent readings can dominate their difference, while a tiny systematic accounting error grows without bound when accumulated.

Sampling timestamps are event time, not arrival time. Integrating using when messages reached a process rather than when the sensor produced them is like ordering distributed events by log-ingestion time.

## Parcel / Go2 bridge

Parcel uses sampled camera, LiDAR, control, and simulator observations. State estimation converts those streams into pose and velocity beliefs. Motion completion should combine fused estimates with feedback freshness rather than integrating requested velocity. Latency metrics should distinguish sensor timestamp, receipt time, decision time, and actuator acknowledgement.

Companion reading: [Robotics Day 11 — Clocks, Sampling, Timescales, and Deadlines](../robotics-60-days/day-11-clocks-sampling-deadlines.md).

## Failure and safety note

Do not infer hardware travel solely by integrating commands, and do not derive acceleration from unfiltered low-resolution pose samples for a safety decision. Use appropriate state estimation and independent safety sensing. A beautiful graph with missing or reordered timestamps can still be physically false.

## Retrieval questions

1. What do slope and area mean on a velocity-versus-time graph?
2. Why does integration accumulate bias?
3. Why should sampled integration use sensor timestamps rather than arrival times?

## Optional 10-minute exercise

For velocities 0.0, 0.4, 0.4, and 0.0 m/s at times 0, 1, 2, and 3 s, estimate displacement with trapezoids. Sketch the graph and verify that the geometric area agrees.
