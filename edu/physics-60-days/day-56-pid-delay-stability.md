# Day 56: PID, Delay, and Stability

## Mental model

Feedback corrects error only after the physical system responds and a measurement returns. Proportional-integral-derivative control is a compact way to use present, accumulated, and changing error. More gain can reject disturbances faster, but delay rotates correction out of phase. A command intended to oppose an old error can reinforce the system's current motion and create oscillation or instability.

PID is not one magic controller for the whole dog. Unitree Sport keeps ownership of the fast closed-loop balance and gait controller. Parcel may use slower bounded controllers for owner distance, heading, waypoint tracking, and command shaping. Those outer loops operate through Sport's body-velocity interface and retain collision vetoes, leases, and measured completion.

## Quantities, units, and assumptions

- error `e`: target units, such as metre or radian
- control output `u`: commanded units, such as `m/s` or `rad/s`
- proportional gain `K_p`: `u/e`
- integral gain `K_i`: `u/(e s)`
- derivative gain `K_d`: `u s/e`
- feedback delay `T_d`: second (`s`)
- angular frequency `omega`: radian per second (`rad/s`)
- phase: radian or degree

Classical PID reasoning assumes a stable operating mode with useful measurements. Saturation, mode switches, nonlinear friction, stale tracks, and the hidden dynamics of an inner vendor loop require limits and experiments.

## Core equations

~~~text
u(t) = K_p e(t) + K_i integral(e dt) + K_d de/dt
integrator state: I_dot = e
pure-delay phase lag: phi = -omega T_d radians
omega = 2 pi f
~~~

Proportional action responds now but may leave steady error. Integral removes persistent error but can wind up against a saturated actuator. Derivative anticipates trend but amplifies high-frequency measurement noise. Practical implementations filter derivative, bound or back-calculate integral, and clamp the final output.

## ASCII diagram

~~~text
 target -> error -> [ P + I + D ] -> bounded body setpoint -> Sport -> body
    ^                                                       |
    +----- delayed camera/LiDAR/body-state measurement <----+

 too much gain + delay: correct yesterday's error in today's wrong direction
~~~

## Worked Parcel / Go2 example

Suppose an illustrative owner-heading outer loop has meaningful motion near 2 Hz while sensing, scheduling, and filtering add 100 ms of delay. Delay alone contributes:

~~~text
phi = -(2 pi)(2 Hz)(0.100 s) = -1.257 rad = -72 degrees
~~~

That is a large loss of phase margin before accounting for Sport/body response. Raising heading gain to make a static simulator “snappy” can cause real oscillation around the owner. A safer design identifies the outer response, reduces latency, limits bandwidth, filters derivative carefully, uses hysteresis near alignment, and verifies with perturbed simulation.

The frequency and delay are illustrative. They are not Go2 controller bandwidth or measured Parcel p99 latency. Sport's own vendor-tuned fast loop is not replaced or retuned by this outer calculation.

## Software-engineering analogy

Integral action resembles a retry backlog: it remembers unmet demand. Saturation without anti-windup is a queue that grows while the dependency is rate-limited, then floods it after recovery. Delay-induced instability resembles an autoscaler reacting to old load and repeatedly overshooting capacity.

## Parcel / Go2 bridge

Use proportional or PID-like logic only behind typed behavior/navigation interfaces, with explicit source timestamps and output limits. Track `UserQueryEndToFirstReasoningResponse`, first spoken response, perception age, planning, arbitration, command delivery, and measured response separately because their tails constrain safe loop bandwidth. Read [Day 18: Feedback Control and PID](../robotics-60-days/day-18-feedback-control-pid.md), [Day 20: Unitree Sport Nested Loop](../robotics-60-days/day-20-synthesis-unitree-sport-nested-loop.md), and [`docs/MOTION.md`](../../docs/MOTION.md).

## Failure and safety note

Do not tune gains first on free-standing hardware. Wrong sign, units, frame, timestamp, or output authority can destabilize immediately. Begin with offline logs and headless simulation, inject delay and drops, cap energy, and use a commissioned low-speed procedure with an E-stop operator. Integral state must reset or transfer safely across stop, mode, and target changes.

## Retrieval questions

1. What physical information do the P, I, and D terms use?
2. Why does pure delay reduce stability margin as loop frequency rises?
3. Which controller retains fast Go2 balance authority, even if Parcel uses an outer PID-like follower?

## Optional 10-minute exercise

Calculate delay phase at 0.5, 1, 2, and 5 Hz for delays of 20 and 100 ms. Mark combinations exceeding 45 degrees of lag. Then identify which latency metric would test each assumed delay; do not tune hardware.
