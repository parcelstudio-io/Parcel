# Day 57: Collision Physics and Stopping Margins

## Mental model

Avoiding collision requires more than detecting an obstacle at the current pose. During sensing, processing, command delivery, and actuator response, the robot continues moving. It then needs distance to decelerate, and every quantity is uncertain. A stopping margin is therefore a budget containing reaction travel, braking travel, state error, obstacle motion, and a residual safety buffer.

Kinetic energy and braking distance grow with speed squared. A modest speed increase can invalidate a clearance that looked generous at walking pace. Navigation may prefer smooth forward motion after turning toward the goal, while retaining bounded lateral velocity for local maneuvers; every component must be evaluated against the appropriate directional sensing and stopping envelope.

## Quantities, units, and assumptions

- robot speed `v`: metre per second (`m/s`)
- reaction delay `t_r`: second (`s`)
- effective braking magnitude `a_b`: metre per second squared (`m/s^2`)
- separation `d`: metre (`m`)
- relative velocity `v_rel`: metre per second (`m/s`) in a common frame
- line-of-sight closing speed `v_close`: metre per second (`m/s`)
- time to collision `TTC`: second (`s`)
- uncertainty and fixed buffer: metre (`m`)

Constant deceleration assumes level terrain, sufficient traction, known motion direction, and no gait transition. A legged controller may not realize the same deceleration on tile, gravel, slope, or while turning. Hardware evidence must replace textbook estimates.

## Core equations

~~~text
reaction distance = v t_r
ideal braking distance = v^2/(2 a_b)
d_stop = v t_r + v^2/(2 a_b)
v_rel = v_obstacle - v_robot
v_close = -r_hat dot v_rel
TTC = separation / v_close             when v_close > 0
kinetic energy = (1/2) m v^2
rough friction bound on level ground: a <= mu g
~~~

A production threshold adds localization/perception error, obstacle prediction error, body radius, command variation, and a tested buffer to `d_stop`.

## ASCII diagram

~~~text
 robot ---> | reaction travel | braking travel | uncertainty | buffer | obstacle
             <---------------- required margin ---------------------->

 camera: object/owner semantics
 LiDAR: fresh geometry -> independent brake/veto -> zero leased command
~~~

## Worked Parcel / Go2 example

Assume illustrative values `v = 0.60 m/s`, total reaction delay `t_r = 0.15 s`, and characterized deceleration `a_b = 1.20 m/s^2`:

~~~text
reaction = (0.60)(0.15) = 0.090 m
braking = 0.60^2/(2 × 1.20) = 0.150 m
ideal d_stop = 0.240 m
~~~

If combined geometry, motion-prediction, and residual buffer is illustratively 0.25 m, the threshold becomes at least 0.49 m before considering body shape or an approaching person. Doubling speed to 1.20 m/s doubles reaction travel but quadruples the braking term. These are teaching values, not commissioned Go2 speeds, deceleration, or clearance.

For a pedestrian, use relative closing speed in one frame rather than robot speed alone. Here `r_hat` points from robot to obstacle and separation should be the relevant surface clearance, not center-to-center distance. This scalar TTC still assumes constant relative velocity and detects only current line-of-sight closure; predicted trajectory intersection needs a geometric collision calculation. A person stepping toward the path can reduce TTC even while the dog is already slowing. Camera tracks help classify and predict people; LiDAR geometry and a local reactive gate must still be able to veto motion without waiting for language reasoning.

## Software-engineering analogy

Stopping margin is a distributed timeout budget with irreversible side effects. Reaction distance is work already in flight; braking distance is drain time; uncertainty is clock skew and unobserved queue state. Setting one global timeout from average latency is as unsafe as sizing clearance from average perception delay.

## Parcel / Go2 bridge

The planner may choose a route, but collision and reactive-safety functions own veto authority before `CommandArbiter` and `ControlManager`. Completion also requires settled measured motion. Read [Day 28: Smooth Local Navigation](../robotics-60-days/day-28-smooth-local-navigation.md), [Day 35: Safety Engineering](../robotics-60-days/day-35-safety-engineering.md), and [`docs/NAVIGATION_CITY.md`](../../docs/NAVIGATION_CITY.md).

## Failure and safety note

Never copy illustrative deceleration into hardware configuration. Measure tails across relevant surfaces, directions, battery states, payloads, turns, and gait modes under a commissioned procedure. Treat missing/stale LiDAR as unknown, keep the E-stop local, and ensure a crashed high-level process causes leased motion to expire to stop.

## Retrieval questions

1. What terms belong in a conservative stopping-margin budget?
2. Why does doubling speed more than double ideal stopping distance?
3. Why must Parcel's reactive collision veto remain independent of the LLM and semantic planner?

## Optional 10-minute exercise

Using the illustrative model only, tabulate ideal stopping distance at 0.2, 0.4, 0.6, and 0.8 m/s for `t_r = 0.15 s` and `a_b = 1.2 m/s^2`. Repeat at `t_r = 0.30 s`. Do not transfer the table to hardware limits.
