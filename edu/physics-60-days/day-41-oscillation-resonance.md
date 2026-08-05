# Day 41: Oscillation and Resonance

## Mental model

An oscillation is energy repeatedly moving between two forms. A flexible mount stores elastic energy when it bends, then returns that energy as motion. Mass resists the change, while damping converts some organized motion into heat. If a repeating force arrives near the system's natural frequency, each push can reinforce the last one. That large response is resonance.

Robots contain many oscillators: legs and compliant feet, a camera mast, speaker cones, cable bundles, body panels, and even a controller correcting too aggressively. “Rigid” is always an approximation. The engineering goal is not to remove every vibration; it is to keep important modes away from strong excitation or add enough damping that they do not grow.

## Quantities, units, and assumptions

- displacement `x`: metre (`m`)
- mass `m`: kilogram (`kg`)
- stiffness `k`: newton per metre (`N/m`)
- damping coefficient `c`: newton-second per metre (`N s/m`)
- angular frequency `omega`: radians per second (`rad/s`)
- frequency `f`: hertz (`Hz`)
- damping ratio `zeta`: dimensionless

The basic model assumes one direction, small deformation, linear stiffness, viscous damping, and fixed parameters. Real robot structures have many coupled modes, joints with backlash, nonlinear rubber, and excitation that changes with gait and terrain.

## Core equations

For a driven mass-spring-damper:

~~~text
m x_ddot + c x_dot + k x = F(t)
omega_n = sqrt(k/m)
f_n = omega_n / (2 pi)
zeta = c / (2 sqrt(k m))
~~~

`omega_n` is the undamped natural angular frequency. A small `zeta` means ringing persists; `zeta = 1` is critical damping in this ideal second-order model. A periodic input near `f_n` can produce a response much larger than the static deflection `F/k`.

## ASCII diagram

~~~text
 fixed body          flexible payload
 |                   +---------+
 |----/\/\/\----[damper]----[ m ]  -> x
        k          c

 gait force F(t) -> stored spring energy <-> kinetic energy
                                      \-> heat through damping
~~~

## Worked Parcel / Go2 example

Suppose an illustrative 0.080 kg microphone assembly and mount have an effective lateral stiffness of 800 N/m. Ignoring damping:

~~~text
omega_n = sqrt(800 N/m / 0.080 kg) = 100 rad/s
f_n = 100 / (2 pi) = 15.9 Hz
~~~

If a gait, cooling fan, or repeated foot impact has substantial energy near 16 Hz, the array may shake more than expected. Camera blur, microphone handling noise, and loose-fastener fatigue can all follow even though the body trajectory looks smooth. Changing the mount mass or stiffness shifts the mode; an elastomer may add damping but can also lower stiffness. These numbers are illustrative, not measured Go2 or mount properties. The correct next step is an unpowered tap test or low-energy instrumented sweep, not guessing a “safe” gait rate.

## Software-engineering analogy

Resonance resembles a retry loop whose interval aligns with a slow dependency. Each individually modest request arrives at the worst phase and the queue grows. Damping resembles backpressure that removes accumulated energy. Adding stiffness is not automatically a fix, just as increasing concurrency is not: it moves the failure frequency and can transfer load elsewhere.

## Parcel / Go2 bridge

Unitree Sport owns fast balance and gait response, but Parcel can avoid exciting the body with discontinuous high-level commands. Jerk-limited velocity shaping, sound payload mounting, and camera exposure choices all depend on vibration. Compare the systems treatment in [Day 12: Signals, Noise, Filtering, and Delay](../robotics-60-days/day-12-signals-noise-filtering-delay.md) and the physical controller boundary in [`docs/MOTION.md`](../../docs/MOTION.md).

## Failure and safety note

A simulator with a perfectly rigid sensor mount can hide a real resonant mode. Conversely, a dramatic vibration in a visualizer may be a numerical artifact. Never identify a mode by increasing hardware excitation until something visibly shakes. Begin unpowered where possible, secure the robot, use low-amplitude tests, respect vendor limits, and stop if fasteners loosen, temperatures rise, or balance degrades.

## Retrieval questions

1. What two forms of energy exchange in an ideal mass-spring oscillator, and what does damping do?
2. How do effective mass and stiffness change natural frequency?
3. Why might smoothing Parcel's body-velocity command reduce sensor error without changing the camera or microphone?

## Optional 10-minute exercise

In a spreadsheet, compute `f_n` for `m = 0.05, 0.10, 0.20 kg` and `k = 400, 800 N/m`. Mark combinations within 20% of 10 Hz or 20 Hz. Write one safe measurement that would test whether either frequency is actually excited on the assembled robot.
