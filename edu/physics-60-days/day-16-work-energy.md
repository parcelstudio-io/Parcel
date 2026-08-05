# Day 16: Work and Mechanical Energy

## Mental model

Work is energy transferred when a force acts through a displacement. Mechanical energy is a useful accounting system: motion carries kinetic energy, height in gravity stores potential energy, and elastic deformation stores spring energy. Friction, damping, impacts, and motor losses transform organized mechanical energy into heat, sound, and deformation.

Energy accounting answers questions that position alone cannot. Lifting a payload, accelerating the body, and repeatedly braking all consume energy even when the dog eventually returns to its starting pose. A path planner that minimizes distance may not minimize energy if it chooses steep terrain or frequent stop-start motion.

Work can be positive, negative, or zero. A braking force does negative work on the moving body. A support force perpendicular to displacement can do zero work in an idealized model.

## Quantities, units, and assumptions

Work and energy are measured in joules:

~~~text
1 J = 1 N·m = 1 kg·m²/s²
~~~

Use:

- Force F in N.
- Displacement d in m.
- Mass m in kg.
- Speed v in m/s.
- Height h in m.

The system boundary matters. Mechanical energy lost by the body is not destroyed; it leaves the selected mechanical account as heat, sound, electrical regeneration, or deformation. Assume a constant gravitational field near Earth and choose a zero-height reference for potential energy.

## Core equations

For constant force:

~~~text
work W = F d cosφ
kinetic energy K = ½mv²
gravitational potential U_g = mgh
spring energy U_s = ½kx²
net work W_net = ΔK
~~~

With nonconservative losses:

~~~text
energy_initial + energy_input
= energy_final + energy_dissipated
~~~

Dimensional check:

~~~text
[kg][m/s²][m] = [kg·m²/s²] = [J]
~~~

## ASCII diagram

~~~text
 battery/electrical energy
          |
          v
 motor work → kinetic energy → climb potential energy
      |             |                  |
      +--------> heat/sound <----------+

 energy changes form; the accounting boundary decides the labels
~~~

## Worked Parcel / Go2 example

Assume an illustrative total mass of 16 kg climbs vertically by 0.20 m:

~~~text
ΔU_g = mgh
     = (16 kg)(9.81 m/s²)(0.20 m)
     ≈ 31.4 J
~~~

If it also reaches 0.60 m/s:

~~~text
K = ½(16 kg)(0.60 m/s)² = 2.88 J
~~~

At least 34.3 J has entered those two idealized mechanical stores. Actual battery energy drawn is larger because motors, electronics, contact, and computation are not perfectly efficient. Descending does not guarantee all potential energy returns to the battery; the controller may dissipate much of it.

These numbers are illustrative, not a Go2 payload, slope, energy, or speed specification.

## Software-engineering analogy

Energy is conserved accounting across services. Moving a cost out of one budget does not delete it; it appears in another account. A planner can reduce path length while increasing the thermal bill, just as a low-latency cache may increase memory cost.

Potential energy resembles deferred work. A robot at height has stored capacity for motion during a fall, even while its velocity is zero. Static state can therefore carry dynamic risk.

## Parcel / Go2 bridge

Parcel’s navigation costs can eventually include slope, stop-start frequency, battery state, and thermal state in addition to geometric distance. Unitree Sport handles locomotion mechanics, but behavior planning decides whether a nonessential gesture or detour is appropriate during a low-energy mission. Completion and energy accounting should use measured state, not only commanded trajectories.

Companion reading: [Robotics Day 05 — Electricity, Batteries, Power, and Heat](../robotics-60-days/day-05-electricity-batteries-power-heat.md).

## Failure and safety note

Do not infer remaining battery runtime or safe climbing ability from mechanical energy alone. Peak current, voltage sag, actuator thermal limits, surface contact, battery health, and vendor restrictions dominate real operation. Never perform climb or drop tests outside a controlled, approved facility.

## Retrieval questions

1. Under what geometric condition does a constant force do zero work?
2. Where can mechanical energy go when the robot brakes?
3. Why can returning to the start still consume substantial energy?

## Optional 10-minute exercise

Calculate the illustrative change in potential energy for 10 kg raised by 0.1, 0.5, and 1.0 m. Compare it with kinetic energy at 0.5 m/s. Use a calculator or simulator, not powered hardware.
