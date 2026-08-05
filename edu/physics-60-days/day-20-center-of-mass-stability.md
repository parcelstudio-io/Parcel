# Day 20: Center of Mass and Static Stability

## Mental model

The center of mass is the weighted average location of a system’s mass. Gravity acts as if the body’s total weight were concentrated there for many rigid-body calculations. A standing robot is statically stable when the vertical projection of its center of mass lies inside the support region formed by its active contacts.

Distance from that projection to the nearest support boundary is a rough stability margin. Near an edge, a small slope, push, acceleration, payload shift, or contact loss can create a tipping moment. During walking, the contact set changes and dynamic balance is richer than a static polygon, but the static picture remains a useful first model.

Center of mass is not necessarily the geometric center, and it moves when legs or payloads move.

## Quantities, units, and assumptions

For point masses m_i at positions r_i:

~~~text
total mass M = Σm_i
center of mass r_com = (Σm_i r_i)/M
~~~

Mass is in kg; positions and stability margins are in m. All positions must use the same frame and origin.

The static support-polygon rule assumes a rigid level surface, stationary body, compressive contacts, negligible dynamic momentum, and sufficient friction. A foot that is swinging or has lost contact is not a support vertex.

The center of pressure is where the resultant ground-reaction force acts on the support surface. It is related to, but not identical with, the center-of-mass projection.

## Core equations

For a body plus one payload along x:

~~~text
x_com = (m_body x_body + m_payload x_payload)
        / (m_body + m_payload)
~~~

Quasi-static condition:

~~~text
vertical projection of r_com lies inside support polygon
~~~

At an edge, gravity creates an approximate tipping moment:

~~~text
τ_tip = mg d
~~~

where d is horizontal perpendicular distance beyond the pivot edge. This is a teaching model, not a controller.

## ASCII diagram

~~~text
 top view

 front feet ●────────────●
            │     × CoM  │
            │            │  support polygon
 rear feet  ●────────────●

 × inside: static restoring margin
 × at edge: zero ideal margin
 × outside: gravity produces tipping tendency
~~~

## Worked Parcel / Go2 example

Assume an illustrative 15 kg body has x_body = 0 and a 1 kg audio payload is mounted at x_payload = 0.30 m:

~~~text
x_com = [(15 kg)(0 m) + (1 kg)(0.30 m)] / 16 kg
      = 0.01875 m
      ≈ 1.9 cm toward the payload
~~~

That shift may look small, yet it changes foot-load distribution and consumes stability margin. Raising the payload also increases how far its projection shifts on a slope and can increase rotational effects during turns.

These masses, locations, and any diagram proportions are illustrative. They are not Go2 payload limits or measured support geometry. A real review needs the complete assembly, leg pose, dynamic loads, vendor restrictions, and measured contact behavior.

## Software-engineering analogy

Center of mass is a weighted aggregate whose value changes when ownership moves. The support polygon is an admissible-state region. Operating near its boundary resembles running a service at saturation: tiny disturbances trigger a mode change.

Redundancy depends on active members. Four configured replicas do not help if only two are healthy; four feet do not define support while two are swinging.

## Parcel / Go2 bridge

Parcel should use Unitree Sport for balance and gait instead of recreating those fast loops. Application software still supervises tilt, measured motion, faults, and task context. Physical additions such as the microphone array, speaker enclosure, compute, brackets, and cables require a payload and center-of-mass review before hardware operation.

Companion reading: [Robotics Day 20 — Unitree Sport as a Nested Closed Loop](../robotics-60-days/day-20-synthesis-unitree-sport-nested-loop.md).

## Failure and safety note

Never test static stability by pushing, tipping, suspending, or loading a powered robot. Use vendor-approved payload limits, qualified mechanical review, rated supports, unpowered measurements, and controlled commissioning with an E-stop operator. Static stability does not certify dynamic walking.

## Retrieval questions

1. How is center of mass calculated for several component masses?
2. Which contacts belong in a static support polygon?
3. Why can a statically stable pose still fail during walking or turning?

## Optional 10-minute exercise

On paper, place a 10 kg body at x = 0 and payloads of 1 kg at x = 0.2 m and 0.5 kg at x = -0.3 m. Calculate x_com. Draw an illustrative support rectangle and discuss margin without claiming hardware safety.
