# Day 27: Statics and Load Distribution

## Mental model

**Statics** studies systems with zero linear and angular acceleration. A standing quadruped must have ground forces that sum to its weight and moments that balance about every axis. Those equations constrain foot loads, but often do not uniquely determine all four forces. Compliance, posture, terrain height, and controller choices decide how the remaining load is shared.

Centering a payload can make equal-load intuition reasonable on level ground. Moving it forward shifts load to the front feet. During walking, acceleration and contact changes invalidate a purely static calculation; statics remains a baseline and a useful sanity check.

## Quantities, units, and assumptions

- Mass `m`: kilograms (`kg`).
- Weight `W = mg`: newtons (`N`).
- Foot normal force `F_z`: newtons (`N`).
- Fore-aft location `x`: metres (`m`) from a declared origin.
- Moment: newton metres (`N m`).

Assume level rigid ground, no acceleration, four point-like contacts, and left-right symmetry. Ignore leg mass distribution and horizontal forces. These assumptions are deliberately narrower than real Go2 stance physics.

## Core equations

```text
vertical force balance:       sum(F_z,i) = m g
pitch moment balance:         sum(x_i F_z,i) - x_CoM m g = 0
static equilibrium generally: sum(F) = 0 and sum(tau) = 0
```

Equal loading follows only from symmetric geometry and centered center of mass—not from “four feet” alone.

## ASCII diagram

```text
 side view, level ground

 rear pair             CoM             front pair
    ^ F_R               | mg down          ^ F_F
    |                    v                  |
----o--------------------*------------------o----
  x=-0.25 m           x=+0.10 m         x=+0.25 m

forward CoM shift -> larger front-pair reaction
```

## Worked Parcel / Go2 example

**All masses and dimensions are illustrative, not a measured Go2 load case.** Model an `18 kg` assembled dog with front and rear contact pairs at `x = +0.25 m` and `x = -0.25 m`. Let its center of mass be `0.10 m` forward of the middle.

```text
W = 18 kg * 9.81 m/s² = 176.6 N
wheelbase-like separation L = 0.50 m

front-pair load = W * (0.10 - (-0.25)) / 0.50
                = 0.70 W approximately 123.6 N

rear-pair load  = W - front load approximately 53.0 N
```

With left-right symmetry, that is about `61.8 N` per front foot and `26.5 N` per rear foot. The result shows why adding an audio/compute payload forward changes leg loading. It does not predict loads during trot, slope, yaw, foot compliance, or controller redistribution.

## Software-engineering analogy

Global invariants constrain totals without uniquely assigning ownership. “All shard loads sum to traffic” does not say which replica receives which requests. Static force and moment equations are conservation invariants; contact compliance and the controller are the scheduler.

## Parcel / Go2 bridge

Payload layout should be represented in mechanical documentation and the simulator’s inertial model. Sport commands gait and contact behavior, while the controller, body, ground, and disturbances together determine the resulting stance forces; Parcel observes coarse body state and faults. Application behaviors should queue bow/sit gestures behind a confirmed stop because a changing contact pattern and moving CoM invalidate the stationary load model.

Companion reading: [Rotational mechanics and balance](../robotics-60-days/day-04-rotational-mechanics-balance.md) and [Rigid-body dynamics and contact](../robotics-60-days/day-17-rigid-body-dynamics-contact.md).

## Failure and safety note

A new front enclosure passes a total-payload check, but no one recalculates load distribution. Front actuators run hotter and front feet approach surface-pressure or traction limits sooner. A static estimate would have exposed the direction of change, though only instrumented tests can quantify it. Do not place weights on a powered robot for this exercise.

## Retrieval questions

1. Which two equilibrium conditions constrain a standing robot?
2. Why do four vertical foot forces usually need more information than force and pitch-moment balance alone?
3. What happens to front-foot load when the center of mass moves forward?

## Optional 10-minute exercise

Draw the example and repeat it for `x_CoM = 0` and `x_CoM = -0.05 m`. Confirm that front plus rear load always equals weight. Optionally balance a ruler on two supports with a coin payload; do not use the robot.
