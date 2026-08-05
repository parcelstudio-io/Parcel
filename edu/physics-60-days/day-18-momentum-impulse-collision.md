# Day 18: Momentum, Impulse, and Collision

## Mental model

Momentum combines mass and velocity. Impulse is force applied over time and equals a change in momentum. These ideas explain why stopping takes time and why a softer, longer collision generally has lower average force than an abrupt one for the same momentum change.

Impact risk cannot be described by speed alone. Mass, approach direction, contact geometry, compliance, stopping time, and the human or object struck all matter. Kinetic energy describes how much energy must be transformed; momentum and impulse describe the force-time exchange.

A collision monitor should prevent contact rather than rely on padding. Compliance is a last mitigation, not permission to drive closer.

## Quantities, units, and assumptions

~~~text
momentum p       kg·m/s
impulse J        N·s = kg·m/s
force F          N
collision time Δt   s
~~~

Momentum is a vector. A turn changes momentum even if speed remains constant. For a short impact, external impulse may dominate other forces, but gravity and multi-contact dynamics can matter.

Average-force estimates hide peak force and contact shape. Human injury cannot be inferred from one scalar average. Treat the body as a point mass only for first-order comparison.

## Core equations

~~~text
p = mv
J = integral of F dt = Δp
F_average ≈ Δp/Δt
kinetic energy K = ½mv²
~~~

For a stop from speed v in one dimension:

~~~text
|Δp| = mv
~~~

Dimensional check:

~~~text
[N][s] = [kg·m/s²][s] = [kg·m/s]
~~~

Momentum is conserved only for a suitably isolated system. During a robot-floor collision, the Earth is part of the larger momentum account.

A rebound reverses part of the velocity, so its momentum change can be larger than merely stopping. Contact materials and geometry influence that rebound, but a simple “bounciness” value still cannot predict peak force or human injury.

## ASCII diagram

~~~text
before: dog ●────► p

short stop:   █  large force over short time
soft stop:  ~~~~ smaller average force over longer time

area under force-time curve = impulse = change in momentum
~~~

## Worked Parcel / Go2 example

Assume an illustrative 16 kg system moving at 0.60 m/s:

~~~text
p = (16 kg)(0.60 m/s) = 9.6 kg·m/s
~~~

If it is brought to rest in 0.10 s, a crude average net force magnitude is:

~~~text
F_avg ≈ 9.6/0.10 = 96 N
~~~

If the same momentum change occurs over 0.50 s:

~~~text
F_avg ≈ 9.6/0.50 = 19.2 N
~~~

The longer stop needs more time and usually more distance. Neither number predicts peak contact force, injury, or safe operation. They are illustrative, not commissioned Go2 collision or braking limits.

## Software-engineering analogy

Momentum resembles queued state that cannot disappear instantly. Impulse is the accumulated cancellation work needed to drain it. A graceful shutdown spreads work over time; a hard termination can concentrate load elsewhere.

Average force resembles average latency: useful for accounting but capable of hiding a damaging peak. Safety reviews need worst-case timing and uncertainty, not only means.

## Parcel / Go2 bridge

Parcel should keep people outside the predicted stopping envelope, monitor time to collision, and trigger independent braking or stop gates. Unitree Sport executes the physical response, while measured velocity confirms settling. Behavior gestures near a user require lower energy and explicit spatial preconditions.

Companion reading: [Robotics Day 35 — Safety Engineering](../robotics-60-days/day-35-safety-engineering.md).

## Failure and safety note

Never perform collision experiments with people or animals, and never use lesson calculations to certify padding. Human-contact testing and safety certification require specialists, approved fixtures, instrumentation, and applicable standards. Simulation cannot validate injury risk by itself.

## Retrieval questions

1. What physical quantity equals the area under a force-versus-time curve?
2. Why can increasing stopping time reduce average force?
3. Why do momentum and kinetic energy provide different information?

## Optional 10-minute exercise

For an illustrative 10 kg body at 0.3 and 0.6 m/s, compute momentum, kinetic energy, and average stopping force over 0.2 s. Note which quantities double and which quadruple.
