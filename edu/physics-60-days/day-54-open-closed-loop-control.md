# Day 54: Open-Loop and Closed-Loop Control

## Mental model

Open-loop control chooses an input without measuring whether the desired physical result occurred. Closed-loop control measures an output, compares it with a target, and corrects future input. Open loop can be adequate when disturbances are small and the plant is predictable. A companion robot on changing floors near people needs feedback.

Closed loop is not one giant controller. Parcel uses nested loops at different timescales. A behavior loop checks task predicates and owner-relative state. Navigation turns spatial error into bounded body motion. `ControlManager` leases and monitors commands. Unitree Sport remains the fast closed-loop balance and gait controller using onboard proprioception. Parcel does not replace that balance loop with Python, an LLM, or a navigation model.

## Quantities, units, and assumptions

- reference `r(t)`: desired physical quantity
- measured output `y_m(t)`: same unit as reference
- error `e(t) = r(t) - y_m(t)`
- control input `u(t)`: plant input, here often body velocity setpoint
- disturbance `d(t)`: push, slip, grade, payload change
- loop period and delay: second (`s`)
- gain `K`: output units chosen so dimensions match

Feedback assumes the measurement is fresh enough, the sign and frame are correct, and the controller can affect the output. Saturation and hidden inner loops change the response.

## Core equations

~~~text
error: e(t) = r(t) - y_m(t)
proportional example: u(t) = K_p e(t)
plant: x_dot = f(x, u, d)
closed-loop update: measure -> compare -> command -> physical response -> measure
~~~

For owner following, an illustrative distance controller might use forward speed proportional to `distance - desired_distance`, then clamp it to an admitted envelope. Collision vetoes can always replace that speed with stop.

## ASCII diagram

~~~text
 task target -> behavior/nav -> body setpoint -> ControlManager -> Unitree Sport
      ^                                                       | fast balance
      |                                                       v
      +---- camera/LiDAR + estimated body motion <------- physical Go2

 outer loops: semantic/task/navigation        inner loop: gait/balance
 no layer bypasses safety or becomes a second motor writer
~~~

## Worked Parcel / Go2 example

“Walk away from the owner five steps” is unsafe as five timed reverse pulses: stride length varies with speed, gait, surface, and controller response. A closed-loop implementation interprets the phrase into a bounded metric displacement or asks clarification, records an owner-relative start state, commands a preferred safe trajectory, and stops when measured displacement reaches a tolerance while clearance remains valid.

Illustratively, if the compiled target is 1.5 m and current measured progress is 1.1 m:

~~~text
e = 1.5 m - 1.1 m = 0.4 m
u = (0.8 1/s)(0.4 m) = 0.32 m/s
~~~

The output is then shaped, clamped, leased, and possibly vetoed. The numeric target and gain are teaching values, not Go2 settings. Sport takes the admitted body setpoint and closes its own faster feedback around posture and feet.

## Software-engineering analogy

Open loop is fire-and-forget RPC plus a timer. Closed loop is a reconciler: compare desired and observed state, issue an idempotent bounded action, and repeat. Sport is a lower-level reconciler with a much tighter deadline. Running two writers against the same actuator resembles competing database leaders.

## Parcel / Go2 bridge

The swappable `LocomotionController` boundary preserves one body-command contract while Sport owns today's balance implementation and a future commissioned controller could replace it. Task success must use observations, not Sport RPC acknowledgement. Read [Day 20: Unitree Sport as a Nested Closed Loop](../robotics-60-days/day-20-synthesis-unitree-sport-nested-loop.md) and [`docs/MOTION.md`](../../docs/MOTION.md).

## Failure and safety note

Wrong feedback sign creates positive feedback; stale feedback makes corrections late; integral state can continue pushing after saturation. A closed loop is not safe merely because it is closed. Keep leases, limits, E-stop authority, freshness checks, measured stop confirmation, and independent collision vetoes. Hardware gain tuning requires a commissioned low-energy procedure.

## Retrieval questions

1. What distinguishes open-loop execution from closed-loop task completion?
2. Which layer owns fast Go2 balance today, and what does Parcel command instead?
3. Why are “five timed reverse pulses” not a robust implementation of “walk away five steps”?

## Optional 10-minute exercise

In the headless simulator or on paper, compare a timed 1.5 m prediction with completion based on measured displacement under two speed-response delays. List every feedback signal and veto required. Do not run this exercise on hardware.
