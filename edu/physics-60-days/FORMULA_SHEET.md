# Parcel Physics Formula Sheet

This sheet is a memory aid, not a substitute for drawing the system, frame, forces, and assumptions. Symbols are defined locally because the same letter can mean different things in different fields.

## SI quantities used most often

| Quantity | Symbol | SI unit | In base units |
| --- | --- | --- | --- |
| Time | `t` | second (`s`) | `s` |
| Distance / position | `x`, `r` | metre (`m`) | `m` |
| Angle | `theta` | radian (`rad`) | dimensionless ratio |
| Mass | `m` | kilogram (`kg`) | `kg` |
| Temperature | `T` | kelvin (`K`) | `K` |
| Velocity | `v` | metres per second (`m/s`) | `m s^-1` |
| Acceleration | `a` | metres per second squared (`m/s^2`) | `m s^-2` |
| Angular velocity | `omega` | radians per second (`rad/s`) | `s^-1` |
| Force | `F` | newton (`N`) | `kg m s^-2` |
| Torque | `tau` | newton metre (`N m`) | `kg m^2 s^-2` |
| Energy / work | `E`, `W` | joule (`J`) | `kg m^2 s^-2` |
| Power | `P` | watt (`W`) | `kg m^2 s^-3` |
| Pressure / stress | `p`, `sigma` | pascal (`Pa`) | `kg m^-1 s^-2` |
| Electric charge | `q` | coulomb (`C`) | `A s` |
| Current | `I` | ampere (`A`) | `A` |
| Voltage | `V` | volt (`V`) | `kg m^2 s^-3 A^-1` |
| Resistance | `R` | ohm (`Ω`, often `ohm` in ASCII) | `kg m^2 s^-3 A^-2` |
| Frequency | `f` | hertz (`Hz`) | `s^-1` |

Useful prefixes: `m` milli = `10^-3`, `µ` micro = `10^-6` (often `u` in ASCII identifiers), `n` nano = `10^-9`, `k` kilo = `10^3`, `M` mega = `10^6`, `G` giga = `10^9`. Case matters: `mW` is a milliwatt; `MW` is a megawatt.

## Motion

Average and instantaneous rates:

```text
average velocity:       v_avg = Delta x / Delta t
instantaneous velocity: v = dx/dt
acceleration:            a = dv/dt = d^2x/dt^2
jerk:                    j = da/dt
position from velocity:  Delta x = integral(v dt)
velocity from accel.:    Delta v = integral(a dt)
```

Constant acceleration in one dimension:

```text
v = v0 + a t
x = x0 + v0 t + (1/2) a t^2
v^2 = v0^2 + 2 a (x - x0)
```

Stopping approximation with reaction delay `t_r` and braking magnitude `a_b > 0`:

```text
d_stop = v t_r + v^2 / (2 a_b)
```

This is a nominal idealized estimate, not a safety bound. A conservative bound requires measured worst-case delay and braking behavior plus margins for grade, traction, estimator error, footprint, obstacle motion, and uncertainty.

Angular motion and circular motion:

```text
arc length:            s = r theta              (theta in radians)
tangential speed:      v = r omega
angular acceleration: alpha = d omega/dt
centripetal accel.:    a_c = v^2/r = r omega^2
period/frequency:      T = 1/f
```

## Vectors and frames

Two-dimensional vector magnitude and dot product:

```text
|v| = sqrt(v_x^2 + v_y^2)
a dot b = |a| |b| cos(theta)
```

Planar rotation from body coordinates to world coordinates:

```text
[x_w]   [ cos(yaw)  -sin(yaw) ] [x_b]
[y_w] = [ sin(yaw)   cos(yaw) ] [y_b]
```

Write the frame on every physical vector. A bare tuple `(0.3, 0.0)` is not a complete motion contract.

## Forces, contact, and energy

Newton's second law and gravitational weight near Earth's surface:

```text
sum(F) = m a
weight magnitude = m g, where g approximately 9.81 m/s^2
```

Ideal dry-friction model:

```text
static:   |F_tangent| <= mu_s N
sliding:  |F_tangent| approximately mu_k N
```

Real feet and terrain do not obey one fixed coefficient. Treat `mu` as a model parameter and test sensitivity.

Work, energy, and power:

```text
work by constant force: W = F dot Delta x
kinetic energy:         K = (1/2) m v^2
gravitational energy:   U_g = m g h
spring energy:          U_s = (1/2) k x^2
power:                  P = dW/dt = F dot v
efficiency:             eta = useful output / input
```

Momentum and impulse:

```text
momentum: p = m v
impulse:  J = integral(F dt) = Delta p
```

Linear spring and viscous damper:

```text
F_s = -k x
F_d = -c v
```

## Rotation and balance

Torque and rotational dynamics about a chosen point:

```text
tau = r cross F
|tau| = r F sin(theta)
sum(tau) = I alpha                     (fixed axis, constant I)
rotational energy = (1/2) I omega^2
angular momentum = I omega             (fixed-axis form)
```

