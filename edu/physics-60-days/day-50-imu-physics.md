# Day 50: IMU Physics

## Mental model

An inertial measurement unit usually contains gyroscopes and accelerometers. A gyro measures angular rate. An accelerometer measures **specific force**: non-gravitational force per unit mass expressed in the sensor frame. A supported accelerometer at rest therefore reads approximately one `g` upward, because the surface is pushing it against gravity. In ideal free fall it reads near zero.

Integrating rates creates orientation, velocity, and position, but tiny biases accumulate. An IMU is excellent for fast relative motion and terrible as a standalone long-term position oracle. Contact, camera, LiDAR, odometry, and physical constraints are needed to bound drift.

## Quantities, units, and assumptions

- angular rate `omega`: radian per second (`rad/s`)
- specific force `f`: metre per second squared (`m/s^2`)
- gravitational acceleration magnitude `g`: about `9.81 m/s^2` near Earth's surface
- gyro bias `b_g`: `rad/s`
- accelerometer bias `b_a`: `m/s^2`
- sample interval `Delta t`: second (`s`)
- orientation: quaternion or rotation matrix, dimensionless

The basic integration equations assume correct axes, scale, timestamps, and calibration. Temperature, vibration, saturation, and coning motion change real behavior.

## Core equations

Using `R` from sensor to world and world gravity vector `g_w`:

~~~text
accelerometer: f_meas = R^T (a_world - g_w) + b_a + noise
gyro: omega_meas = omega_true + b_g + noise
angle_error from constant gyro bias approximately b_g t
velocity_error from constant accel bias approximately b_a t
position_error from constant accel bias approximately (1/2) b_a t^2
~~~

Gravity removal requires an orientation estimate; orientation estimation itself uses IMU and other evidence. That circular dependence is handled by a state estimator, not by subtracting `9.81` from one fixed axis.

## ASCII diagram

~~~text
                 world z
                    ^
 support force -----|------> accelerometer reads specific force
                    [IMU]  body axes rotate with dog
 gravity acts down   |

 gyro rates --integrate--> attitude --rotate/remove gravity--> acceleration
      bias               \------------------------------------> drift
~~~

## Worked Parcel / Go2 example

An illustrative gyro bias of 0.5 degrees/s creates, without correction:

~~~text
yaw error after 60 s = (0.5 deg/s)(60 s) = 30 degrees
~~~

An accelerometer bias of only `0.05 m/s^2`, integrated as world acceleration for 60 s, gives:

~~~text
position error approximately 0.5(0.05 m/s^2)(60 s)^2 = 90 m
~~~

The dramatic result is not a prediction of Go2 odometry; it demonstrates why raw double integration is insufficient. Unitree Sport uses fast body sensing internally for balance, and Parcel may consume estimated body motion and faults through its control boundary. The companion's environmental understanding still relies on camera and LiDAR, not an LLM reading raw IMU samples.

## Software-engineering analogy

An IMU is a high-rate event stream whose offsets compound during event sourcing. Bias is a small clock skew applied to every event; integration turns it into a large state divergence. External observations are snapshots that re-anchor the log, while a filter maintains uncertainty between them.

## Parcel / Go2 bridge

Keep the authority boundary clear: Sport's internal IMU/encoder loop balances the body; Parcel reasons from typed `RobotMotionState`, camera, and LiDAR. The reasoning model should never close a balance loop or reinterpret raw axes. Continue with [Day 24: IMU, Odometry, Drift, and Slip](../robotics-60-days/day-24-imu-odometry-drift.md) and [`docs/MOTION.md`](../../docs/MOTION.md).

## Failure and safety note

A stationary calibration on a desk does not characterize vibration, temperature, clipping, or mounting flex during gait. Axis-sign mistakes can look plausible until a turn. Never test balance by injecting corrected IMU values into hardware. Validate offline logs and simulator interfaces first, then use vendor-supported telemetry under restrained, low-energy procedures.

## Retrieval questions

1. What does an accelerometer at rest on a table measure, and why?
2. Why does constant accelerometer bias create position error proportional to time squared?
3. Which layer uses fast inertial feedback for Go2 balance, and which sensors give Parcel environmental evidence?

## Optional 10-minute exercise

Compute yaw drift after 10, 60, and 300 s for biases of 0.05 and 0.5 degrees/s. Compute position error after 10 and 60 s for `b_a = 0.01 m/s^2`. Then inspect a recorded or simulated stationary IMU trace only if one already exists; do not move powered hardware.
