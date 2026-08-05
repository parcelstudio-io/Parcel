# Day 26: Force and Torque Through a Jacobian

## Mental model

The Jacobian maps joint velocity to foot velocity. Its transpose maps a task-space force to an equivalent generalized joint torque. The sign depends on which side of the contact the force names. This pairing is not a mnemonic accident; it follows from **virtual work**: for the same tiny compatible motion, mechanical power computed at the joints must equal power computed at the foot.

```text
joint side: tau dot q_dot
foot side:  F dot v
```

If `F_out` means the force the limb exerts on the environment and `v = J q_dot`, equality for every allowed `q_dot` gives `tau_actuator = J transpose F_out` in the idealized convention used here. The environment exerts the opposite contact force on the foot. Geometry therefore determines mechanical advantage. A configuration that makes a foot force easy in one direction may demand large torque in another.

## Quantities, units, and assumptions

- Foot output force `F_out`: newtons (`N`), expressed in a named foot/task frame; the environment-on-foot reaction has the opposite sign.
- Joint torque `tau`: newton metres (`N m`).
- Jacobian `J`: metres per radian (`m/rad`) for translational foot motion.
- Joint rate `q_dot`: radians per second (`rad/s`).
- Mechanical power: watts (`W`).

We assume quasi-static rigid links, ideal joints, a correctly oriented force vector, and no actuator friction or transmission loss. The equation describes a mapping, not a motor rating or a balance policy. If `F_ext` instead means force applied by the environment to the foot, `J^T F_ext` is the generalized external torque and an actuator statically opposing it contributes the negative, before gravity and other terms.

## Core equations

```text
v_foot = J(q) q_dot
tau_actuator = J(q)^T F_out

virtual-work / power identity:
tau_actuator dot q_dot = F_out dot v_foot
```

Near a singularity, the robot can have poor mechanical advantage in a task direction. Large force requests may require joint efforts beyond limits even if foot position is reachable.

## ASCII diagram

```text
 joint space                         task / foot space

 q_dot  ----------- J ----------->  v_foot
 tau    <-------- J transpose ----- F_out

       velocity flows right; force maps back left
```

## Worked Parcel / Go2 example

**The values are illustrative and are neither Go2 limits nor safe commanded forces.** Use the Day 25 teaching Jacobian:

```text
J = [0.341, 0.200] m/rad
    [0.141, 0.000] m/rad
```

Suppose the model asks the leg to exert `F_out = [20, 80] N` on the environment in the corresponding `(x, z)` directions. The environment-on-foot reaction is the negative of this vector. Then the idealized actuator-torque contribution is:

```text
tau = J^T F_out

tau_1 = 0.341(20) + 0.141(80) approximately 18.1 N m
tau_2 = 0.200(20) + 0.000(80) = 4.0 N m
```

The first joint carries more effort in this pose because both output-force components have lever effect through its Jacobian column. This calculation omits the other links, gravity, dynamics, gearing, motor current, and contact sharing. It is useful for intuition and simulation review, not actuator selection from one pose.

Check power using the Day 25 illustrative `q_dot = [0.5, -0.5] rad/s` and `v approximately [0.071, 0.071] m/s`:

```text
tau dot q_dot approximately 18.1(0.5) + 4.0(-0.5) = 7.05 W
F_out dot v approximately 20(0.071) + 80(0.071) = 7.10 W
```

The small mismatch is rounding.

## Software-engineering analogy

The Jacobian transpose resembles reverse-mode dependency propagation: a downstream load is pulled backward through the local dependency graph to determine upstream responsibility. Just as gradients depend on the current activation state, torque mapping depends on the current configuration.

## Parcel / Go2 bridge

On Go2 hardware, Sport closes the fast force, gait, and balance loops. Parcel should monitor bounded body motion and vendor-exposed state rather than compute foot-force-to-torque mappings in the voice planner. This lesson prepares a clean future controller interface: a replacement controller may own dynamics internally while preserving the same high-level command, feedback, watchdog, and safety contracts.

Companion reading: [Rigid-body dynamics, contact, and friction](../robotics-60-days/day-17-rigid-body-dynamics-contact.md) and [`docs/MOTION.md`](../../docs/MOTION.md).

## Failure and safety note

A developer uses a Jacobian from the wrong leg pose or frame. The computed torques are finite and plausible, but the real force direction differs, causing saturation or unloading a stance foot. Frame, joint ordering, configuration freshness, limits, and contact mode must all be validated. Never send this lesson’s calculated torques to hardware.

## Retrieval questions

1. Why does the transpose appear in the force mapping?
2. What equality connects joint power and foot power?
3. Why can a reachable foot position still demand infeasible torque?

## Optional 10-minute exercise

Choose `F_out = [0, 100] N` and calculate `J^T F_out` for the example matrix. Then change the second row of `J` to `[0.05, 0.04] m/rad` and repeat. Explain how configuration-dependent geometry changes joint loading without changing the chosen task-space output force.