For point masses about an axis:

```text
I = sum(m_i r_i^2)
```

Static equilibrium:

```text
sum(F) = 0
sum(tau) = 0
```

A stationary robot on level rigid ground is statically stable when the vertical projection of its center of mass lies inside its contact support region. Walking is dynamic, contacts are finite, and the onboard locomotion controller uses a richer model.

## Legs and rigid bodies

Kinematic mapping near one configuration:

```text
foot velocity:       v_foot = J(q) q_dot
joint torque:        tau_actuator = J(q)^T F_out
```

Here `F_out` is the force the limb exerts on the environment under the chosen sign convention. If `F_ext` instead denotes the environment's force on the foot, its generalized joint torque is `J(q)^T F_ext`; the actuator torque that statically opposes it has the negative sign, before gravity and other terms. The transpose equation expresses virtual-work duality. Near a singular configuration, small task-space requests can require extreme joint rates or efforts.

Rigid-body twist convention used in Parcel's application layer:

```text
twist = [v_x, v_y, yaw_rate]
```

The `yaw_rate` component is named `vyaw` in Parcel's velocity contract. The physical Go2 has six body degrees of freedom and twelve actuated leg joints; Parcel's high-level Sport boundary intentionally requests a bounded planar body twist rather than joint torque.

## Electricity, motors, and batteries

Circuits and power:

```text
Ohm's law:             V = I R
electrical power:      P = V I = I^2 R = V^2/R
energy:                E = integral(P dt)
Kirchhoff current law: sum(current into a node) = 0
Kirchhoff voltage law: sum(voltage around a loop) = 0
```

Ideal capacitor and inductor:

```text
capacitor: i = C dV/dt,  stored energy = (1/2) C V^2
inductor:  V = L di/dt,  stored energy = (1/2) L I^2
```

Simplified motor relationships:

```text
motor torque:          tau approximately k_t I
back EMF:              V_emf approximately k_e omega
mechanical power:      P_mech = tau omega
electrical input:      P_elec = V I
```

The constants, winding resistance, controller, saturation, gearing, temperature, and losses all matter in real hardware.

Battery energy estimate:

```text
energy (Wh) approximately nominal voltage (V) * capacity (Ah)
runtime (h) approximately usable energy (Wh) / average load (W)
```

This is a planning estimate, not a safe state-of-charge estimator. Voltage sag, temperature, age, discharge rate, cell balance, and BMS cutoffs matter.

## Heat, structures, and fluids

Heating and conduction:

```text
sensible heat: Q = m c_p Delta T
conduction rate: Q_dot = k A Delta T / L
thermal resistance: R_theta = Delta T / Q_dot
```

Stress and strain in a simple axial member:

```text
normal stress: sigma = F/A
normal strain: epsilon = Delta L/L
linear elastic region: sigma = E epsilon
```

Fluid pressure and a common drag model:

```text
pressure: p = F/A
dynamic pressure: q = (1/2) rho v^2
drag: F_D = (1/2) rho C_D A v^2
```

## Waves, audio, optics, and ranging

Wave relationship:

```text
wave speed: c = f lambda
```

Sound pressure level relative to reference pressure `p0`:

```text
SPL = 20 log10(p_rms / p0) dB
```

Decibels describe a ratio. Adding dB values directly is usually wrong unless the full power/amplitude relationship and correlation are known.

Thin-lens model and approximate pinhole projection:

```text
1/f = 1/d_object + 1/d_image
image coordinate u approximately f_x X/Z + c_x
image coordinate v approximately f_y Y/Z + c_y
```

Ideal round-trip time-of-flight range:

```text
range = c_light Delta t / 2
```

The factor of two is the outward and return path. Reflectivity, incidence angle, multipath, weather, synchronization, and calibration cause real errors.

## Sampling, uncertainty, and control

Sampling and data age:

```text
sample period: T_s = 1/f_s
Nyquist condition for a band-limited signal: f_s > 2 f_max
measurement age: age = now - sensor_timestamp
```

Independent uncertainty propagation for a sum `z = x + y`:

```text
sigma_z^2 = sigma_x^2 + sigma_y^2
```

Simple controller terms:

```text
error: e(t) = target - measurement
PID:   u(t) = K_p e + K_i integral(e dt) + K_d de/dt
first-order step response: y(t) = K(1 - exp(-t/tau))
```

Closed loop does not mean safe by itself. Sensor freshness, actuator saturation, delay, sign, units, frames, watchdogs, and an independent stop path remain part of the physical contract.

## Always run these checks

1. **Dimensions:** do both sides have the same base units?
2. **Sign:** did you choose and preserve a positive direction?
3. **Frame:** body, odom, map, sensor, or joint frame?
4. **Scale:** is the answer within an order of magnitude of reality?
5. **Limit:** did a linear, rigid, static, ideal, or no-slip assumption fail?
6. **Evidence:** what measured signal verifies the predicted result?
7. **Safety:** what stops the robot if the model is wrong?
