# Day 55: First- and Second-Order Dynamics

## Mental model

A dynamic system has memory: its output depends on previous state, not only the current input. First-order models describe one dominant energy-storage or lag process. Second-order models describe two coupled state variables and can overshoot or oscillate. These simple models rarely capture an entire quadruped, but they are excellent for latency budgets, controller intuition, and detecting when a simulator responds unlike hardware.

Parcel can identify a safe, low-bandwidth command-to-body response around Unitree Sport without modeling every joint. Sport still owns fast balance and gait. The outer stack sees a controlled plant: request a body twist, observe delayed and smoothed measured motion, and plan within that response envelope.

## Quantities, units, and assumptions

- steady-state gain `K`: output/input unit ratio
- time constant `tau`: second (`s`)
- natural angular frequency `omega_n`: radian per second (`rad/s`)
- damping ratio `zeta`: dimensionless
- rise time, settling time, and delay: second (`s`)
- bandwidth: hertz (`Hz`)
- input `u`, output `y`: quantities with declared units

The models assume approximately linear, time-invariant behavior near one operating point. Gait transitions, saturation, contact changes, payload, battery state, and vendor mode logic break that assumption.

## Core equations

First-order system and unit-step response:

~~~text
tau y_dot + y = K u
y(t) = K u_0 (1 - exp(-t/tau))
y(tau) = 0.632 K u_0
~~~

Standard second-order form:

~~~text
y_ddot + 2 zeta omega_n y_dot + omega_n^2 y = omega_n^2 K u
omega_d = omega_n sqrt(1-zeta^2)   for zeta < 1
rough first-order settling scale approximately 4 tau
~~~

Underdamped response (`zeta < 1`) can overshoot. Critical damping is `zeta = 1`; overdamping is slower without oscillatory overshoot.

## ASCII diagram

~~~text
 command step:  ____|---------------- target

 first order:   ____/'''''''''''''''' approaches target
 second order:  ____/\__/‾‾‾‾‾‾‾ may overshoot/ring
                      ^ damping controls decay

 Parcel command -> [Sport + body + ground] -> measured body velocity
~~~

## Worked Parcel / Go2 example

Suppose an illustrative simulator log, after removing a separately estimated pure delay, shows measured forward speed reaches 63% of its final value 0.18 s into the response to a small admitted command step. A first-order estimate is `tau = 0.18 s`, giving a rough settling scale:

~~~text
t_settle approximately 4 tau = 0.72 s
~~~

A navigation behavior that assumes instantaneous speed may overshoot a lamppost stand-off or reverse too late. It can instead shape the reference, predict stopping with observed response delay, and verify settled measured motion. If pure delay is not separated, the command-to-63% time overestimates the plant time constant. This model says nothing about foot stability; it is only an outer command-response approximation. The step size, time constant, and settling rule are illustrative, not Unitree specifications.

If the response rings, a second-order model may fit better—or the ringing may be a mode switch, estimator artifact, or contact change. Residuals should decide rather than forcing every trace into one equation.

## Software-engineering analogy

A first-order plant resembles a service autoscaler with one dominant lag. A second-order plant resembles a feedback-driven queue that can overprovision, correct, and oscillate. Steady-state throughput alone hides transient behavior; p99 settling after a workload step is often the real product constraint.

## Parcel / Go2 bridge

Use low-energy identified response models to tune simulation, smoother limits, prediction horizon, and task timeout—not to bypass Sport. A future custom controller must sit behind the same exclusive `LocomotionController` boundary and prove its own fast stability. Read [Day 19: State Space and Constrained Control](../robotics-60-days/day-19-state-space-constrained-control.md) and [`docs/MOTION.md`](../../docs/MOTION.md).

## Failure and safety note

A step test is an energy injection. Do not perform it on hardware without vendor limits, open clearance, restraint/spotting, an E-stop operator, and a commissioned protocol. Models identified on one surface or gait should not be reused blindly. Never infer balance stability from a fitted body-velocity time constant.

## Retrieval questions

1. What physical meaning does the first-order time constant have after a step?
2. What does damping ratio change in an ideal second-order response?
3. Why may Parcel model command-to-body response without taking over Sport's balance loop?

## Optional 10-minute exercise

Plot `1 - exp(-t/tau)` for `tau = 0.1, 0.2, 0.5 s`, marking 63% and `4 tau`. If an existing simulator log is available, estimate `tau` from it and clearly label the operating point; do not collect a hardware step response.
