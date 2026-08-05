# Physics for Robot Builders: Day 0 to Day 60

This is a companion to [Robotics Systems for Senior Software Engineers](../robotics-60-days/README.md). It teaches the physics needed to reason about **Parcel on a Unitree Go2** without assuming prior hardware coursework.

Use Day 0 as a preflight, then read one lesson per day for Days 1–60 in about
15–25 minutes. Each lesson has one mental model, a small set of equations with
SI units, a worked robot-dog example, an engineering failure mode, retrieval
questions, and a short desk or simulator exercise. The numbers in worked
examples are intentionally simple and illustrative; do not treat them as
commissioned Go2 limits.

## How to use the two courses

The robotics course explains the complete software/hardware stack. This course slows down the physical concepts that stack relies on. You do **not** need to keep the day numbers synchronized. Follow each lesson's “Companion reading” link when you want the matching systems view.

The kinematics, Jacobian, force-mapping, and balance lessons explain what a locomotion controller must reason about; they do not change Parcel's authority boundary. Parcel currently sends a leased, bounded planar body-velocity request in `base_link` to Unitree Sport. Sport owns gait, foot placement, balance, and actuator-level execution.

For every equation, use this five-step loop:

1. Name the physical system and boundary.
2. Draw the directions and coordinate frame.
3. Write known values with units.
4. Compute and check dimensions.
5. Ask what sensor could falsify the result.

Keep a notebook with one page per day. Prediction before measurement is the habit this course is trying to build.

## Module 0: Orientation

| Day | Lesson | Topic |
| ---: | --- | --- |
| 0 | [Physics is the contract](day-00-physics-is-the-contract.md) | Models, measurement, approximation, and safe experimentation |

## Module 1: Measurement and motion — Days 1–10

| Day | Lesson | Topic |
| ---: | --- | --- |
| 1 | [Units, dimensions, and estimates](day-01-units-dimensions-estimates.md) | SI units, dimensional checks, order-of-magnitude reasoning |
| 2 | [Scalars, vectors, and frames](day-02-scalars-vectors-frames.md) | Magnitude, direction, components, body and world frames |
| 3 | [Position, displacement, and distance](day-03-position-displacement-distance.md) | State versus path length |
| 4 | [Velocity and relative velocity](day-04-velocity-relative-motion.md) | Rates, direction, and owner-relative motion |
| 5 | [Acceleration](day-05-acceleration.md) | Changing velocity and felt motion |
| 6 | [Motion graphs and calculus intuition](day-06-motion-graphs-calculus.md) | Slope, area, derivative, and integral |
| 7 | [Constant-acceleration motion](day-07-constant-acceleration-braking.md) | Prediction and braking distance |
| 8 | [Two-dimensional and relative motion](day-08-two-dimensional-motion.md) | Decomposition, pursuit, and formation motion |
| 9 | [Angular motion](day-09-angular-motion.md) | Radians, yaw rate, tangential speed |
| 10 | [Motion synthesis](day-10-motion-synthesis.md) | Trace a command into measurable motion |

## Module 2: Forces, energy, and balance — Days 11–20

