# Day 35: Gears and Transmissions

## Mental model

A transmission trades speed for torque while approximately conserving power. A reduction gear lets a fast, lower-torque motor produce slower, higher-torque joint motion. It does not create energy. Efficiency loss becomes heat, while backlash, compliance, friction, and reflected inertia change control behavior.

Gear ratio is a convention that must be stated. Here `G = motor speed / joint speed`, so `G > 1` is reduction. Larger reduction multiplies output torque but lowers output speed and can make the joint harder to backdrive. It also magnifies the motor rotor’s apparent inertia when viewed from the joint.

## Quantities, units, and assumptions

- Gear ratio `G`: dimensionless.
- Angular speed `omega`: radians per second (`rad/s`).
- Torque `tau`: newton metres (`N m`).
- Efficiency `eta`: dimensionless, between zero and one.
- Rotational inertia `J`: kilograms metres squared (`kg m²`).

Assume an ideal fixed-ratio transmission plus one efficiency factor. Real reducers have direction-dependent friction, tooth compliance, backlash, wear, load limits, and speed-dependent efficiency.

Backlash creates a small motion interval before opposite tooth faces engage; compliance stores and releases energy. Both can turn smooth motor motion into joint-position error or impact when load direction reverses.

## Core equations

Using this lesson’s ratio convention:

```text
G = omega_motor / omega_joint
omega_joint = omega_motor / G
tau_joint approximately eta G tau_motor

power check:
tau_joint omega_joint approximately eta tau_motor omega_motor

motor inertia seen at joint: J_motor_at_joint approximately G² J_motor
load inertia seen at motor:  J_load_at_motor approximately J_load/G²
```

Always verify which side and convention a datasheet uses.

## ASCII diagram

```text
fast motor             reduction G             slower joint
omega_m, tau_m  --->  [ small : large ]  --->  omega_j, tau_j

speed divided by G
torque multiplied by about eta*G
motor inertia reflected to joint by G²
```

## Worked Parcel / Go2 example

**This is an imaginary transmission, not a Go2 ratio or actuator rating.** Let `G = 9`, efficiency `eta = 0.85`, motor torque `0.40 N m`, and motor speed `270 rad/s`:

```text
omega_joint = 270/9 = 30 rad/s
tau_joint approximately 0.85 * 9 * 0.40 = 3.06 N m

input mechanical power = 0.40 * 270 = 108 W
output mechanical power approximately 3.06 * 30 = 91.8 W
```

The difference, about `16.2 W` in this simple operating point, becomes loss—mostly heat. If motor inertia is an illustrative `0.00020 kg m²`, its ideal reflected contribution at the joint is:

```text
J_reflected = 9² * 0.00020 = 0.0162 kg m²
```

Increasing ratio can help static torque while making rapid joint acceleration, contact transparency, and backdrivability harder.

## Software-engineering analogy

A gearbox resembles a batching layer: it exchanges rate for per-operation leverage while adding latency, overhead, and buffering effects. A ratio is not free capacity. Reflected inertia is like hidden queue state becoming visible across an abstraction boundary.

## Parcel / Go2 bridge

The robot profile and vendor actuator model should own transmission parameters. Navigation should never compensate for gearing by bypassing body-motion limits. Sport already accounts for its physical drivetrain when producing gait. A future custom controller must model ratio conventions, joint-side limits, friction, backlash, efficiency, and temperature explicitly.

Companion reading: [Motors, gearing, and actuator modes](../robotics-60-days/day-07-motors-gearing-actuator-modes.md), [Forward and inverse kinematics](../robotics-60-days/day-15-forward-inverse-kinematics.md), and [Learned quadruped locomotion](../robotics-60-days/day-57-learned-quadruped-locomotion.md).

## Failure and safety note

A team converts a motor-side peak torque into a joint-side continuous rating by multiplying only by gear ratio. It ignores efficiency, thermal duration, gearbox load rating, and vendor current limits. The result looks numerically strong but is unsafe. Use official joint-side operating envelopes and thermal tests; do not derive Go2 limits from these examples.

## Retrieval questions

1. Under this lesson’s convention, how do joint speed and torque change as `G` increases?
2. Why does a gearbox not create power?
3. What does reflected motor inertia do to the feel/control of a high-reduction joint?

## Optional 10-minute exercise

Repeat the illustrative calculation for `G = 5`, `10`, and `15` at the same motor point and `eta = 0.85`. Tabulate joint speed, torque, output power, and reflected motor inertia. Identify the tradeoff; do not command hardware.
