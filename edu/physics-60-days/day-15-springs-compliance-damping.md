# Day 15: Springs, Compliance, and Damping

## Mental model

Real robot structures are not perfectly rigid. Feet, tires, mounts, links, cables, and housings deform under load. **Stiffness** relates force to displacement. **Compliance** is the inverse idea: how much displacement results from force. Elastic elements store energy and return it; dampers dissipate mechanical energy, usually as heat.

Compliance can absorb shocks and preserve contact, but too much causes poor positioning and oscillation. Damping reduces oscillation, but excessive damping can make response sluggish and transmit sustained loads differently. A microphone mount, leg, and body shell each need a suitable balance.

The familiar “spring plus damper” is a lumped model. It captures useful behavior without describing every atom or flex mode.

## Quantities, units, and assumptions

~~~text
displacement x       m
spring stiffness k   N/m
compliance 1/k       m/N
damping coefficient c   N·s/m
force F              N
~~~

Assume small deformation and approximately linear behavior for Hooke’s law. Real rubber, foam, joints, and structural parts can be nonlinear, temperature-dependent, hysteretic, or permanently deformed.

Specify whether x is compression or extension and choose a sign convention. The restoring force points opposite displacement from equilibrium.

## Core equations

~~~text
spring force F_s = -kx
damping force F_d = -c dx/dt
stored spring energy E_s = ½kx²
simple mass-spring-damper:
m d²x/dt² + c dx/dt + kx = external force
~~~

Dimensional check:

~~~text
[N/m][m] = [N]
[N·s/m][m/s] = [N]
~~~

Springs store recoverable energy; ideal viscous dampers dissipate energy. Friction can also damp motion but behaves differently.

Multiple elastic elements form a system: compliant parts in series usually make the assembly softer, while parallel load paths make it stiffer. Interfaces and fasteners can dominate even when the main bracket is rigid.

## ASCII diagram

~~~text
 vibrating body
    [ mass ]
      |   |
   /\/\/  [ damper ]
   spring     |
      |       |
  rigid base / robot chassis

 spring stores ↔ releases energy
 damper removes motion energy as heat
~~~

## Worked Parcel / Go2 example

Suppose an illustrative small elastomer mount is approximated by k = 2,000 N/m and compresses 2.0 mm:

~~~text
x = 0.0020 m
F = kx = (2,000 N/m)(0.0020 m) = 4.0 N
E_s = ½(2,000)(0.0020)² = 0.004 J
~~~

This model might help reason about a lightweight sensor or speaker mount, but it does not select a real component. Dynamic loading, bolt preload, geometry, fatigue, temperature, resonance, acoustic coupling, and cable strain matter. The values are illustrative, not approved Go2 payload or mount specifications.

For audio, isolation that reduces motor vibration may also let the microphone assembly wobble or alter the speaker enclosure. Mechanical and acoustic requirements must be evaluated together.

## Software-engineering analogy

A spring resembles a queue that temporarily stores work and returns it later; a damper resembles load shedding that converts organized work into heat. Too little damping yields retries and oscillation; too much produces slow response.

A lumped model is like a service mock: useful within declared behavior, misleading outside it. Nonlinear end stops are the physical equivalent of a sudden undocumented rate limit.

## Parcel / Go2 bridge

Unitree Sport already handles the compliant, contact-rich locomotion problem at high rate. Parcel engineers still make physical choices when attaching cameras, LiDAR, microphones, speakers, and compute. Mount flexibility can corrupt perception through vibration even when navigation code is correct.

Companion reading: [Robotics Day 37 — The Reality Gap](../robotics-60-days/day-37-reality-gap.md).

## Failure and safety note

Do not mount payloads based on a one-dimensional spring calculation. Use rated fasteners, mechanical review, retention, cable strain relief, and vibration/thermal testing. Never inspect or adjust a mount while the robot is powered or able to stand unexpectedly.

## Retrieval questions

1. What is the difference between stiffness, compliance, and damping?
2. Which element stores mechanical energy and which dissipates it?
3. Why can a mount that isolates vibration still harm sensing or audio?

## Optional 10-minute exercise

Calculate force and stored energy for an illustrative spring with k = 500 N/m at 1, 2, and 4 mm displacement. Confirm that force scales with x while energy scales with x². Use paper or a simulator only.
