# Day 34: Electric Motors

## Mental model

An electric motor converts electrical power into torque and angular motion. In a simplified motor model, current produces torque and rotation produces a counter-voltage called **back EMF**. At low speed, back EMF is small, so current can become large. At higher speed, back EMF consumes more of the supply-voltage budget, leaving less voltage to drive current and torque.

This produces the familiar torque-speed tradeoff. “Peak torque” is a short-duration operating point constrained by current, voltage, controller limits, winding temperature, magnets, gearing, and structure—not a continuously available constant.

## Quantities, units, and assumptions

- Motor current `I`: amperes (`A`).
- Winding resistance `R`: ohms (`ohm`).
- Angular speed `omega`: radians per second (`rad/s`).
- Torque constant `k_t`: newton metres per ampere (`N m/A`).
- Back-EMF constant `k_e`: volt seconds per radian (`V s/rad`).
- Torque `tau`: newton metres (`N m`).

We use a steady idealized DC-equivalent model. Go2-class actuators use electronically commutated motors and sophisticated drives; inductance, phase currents, saturation, field-oriented control, friction, and thermal limits are omitted.

## Core equations

```text
motor torque:             tau approximately k_t I
back EMF:                 V_emf approximately k_e omega
terminal-voltage sketch:  V approximately I R + k_e omega
input power:              P_elec = V I
mechanical power:         P_mech = tau omega
copper heating:           P_copper = I² R
```

In consistent SI conventions, `k_t` and `k_e` have related numerical values, but always use the vendor definitions.

## ASCII diagram

```text
torque
  ^  * stall: high current, zero speed, zero mechanical output
  |   \
  |    \
  |     \
  |      * ------------------------------> speed
  +--------------------------------------->

back EMF rises with speed; available current/torque falls
thermal envelope may lie well below the ideal line
```

## Worked Parcel / Go2 example

**This illustrative imaginary motor is not a Go2 actuator and the numbers are not safe limits.** Let `V = 24 V`, `R = 0.40 ohm`, `k_e = 0.08 V s/rad`, and `k_t = 0.08 N m/A`. At `omega = 200 rad/s`:

```text
V_emf = 0.08 * 200 = 16 V
I = (24 - 16)/0.40 = 20 A
tau = 0.08 * 20 = 1.6 N m
P_mech = 1.6 * 200 = 320 W
P_copper = 20² * 0.40 = 160 W
```

At idealized stall, `omega = 0`, giving `I = 60 A` and `I²R = 1440 W` unless a controller limits current. Mechanical output power at stall is still zero because speed is zero. This is why holding or blocked-joint conditions can heat a motor rapidly.

## Software-engineering analogy

The motor operating envelope resembles a service constrained by CPU, memory, and thermal quotas simultaneously. Peak benchmark throughput is not sustainable throughput. Back EMF is a state-dependent budget subtraction: as speed rises, less voltage headroom remains for torque-producing current.

## Parcel / Go2 bridge

Sport and Unitree’s actuator stack own motor current, torque, commutation, gait, and balance. Parcel should request bounded body motion and observe normalized faults rather than derive motor current from conversational intent. Future custom controllers still need vendor limits, temperature feedback, current limiting, and a formally exclusive authority path.

Companion reading: [Motors, gearing, and actuator modes](../robotics-60-days/day-07-motors-gearing-actuator-modes.md), [Rigid-body dynamics and contact](../robotics-60-days/day-17-rigid-body-dynamics-contact.md), and [`docs/MOTION.md`](../../docs/MOTION.md).

## Failure and safety note

A scripted pose holds a joint against an obstruction. Position error remains nonzero, so the controller continues demanding current while speed is nearly zero. Mechanical output is small but copper heating is large. Never treat “not moving” as “not consuming power.” Respect vendor modes and fault handling; do not intentionally stall a powered actuator.

## Retrieval questions

1. Why does available torque generally fall as motor speed rises in the simple model?
2. Why can a stalled motor heat rapidly while producing zero mechanical power?
3. Which layer owns current and torque control in Parcel’s current Go2 direction?

## Optional 10-minute exercise

Using the imaginary parameters above, compute current, torque, mechanical power, and copper heat at `omega = 0`, `100`, `200`, and `280 rad/s`. Plot torque versus speed. Keep this entirely on paper or in software.
