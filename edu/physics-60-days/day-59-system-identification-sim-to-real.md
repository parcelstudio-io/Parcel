# Day 59: System Identification and Sim-to-Real

## Mental model

System identification estimates model parameters from known inputs and measured outputs. Sim-to-real then asks whether conclusions remain valid across parameter uncertainty, unmodeled effects, and sensors. The objective is not to make one replay look perfect. It is to build the simplest model whose residuals and sensitivity are honest enough for the decision being tested.

Parcel need not identify Unitree's private joint controller to improve companion navigation. It can identify the supported body-command response: delay, rise and settling, directional asymmetry, braking distribution, odometry drift, sensor noise/dropout, and effects of surface or payload. Sport remains the fast balance/gait controller and the simulator adapter preserves the same outer contract.

## Quantities, units, and assumptions

- parameter vector `theta`: masses, friction, delay, time constants, noise scales
- input `u_k`: timestamped admitted command
- output `y_k`: timestamped measured response
- residual `r_k = y_k - y_hat_k`: output unit
- weighting matrix `W`: entry units make `r^T W r` dimensionless; for a covariance inverse, diagonal entries have inverse-squared component units and mixed entries use inverse products
- training and validation runs: distinct datasets
- domain distribution `p(theta)`: plausible parameter ranges and correlations

Identifiability matters: different parameter combinations can generate similar outputs. A fitted “friction” may actually absorb controller delay or estimator filtering unless experiments excite distinguishable behavior.

## Core equations

~~~text
y_hat_k = model(u_0...u_k; theta)
r_k = y_k - y_hat_k
theta_star = argmin_theta sum_k r_k^T W r_k

constant-deceleration estimate from speed and distance:
a_b = v_0^2/(2 d_brake)

domain randomization / sensitivity: theta ~ p(theta)
evaluate metric distribution, not only metric at nominal theta
~~~

Hold out runs for validation. Parameter fitting error and task success are different metrics.

## ASCII diagram

~~~text
 logged command u ----> candidate model(theta) ----> predicted y_hat
       |                                             |
       +---- measured y ---- residual ---------------+
                              |
                       fit on train runs
                       validate on held-out surfaces/modes

 calibrated ranges -> randomized headless eval -> promotion evidence
~~~

## Worked Parcel / Go2 example

Suppose a low-energy, properly commissioned test or trusted log shows illustrative initial body speed `0.50 m/s` and measured stopping travel `0.18 m` after response delay has been separated. A constant-deceleration fit gives:

~~~text
a_b = 0.50^2/(2 × 0.18) = 0.694 m/s^2
~~~

This single value is not a safety limit. Repeat runs produce a distribution; surfaces, direction, turn rate, gait, payload, battery, and estimator error matter. The conservative stopping model should use characterized tails plus latency and uncertainty, not the mean fit.

For simulation, fit outer response and sensor models, then sweep broader plausible ranges. Keep an unchanged Parcel behavior behind an eval adapter. Log date, run ID, commit/config/model identity, scenario seed, change description, metrics, and failures. A score gain that depends on simulator truth or modified task semantics is invalid even if the leaderboard number rises.

## Software-engineering analogy

Identification is performance-model fitting from traces. Overfitting one benchmark host creates a capacity model that fails in production. Domain randomization is chaos testing over physical configuration, while held-out validation is a real canary—not replaying the training incident and calling it coverage.

## Parcel / Go2 bridge

Use identification to improve smoother timing, prediction, stopping envelopes, and simulator fidelity while preserving typed behavior and motion authority. Learned proposals must still pass collision/reactive gates. Read [Day 37: The Reality Gap](../robotics-60-days/day-37-reality-gap.md), [Day 38: Testing and Evaluation](../robotics-60-days/day-38-testing-evaluation.md), and [`docs/INSTRUCTION_NAV_HILLCLIMB.md`](../../docs/INSTRUCTION_NAV_HILLCLIMB.md).

## Failure and safety note

Identification can invite increasingly energetic excitation. Do not perform hardware maneuvers outside a commissioned protocol, and stop on slip, tilt, thermal, power, or communications faults. Never reduce simulator diversity merely to raise nominal success. Preserve raw logs and distinguish measured, estimated, and simulator-truth fields.

## Retrieval questions

1. Why can a low residual on fitting runs still produce a bad sim-to-real model?
2. Which outer response parameters are useful without reverse-engineering Sport's joint controller?
3. What metadata makes an eval score reproducible and guards against benchmark-only behavior changes?

## Optional 10-minute exercise

Create a paper identification plan for command delay and first-order time constant: inputs, measured outputs, operating point, train/holdout split, and residual plots. Add five simulator parameters to sweep. Do not collect new hardware data.