| Day | Lesson | Topic |
| ---: | --- | --- |
| 11 | [Newton's laws](day-11-newtons-laws.md) | Inertia, net force, and interaction pairs |
| 12 | [Free-body diagrams](day-12-free-body-diagrams.md) | Isolating a body and accounting for forces |
| 13 | [Gravity, weight, and normal force](day-13-gravity-weight-normal-force.md) | Mass versus weight and contact support |
| 14 | [Friction, traction, and slip](day-14-friction-traction-slip.md) | Contact limits and why commands do not guarantee motion |
| 15 | [Springs, compliance, and damping](day-15-springs-compliance-damping.md) | Energy storage, shock absorption, and oscillation control |
| 16 | [Work and mechanical energy](day-16-work-energy.md) | Kinetic and potential energy |
| 17 | [Power and efficiency](day-17-power-efficiency.md) | How quickly energy moves and where it is lost |
| 18 | [Momentum, impulse, and collision](day-18-momentum-impulse-collision.md) | Stopping, impacts, and contact duration |
| 19 | [Torque and levers](day-19-torque-levers.md) | Turning effects and joint loading |
| 20 | [Center of mass and static stability](day-20-center-of-mass-stability.md) | Support regions, tipping, and stance |

## Module 3: Rigid bodies and legged motion — Days 21–30

| Day | Lesson | Topic |
| ---: | --- | --- |
| 21 | [Rotational inertia](day-21-rotational-inertia.md) | Mass distribution and angular acceleration |
| 22 | [Rigid-body pose and twist](day-22-rigid-body-pose-twist.md) | Translation, rotation, and body velocity |
| 23 | [Links, joints, and degrees of freedom](day-23-links-joints-dof.md) | How morphology constrains motion |
| 24 | [Forward and inverse kinematics](day-24-forward-inverse-kinematics.md) | Joint angles and foot position |
| 25 | [Jacobians and velocity mapping](day-25-jacobians-velocity.md) | Local sensitivity and singularities |
| 26 | [Force and torque through a Jacobian](day-26-jacobian-force-mapping.md) | Foot forces and joint effort |
| 27 | [Statics and load distribution](day-27-statics-load-distribution.md) | Sharing body load across feet |
| 28 | [Gaits and contact sequences](day-28-gaits-contact-sequences.md) | Stance, swing, duty factor, and phase |
| 29 | [Dynamic balance](day-29-dynamic-balance.md) | Capture point and zero-moment-point intuition |
| 30 | [Legged locomotion synthesis](day-30-legged-locomotion-synthesis.md) | Turn-first, forward-preferred motion with bounded lateral velocity |

## Module 4: Electricity, actuators, heat, and materials — Days 31–40

| Day | Lesson | Topic |
| ---: | --- | --- |
| 31 | [Charge, current, voltage](day-31-charge-current-voltage.md) | Electrical quantities and energy per charge |
| 32 | [Resistance and circuits](day-32-resistance-circuits.md) | Ohm's law, Kirchhoff's laws, series and parallel paths |
| 33 | [Fields and electromagnetism](day-33-fields-electromagnetism.md) | How current and magnetic fields create force |
| 34 | [Electric motors](day-34-electric-motors.md) | Torque constant, back EMF, and motor limits |
| 35 | [Gears and transmissions](day-35-gears-transmissions.md) | Torque-speed tradeoffs and reflected inertia |
| 36 | [Batteries and stored energy](day-36-batteries-energy.md) | Cells, voltage sag, state of charge, and safe handling |
| 37 | [Robot power budgets](day-37-robot-power-budget.md) | Mechanical, electrical, peak, and average power |
| 38 | [Thermodynamics and heat transfer](day-38-thermodynamics-heat.md) | Temperature, heat capacity, conduction, convection, radiation |
| 39 | [Stress, strain, stiffness, and fatigue](day-39-materials-stress-strain.md) | Why structures bend and eventually fail |
| 40 | [Pressure, fluids, and weather](day-40-fluids-environment.md) | Airflow, water, seals, wind, and environmental loads |

## Module 5: Oscillations, sound, light, and sensors — Days 41–50

| Day | Lesson | Topic |
| ---: | --- | --- |
| 41 | [Oscillation and resonance](day-41-oscillation-resonance.md) | Natural frequency and vibration |
| 42 | [Waves](day-42-waves.md) | Frequency, wavelength, phase, and superposition |
| 43 | [Sound and decibels](day-43-sound-decibels.md) | Acoustic pressure, distance, reflection, and logarithmic level |
| 44 | [Microphones and speakers](day-44-microphones-speakers.md) | Turning sound into voltage and back |
| 45 | [Echo and full-duplex acoustics](day-45-echo-full-duplex-acoustics.md) | Acoustic echo paths and why the reference signal matters |
| 46 | [Light and radio](day-46-light-radio.md) | Electromagnetic waves, reflection, absorption, antennas, and Bluetooth |
| 47 | [Lenses and image formation](day-47-lenses-image-formation.md) | Focal length, field of view, focus, and depth |
| 48 | [Camera measurement physics](day-48-camera-measurement.md) | Exposure, motion blur, rolling shutter, and pixels |
| 49 | [LiDAR time of flight](day-49-lidar-time-of-flight.md) | Range, reflectivity, angular resolution, and occlusion |
| 50 | [IMU physics](day-50-imu-physics.md) | Specific force, angular rate, gravity, bias, and integration drift |

## Module 6: Measurement, feedback, and simulation — Days 51–60

| Day | Lesson | Topic |
| ---: | --- | --- |
| 51 | [Sampling, aliasing, and quantization](day-51-sampling-aliasing-quantization.md) | Turning continuous physics into discrete data |
| 52 | [Noise, uncertainty, and filtering](day-52-noise-uncertainty-filtering.md) | Random error, bandwidth, and delay |
| 53 | [Calibration, bias, drift, and fusion](day-53-calibration-bias-drift-fusion.md) | Combining imperfect sensors without inventing certainty |
| 54 | [Open-loop and closed-loop control](day-54-open-closed-loop-control.md) | Feedback, disturbance rejection, and nested loops |
| 55 | [First- and second-order dynamics](day-55-system-dynamics.md) | Time constants, overshoot, damping ratio, and bandwidth |
| 56 | [PID, delay, and stability](day-56-pid-delay-stability.md) | Correction terms and why late feedback destabilizes |
| 57 | [Collision physics and stopping margins](day-57-collision-stopping-margins.md) | Reaction distance, braking distance, and time to collision |
| 58 | [What a physics simulator computes](day-58-physics-simulation.md) | Integration, constraints, contacts, and timestep |
| 59 | [System identification and sim-to-real](day-59-system-identification-sim-to-real.md) | Estimating parameters and testing sensitivity |
| 60 | [Parcel physical design review](day-60-parcel-physical-design-review.md) | Capstone: defend the robot's physical assumptions with evidence |

## Course artifacts

- [Formula sheet](FORMULA_SHEET.md): symbols, units, and the small equation set worth retaining.
- [Glossary](GLOSSARY.md): physics terms translated for software engineers.
- [References](REFERENCES.md): free, stable sources for deeper study.

## Safety boundary

Desk calculations and simulation are learning tools, not hardware commissioning evidence. Never infer a safe speed, load, temperature, battery state, or stopping distance from a lesson example. Obtain the correct vendor limits, instrument the physical robot, begin at low energy, keep an operator at the hardware E-stop, and validate each assumption on the specific robot and surface.
