# Day 00: Physics Is the Contract

## Mental model

Robot software can request motion, but physics decides what happens. A command such as “move forward at 0.5 m/s” is not a fact about the body. It is an input to motors, gears, feet, a floor, and a controller. The useful contract is therefore:

~~~text
predict from a model → act at bounded energy → measure → compare → revise
~~~

A physical model is a deliberately incomplete description of reality. A point-mass model may be enough to estimate stopping distance, but it cannot predict whether one foot slips. A rigid-body model can describe tipping, but not a loose cable. Good engineering uses the simplest model that answers the current question, states its assumptions, and names a measurement that could prove it wrong.

This differs from treating a simulator or a successful API call as truth. Simulation is an executable model. Telemetry is evidence with noise and delay. Neither is the physical world itself.

## Quantities, units, and assumptions

Start every problem by naming:

- **System boundary:** the dog, one leg, a battery, or dog plus payload.
- **State:** quantities needed to describe it now, such as position in metres and velocity in metres per second.
- **Inputs:** commanded velocity, motor current, or an external push.
- **Parameters:** mass, friction coefficient, link length, or battery resistance.
- **Disturbances:** a moving person, floor slope, wind, or packet delay.
- **Observations:** encoder, IMU, camera, LiDAR, voltage, or temperature data.

Write units beside every value. Also record the coordinate frame and timestamp for spatial data. “0.5” is unusable; “0.5 m/s forward in base_link, sampled 40 ms ago” is a physical statement.

Assumptions should be visible: level floor, constant acceleration, fresh localization, no wheel-like lateral glide, or owner velocity approximately constant. An assumption is not embarrassing. A hidden assumption is.

## Core equations

A general model can be written as:

~~~text
state_next = f(state_now, input, disturbance; parameters)
measurement = h(state) + error
residual = measured - predicted
~~~

For a first motion estimate:

~~~text
distance = speed × time
[m]      = [m/s] × [s]
~~~

The dimensional equality is a cheap correctness test. It does not prove the model is suitable, but a dimensional mismatch proves it is wrong.

## ASCII diagram

~~~text
 intent       model/controller       physical world
“forward” ──► velocity request ──► forces, contact, slip
                    ▲                         │
                    │                         ▼
              revise model ◄──── sensors and residual

       command accepted ≠ body moved ≠ task complete
~~~

## Worked Parcel / Go2 example

Suppose Parcel requests 0.50 m/s for 2.0 s. A constant-speed model predicts:

~~~text
d = v t = (0.50 m/s)(2.0 s) = 1.0 m
~~~

These numbers are illustrative, not commissioned Go2 limits. Imagine fused pose reports 0.86 m of progress. The residual is:

~~~text
0.86 m - 1.00 m = -0.14 m
~~~

That residual could come from acceleration ramps, floor slip, estimator error, delayed timestamps, or an early safety clamp. It does not justify arbitrarily adding 0.14 m to the next command. First identify which assumption failed. Task completion should use measured or estimated pose and a tolerance, not elapsed command time.

## Software-engineering analogy

A model resembles an interface contract plus an SLO. It declares accepted inputs, expected behavior, and failure bounds. The physical plant resembles a distributed dependency whose state is only indirectly observable. An RPC acknowledgement says the request crossed a boundary; it does not provide linearizability with reality.

Residuals play the role of invariant violations. Instrument them rather than hiding them with retries. If predicted and observed stopping distance diverge, the correct response is to lower energy and investigate, not tune until one scenario passes.

## Parcel / Go2 bridge

Parcel’s high-level behavior and navigation create bounded motion intentions. The exclusive control path supervises Unitree Sport, which closes faster balance and gait loops. Feedback, watchdogs, and safety gates turn that hierarchy into a closed-loop system. Physics remains the final authority at every layer.

Companion reading: [Robotics Day 01 — Physical Truth vs Software State](../robotics-60-days/day-01-physical-truth.md).

## Failure and safety note

Never derive a hardware-safe speed, payload, temperature, or stopping margin from a course example or simulator result. Use vendor documentation, instrument the particular robot, start at low energy, and keep an operator able to stop it. Do not open batteries, energize exposed conductors, restrain powered joints by hand, or stand in a robot’s predicted path.

## Retrieval questions

1. What six items should you name before trusting a physical model?
2. Why does a dimensionally correct equation remain capable of producing a bad prediction?
3. What does a motion-command acknowledgement prove, and what does it not prove?

## Optional 10-minute exercise

Choose one logged Parcel quantity. Write its value, unit, frame if applicable, timestamp or freshness, model assumption, and one independent sensor that could challenge it. No powered hardware is required.
