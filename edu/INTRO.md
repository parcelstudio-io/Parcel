# Introduction to Robotics and the Parcel Stack

This chapter explains how robots work for a reader who is experienced in
software engineering but new to robotics and hardware. It uses the Parcel
robot-dog stack as the concrete example.

## The core mental model

A conventional service often looks like this:

```text
request -> computation -> response
```

A robot continuously closes a feedback loop:

```text
sense -> estimate -> decide -> act
  ^                         |
  +------ observe result ---+
```

The robot reads sensors, estimates the state of itself and the world, chooses
an action, applies physical forces, and then observes what actually happened.
That last step matters: motors slip, surfaces have different friction, sensors
are noisy, batteries weaken, and people move unexpectedly.

In software terms, a robot is a distributed real-time system connected to a
physical body. Its software must deal with deadlines, noisy inputs, partial
failure, and commands that can have irreversible physical consequences.

## The physical layers of a robot dog

### Mechanical body

The frame, legs, joints, feet, bearings, and gearboxes define what motion is
physically possible. A typical quadruped has three actuated joints per leg:

- Hip abduction/adduction moves the leg sideways.
- Hip flexion/extension moves it forward and backward.
- Knee flexion/extension shortens and extends the leg.

A four-legged robot with this arrangement has 12 degrees of freedom. Every
joint has angle, speed, torque, and temperature limits. The software cannot
request arbitrary poses without respecting these constraints.

### Actuators

Modern robot dogs commonly use brushless DC motors with gear reduction. A
motor assembly normally includes a position encoder, current sensing,
temperature monitoring, and a motor controller.

Depending on the interface, higher software layers can request:

- Position: move a joint to a particular angle.
- Velocity: rotate it at a particular rate.
- Torque: apply a particular rotational force.

The motor controller handles fast electrical control. Higher layers should not
attempt to reproduce those electronics-level responsibilities.

### Internal sensors: proprioception

Proprioception tells the dog about its own body:

- Joint encoders report joint angles and often velocities.
- An IMU reports orientation, angular velocity, and acceleration.
- Motor current provides information related to applied effort.
- Foot-force or contact sensors may report ground contact.
- Battery and thermal sensors report hardware health.

Parcel's product-level world perception can be limited to camera and LiDAR,
but a physical quadruped still needs encoders and an IMU to balance and control
its legs. A useful distinction is:

```text
encoders and IMU = private body/runtime state
camera and LiDAR = application-visible environment perception
```

### External sensors

Parcel primarily uses:

- Camera data for appearance, people, objects, and owner recognition.
- LiDAR data for distance, geometry, free space, and obstacle detection.
- Microphone audio for spoken interaction.
- An optional future map provider for prior geographic information.

Camera and LiDAR are complementary:

```text
camera: "That object looks like the owner."
LiDAR:  "That object is approximately 2.1 meters away."
```

### Compute, communications, and power

A robot usually contains multiple computers rather than one monolithic
process. Motor microcontrollers, the vendor locomotion computer, a perception
computer, and an external workstation may all participate.

They communicate over interfaces such as CAN, Ethernet, DDS/ROS 2, and
vendor-specific protocols. The battery constrains actuator power, payload,
compute, cooling, and operating time. Battery voltage, motor temperature, and
communication loss are therefore software-visible safety concerns.

## The software hierarchy

Robotic software converts progressively more abstract intentions into physical
commands:

```text
User intent
"Walk in a small circle around me"
          |
          v
Behavior planning
Circle owner, radius 1.5 m, clockwise
          |
          v
Navigation
Generate a path around the tracked owner
          |
          v
Local motion control
Desired forward, lateral, and yaw velocity
          |
          v
Locomotion controller
Choose foot placement and body motion
          |
          v
Joint controller
Desired position, velocity, or torque per joint
          |
          v
Motor electronics
Apply electrical current to the motors
```

Each layer should expose a bounded, typed interface. The language model should
never control joint positions or torques directly.

## What a layer's timescale means

A layer's timescale describes how quickly it must observe changes, make a
decision, and produce its next output before the physical world changes too
much for that output to remain useful.

Frequency is commonly expressed in hertz:

```text
frequency = updates per second
period = 1 / frequency

1,000 Hz -> one update every 1 ms
200 Hz   -> one update every 5 ms
20 Hz    -> one update every 50 ms
10 Hz    -> one update every 100 ms
1 Hz     -> one update every second
```

