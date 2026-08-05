# Day 07: Constant-Acceleration Motion and Braking

## Mental model

Constant-acceleration equations are small predictive tools, not promises about a robot. They are useful for estimating ramps, reaction distance, and ideal braking distance. Real quadrupeds do not brake with perfectly constant acceleration: contact changes by gait phase, friction varies, controllers saturate, and state estimates arrive late.

The key safety insight is that stopping begins after perception, computation, communication, and actuator response. The dog travels during that latency. Then it needs physical distance to shed momentum. A collision gate that triggers at the ideal braking distance alone is already late.

Slope changes the estimate: gravity assists downhill motion and opposes uphill motion. A braking model measured on level indoor flooring therefore cannot be transferred unchanged to a ramp or city curb.

## Quantities, units, and assumptions

Use one axis and choose its positive direction. Let:

- x be position in m.
- v be velocity in m/s.
- a be constant acceleration in m/s².
- t be elapsed time in s.

Assume acceleration is constant, the surface can supply it, the body remains stable, and the controller responds as modeled. These assumptions make the equations tractable; field measurements determine whether they are conservative enough.

## Core equations

For constant acceleration:

~~~text
v = v₀ + at
x = x₀ + v₀t + ½at²
v² = v₀² + 2a(x - x₀)
~~~

For braking with positive deceleration magnitude a_b:

~~~text
t_brake = v/a_b
d_brake = v²/(2a_b)
d_reaction = v t_latency
d_stop ≈ d_reaction + d_brake + margin
~~~

Dimensional check:

~~~text
[m²/s²] / [m/s²] = [m]
~~~

Doubling speed makes the ideal braking term four times larger when a_b is unchanged.

## ASCII diagram

~~~text
 dog ●  velocity → | latency travel | physical braking | margin | █ obstacle

 detect → compute → transmit → controller reacts → decelerate → settle
~~~

## Worked Parcel / Go2 example

Assume illustrative values:

~~~text
speed v = 0.80 m/s
end-to-response latency = 0.15 s
available deceleration a_b = 1.60 m/s²
~~~

Then:

~~~text
d_reaction = (0.80)(0.15) = 0.12 m
d_brake = 0.80²/(2 × 1.60) = 0.20 m
ideal subtotal = 0.32 m
~~~

This subtotal excludes perception uncertainty, obstacle motion, robot footprint, controller variation, surface changes, and a settled-speed tolerance. It is therefore not a safe clearance value. The figures are illustrative, not commissioned Go2 limits.

If speed doubles to 1.60 m/s with the same latency and deceleration, reaction distance doubles to 0.24 m while braking distance becomes 0.80 m. The total grows nonlinearly.

## Software-engineering analogy

Stopping resembles cancellation in a distributed system. A client sends cancel, but work continues during propagation and teardown. A zero command is the cancellation request; measured settled velocity is the completed cancellation.

Tail latency matters more than average latency. A stopping margin built from mean perception and network time fails on p99 delays. Freshness budgets and watchdogs are physical SLOs.

## Parcel / Go2 bridge

Parcel should combine speed-dependent obstacle margins, time-to-collision reasoning, fresh sensor data, a final collision monitor, and measured stop confirmation. Unitree Sport performs locomotion braking, while Parcel determines when environmental risk requires a stop. Neither layer should assume the other eliminates latency.

Companion reading: [Robotics Day 35 — Safety Engineering](../robotics-60-days/day-35-safety-engineering.md).

## Failure and safety note

Never commission braking distance by walking the robot toward a person, animal, wall, or valuable object. Use a controlled test area, low initial energy, soft sacrificial targets if approved, vendor procedures, external measurement, and an independent E-stop operator. Repeat across relevant surfaces, payloads, battery states, and delay conditions.

## Retrieval questions

1. What two distances exist before adding uncertainty and footprint margins?
2. Why does ideal braking distance grow with the square of speed?
3. Why is commanded zero not proof that stopping is complete?

## Optional 10-minute exercise

Using only a calculator, compare reaction plus ideal braking distance at 0.4 and 0.8 m/s for 0.20 s latency and 1.0 m/s² illustrative deceleration. Do not turn the result into a hardware limit.
