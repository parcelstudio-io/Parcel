# Day 25: Jacobians and Velocity Mapping

## Mental model

A **Jacobian** is a table of local sensitivities. Each entry says how much one task-space coordinate changes for a tiny change in one joint coordinate. It is the multivariable derivative of forward kinematics. Multiplying it by joint rates predicts the foot’s instantaneous velocity:

```text
foot velocity = Jacobian at the current pose * joint velocity
```

“At the current pose” is essential. The mapping changes as the leg bends. Near a **singularity**, independent joint motions stop producing independent foot directions. Then an ordinary-looking foot-velocity request can imply enormous or undefined joint rates.

## Quantities, units, and assumptions

- Joint vector `q`: radians (`rad`).
- Joint velocity `q_dot`: radians per second (`rad/s`).
- Foot position `p`: metres (`m`).
- Foot velocity `p_dot`: metres per second (`m/s`).
- Jacobian `J = partial p / partial q`: metres per radian (`m/rad`) for this position mapping.

We linearize a smooth, rigid, planar two-link model over a small motion. Large steps require recomputing `J`; finite joint limits, contact, backlash, and force limits remain outside this equation.

## Core equations

```text
p = f(q)
Delta p approximately J(q) Delta q
p_dot = J(q) q_dot

J_ij = partial p_i / partial q_j
```

For the Day 24 planar leg:

```text
J = [ -l1 sin(q1)-l2 sin(q1+q2),  -l2 sin(q1+q2) ]
    [  l1 cos(q1)+l2 cos(q1+q2),   l2 cos(q1+q2) ]
```

If `J` loses rank, some desired velocity directions cannot be generated locally.

## ASCII diagram

```text
 joint rates                         foot velocity
 [q1_dot]       J(q)                 [x_dot]
 [q2_dot]  ----------------------->  [z_dot]

 bent leg: two useful local directions
 straight leg: one direction collapses -> singularity
```

## Worked Parcel / Go2 example

**These are illustrative link lengths and rates, not Go2 commands or limits.** Reuse `l1 = l2 = 0.20 m`, `q1 = -45 degrees`, and `q2 = -45 degrees`. The approximate Jacobian is:

```text
J approximately [0.341, 0.200] m/rad
                [0.141, 0.000] m/rad
```

For illustrative rates `q_dot = [0.5, -0.5] rad/s`:

```text
x_dot = 0.341(0.5) + 0.200(-0.5) approximately 0.071 m/s
z_dot = 0.141(0.5) + 0.000(-0.5) approximately 0.071 m/s
```

This is an instantaneous prediction, not a trajectory. After the joints move, `J` changes. At a fully straight configuration, the two Jacobian columns align in a way that loses a local direction; an inverse based on ordinary division becomes ill-conditioned.

## Software-engineering analogy

A Jacobian resembles a local dependency matrix or the derivative used by an optimizer. It tells you which outputs are sensitive to which inputs around one deployment state. A singularity resembles a rank-deficient API: two controls have become redundant, so asking the inverse service for an arbitrary output produces huge coefficients and noise amplification.

## Parcel / Go2 bridge

Parcel’s current production direction does not invert leg Jacobians in the conversation or navigation layer. Sport owns the fast mapping from body requests to feet and joints. Jacobians become important when interpreting a future controller interface, checking simulated leg motion, or building a replaceable low-level controller behind the same authority boundary. Singularity margins and joint-rate limits belong in that controller, not in prompts.

Companion reading: [Jacobians and trajectory generation](../robotics-60-days/day-16-jacobians-trajectory-generation.md) and [Rigid-body dynamics and contact](../robotics-60-days/day-17-rigid-body-dynamics-contact.md).

## Failure and safety note

A numerical IK loop approaches a straight-leg singularity. Position error falls, but commanded joint rates grow until they saturate, producing tracking error and a sudden configuration change. Damped least squares and limit avoidance can improve numerics, but neither certifies hardware safety. Keep educational Jacobian inversions out of powered hardware and let the vendor controller retain balance authority.

## Retrieval questions

1. What does one entry `J_ij` mean physically?
2. Why must the Jacobian be recomputed as the leg changes configuration?
3. What happens to inverse velocity mapping near a singularity?

## Optional 10-minute exercise

Calculate the two-link Jacobian for `q1 = 0`, `q2 = 0`. Inspect its rows and explain which instantaneous foot direction is lost. Then perturb `q2` to `-5 degrees` and observe how the matrix changes. Use paper or a calculator only.