Illustrative layer rates are:

| Layer | Concern | Example rate | Time per update |
| --- | --- | ---: | ---: |
| Joint/motor control | Produce physical force | 1,000 Hz | 1 ms |
| Locomotion | Balance and foot placement | 200 Hz | 5 ms |
| Local navigation | Nearby obstacles and direction | 20 Hz | 50 ms |
| Behavior planning | Follow, sit, or gesture | 5 Hz | 200 ms |
| Conversation | Understand and answer the user | Event-driven | Variable |

These values are illustrative; actual requirements depend on the robot and
vendor controller.

If the dog begins tipping, different layers react at different times:

```text
0 ms       IMU detects body rotation
1-5 ms     motor and locomotion controllers adjust the legs
50 ms      navigation receives the changed body state
200 ms     behavior planning may adjust the active task
1 s or more conversation can explain what happened
```

The language model cannot be part of the balance loop. A slow layer gives a
goal to a faster layer, and the fast layer reuses that goal while closing its
own feedback loop:

```text
Conversation: "Follow the owner"
       | occasionally
       v
Navigation: desired body direction and speed
       | about every 50 ms
       v
Locomotion: desired body and foot movement
       | about every 5 ms
       v
Joint control: desired motor effort
       | about every 1 ms
       v
Physical robot
```

Higher frequency is not automatically better. It consumes compute, and most
semantic decisions do not change every millisecond. Each layer should run only
as fast as the phenomenon it controls requires.

### Deadlines and jitter

A 200 Hz loop has about 5 ms to complete an update. That is its deadline.
Consider the following execution times:

```text
1 ms, 1 ms, 2 ms, 1 ms, 18 ms
```

The average is small, but the 18 ms update misses several deadlines. One such
pause can matter to a balancing robot. Production robotics therefore measures:

- Average, p95, p99, and maximum latency.
- Jitter, or variation in update timing.
- Missed deadlines.
- The age of sensor data used to compute a command.
- The time from command creation to actuator acknowledgement.
- Watchdog stop latency after a component fails.

Real-time means sufficiently predictable to meet a required deadline. It does
not merely mean fast on average.

## Open-loop and closed-loop control

An open-loop controller plays a command and assumes the expected result:

```text
play predefined leg motion -> assume the body moved correctly
```

A closed-loop controller observes the result and corrects the next command:

```text
command motion
    -> measure joint, IMU, and contact state
    -> compute error
    -> adjust the next command
```

The software analogy is issuing a write versus continuously reconciling actual
state toward desired state.

A minimal proportional controller is:

```text
error = desired_position - measured_position
command = Kp * error
```

A PID controller also considers accumulated error and how quickly error is
changing. Quadruped locomotion generally uses more advanced techniques such as
rigid-body models, contact constraints, model-predictive control, or learned
locomotion policies.

Parcel's current scripted gait and joint visualization are open-loop simulator
previews. Initial physical deployments should use Unitree's onboard locomotion
controller rather than attempting to implement balancing from scratch.

## State estimation and coordinate frames

Raw sensor readings are noisy, delayed, and sometimes contradictory. State
estimation combines them into the robot's best current belief:

```text
joint encoders + IMU -> body pose, velocity, and leg configuration
camera + LiDAR       -> owner position, obstacles, and local geometry
previous belief + observations -> updated world state
```

The system should distinguish:

- Measurement: LiDAR returned a point at a coordinate.
- Estimated state: an object is probably 1.8 meters ahead and moving left.
- Semantic belief: the object is probably the owner.

It must also track coordinate frames:

- `base_link`: relative to the dog's body.
- `camera`: relative to the camera sensor.
- `lidar`: relative to the LiDAR sensor.
- `odom`: a locally stable motion frame.
- `map`: a shared world frame.
- `owner`: a dynamic frame centered on the tracked owner.

A request such as "walk five steps away from me" must eventually become a
metric trajectory in a well-defined coordinate frame.

## Navigation is not locomotion

Navigation decides how the body should move through the environment:

```text
current pose + goal + obstacles -> collision-free body path
```

Locomotion decides how the legs produce that body movement:

```text
desired body velocity + contact state -> foot and joint commands
```

Parcel can prefer forward-facing motion while retaining lateral movement for
local avoidance:

```text
if heading error is large:
    rotate toward the goal
else:
    move primarily forward
```

The navigation layer produces forward, lateral, and yaw velocity intentions.
The Unitree locomotion controller converts them into a stable gait.

## From a voice command to physical motion

For the command "Walk in a small circle around me, then sit," Parcel should
use the following pipeline:

```text
audio
  -> speech-to-text
  -> language and intent model
  -> structured task
  -> safety and feasibility validation
  -> behavior scheduler
  -> navigation trajectory
  -> native motion controller
```

The reasoning model should emit structured meaning rather than motor commands:

```json
{
  "actions": [
    {
      "type": "circle_entity",
      "entity": "owner",
      "radius_m": 1.5,
      "direction": "clockwise",
      "laps": 1
    },
    {
      "type": "pose",
      "name": "sit"
    }
  ]
}
```

Deterministic software then locates the owner, checks free space, generates a
trajectory, replans as the owner moves, stops if tracking is lost, and executes
the sit pose after navigation completes.

The language model supplies semantic interpretation and common sense.
Navigation and control supply repeatability, validation, and safety.

## Priorities, interruption, and safety

The dog can receive conflicting requests. Parcel therefore needs arbitration
similar to an operating-system scheduler:

```text
emergency stop
  > imminent collision avoidance
  > stability and fall recovery
  > explicit safety command
  > active navigation task
  > requested gesture
  > emotion-driven behavior
  > idle personality behavior
```

Actions should declare priority, expiration, cancellation behavior, and
whether they can be interrupted. A playful gesture can be queued while the dog
crosses an obstacle instead of interrupting the important task.

## How Parcel maps onto these concepts

The current high-level flow is:

```text
voice, text, or UI
       -> reasoning and intent interpretation
       -> activity coordinator and command arbiter
       -> follow, spatial, and navigation behavior
       -> collision gate and velocity smoothing
       -> simulator backend
       -> MuJoCo robot
       -> simulated observations returned to the runtime
```

Parcel's Python runtime currently operates at approximately 10 Hz, or once
every 100 ms. That is suitable for behavior coordination, semantic tasks,
follow updates, and high-level movement intentions. It is not suitable for
joint control, balance, foot-contact response, or motor torque control.

The backend interface is the seam between application intelligence and the
physical platform. The simulator backend can eventually be replaced by a ROS 2
and Unitree hardware backend without rewriting conversation, personality,
task-planning, and UI code.

The intended production split is:

```text
Python Parcel brain
  conversation, personality, planning, UI, and semantic perception
                         |
                         v
typed intent: sequence, timestamp, TTL, frame, bounded parameters
                         |
                         v
C++ control and safety process
  validation, arbitration, watchdog, collision bounds, Unitree SDK
                         |
                         v
Unitree locomotion controller
                         |
                         v
motors, encoders, and IMU
```

If Python pauses or crashes, the lower controller must continue balancing and
stop safely within a defined deadline. It must never wait for the language
model while the body is falling.

## Why simulation matters

Simulation provides controllable, repeatable experiments. It lets us:

- Replay the same pedestrian encounter.
- Freeze or delay a sensor.
- Drop commands or network messages.
- Change friction and obstacle layouts.
- Move the owner unexpectedly.
- Measure collisions, latency, and recovery.
- Run dangerous cases without damaging hardware.

Simulation also has a reality gap. Contact, friction, structural flexibility,
sensor noise, heat, power, and networks never behave exactly like their models.
A responsible development sequence is:

```text
unit tests
  -> deterministic simulation
  -> randomized simulation and fault injection
  -> hardware-in-the-loop
  -> robot raised on a support stand
  -> fenced low-speed testing
  -> supervised real-world testing
```

## The central design principle

Keep intelligence and safety separate.

The intelligent layer may be probabilistic, creative, delayed, or temporarily
unavailable. It can infer that the user wants the dog to circle them playfully.

The control layer must be deterministic and skeptical. It must verify that the
request is fresh, authorized, feasible, within physical limits, and safe in the
current environment.

Treat the language model as an untrusted planner whose output crosses a
strongly typed and validated boundary before it can affect the physical world.
That separation allows Parcel to retain productive Python development while
evolving into a robot that can operate safely around people.
