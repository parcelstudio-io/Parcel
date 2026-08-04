# Closed-loop locomotion and Unitree Sport

Implementation snapshot: 2026-08-04. Parcel has one **body-velocity actuator
owner**: `ControlManager`. Voice, navigation, follow, spatial behavior, and
manual control may propose motion, but only the manager's selected
`LocomotionController` can deliver a body-velocity command.

That qualification matters. Simulator-only pose and trajectory skills use a
separate backend channel after the runtime serializes ownership and confirms a
velocity stop. The physical runtime rejects those calls because no
controller-owned whole-body handoff exists yet. The current architecture does
not claim that `ControlManager` arbitrates arbitrary joint or torque writes.

```text
voice / navigation / follow / manual
                 |
                 v
       arbiter + source TTL
                 |
                 v
     smoothing + final camera/LiDAR gate
                 |
                 v
 leased body-velocity target (base_link)
                 |
                 v
          ControlManager
      state and intent watchdogs
       limits, lifecycle, E-stop
                 |
        LocomotionController
            /          \
           v            v
  Unitree Sport      future custom
  Move/StopMove      low-level loop
```

This fixes the previous split path in which a voice request could call
`SportClient.Move` before runtime smoothing and collision checks while
follow/navigation commands went only to the simulator.

## Where authority lives

The body-velocity path has intentionally separate policy and transport
boundaries:

| Layer | Owns | Does not own |
| --- | --- | --- |
| Behavior producers | A short-lived desired `VelocityCommand` | Priority, final collision decision, vendor I/O |
| `CommandArbiter` | One active source by priority and TTL | Acceleration, perception, physical feedback |
| `VelocitySmoother` | Bounded acceleration/deceleration | Safety authority; a safety stop bypasses gradual braking |
| Runtime reactive gate | Directional person/owner/obstacle slowdown or translation stop using fresh camera/LiDAR observations | Vendor state, balance, RPC delivery |
| `ControlManager` | Exclusive velocity writer, body limits, feedback freshness, controller faults/tilt, lease expiry, stop/E-stop lifecycle | Environmental collision perception or route planning |
| Unitree Sport | Fast balance, gait, foot placement, and motor control for the requested body velocity | Semantic goals and external obstacle avoidance |

The arbiter's current priority order is navigation (30), follow (40), spatial
(50), voice (60), manual (80), and safety (100). A software E-stop is not a
priority-100 command; it is a separate persistent latch in both the runtime
arbiter and `ControlManager`.

`ControlManager` is safe to use as a vendor-neutral locomotion boundary, but it
is not by itself an autonomous-navigation safety system. The standalone
commissioning CLI deliberately calls it without camera/LiDAR navigation and
therefore uses much lower speed/duration limits and an operator-held physical
E-stop. A production caller that bypasses `RobotRuntime` also bypasses the
environmental reactive gate.

## Nested closed loops

With Unitree Sport, Parcel does not implement balance:

```text
Parcel navigation loop (~10 Hz)
  owner/goal feedback -> desired body velocity
                         |
                         v
Parcel ControlManager (50 Hz default)
  feedback freshness, target lease, faults, stop watchdog
                         |
                         v
Unitree onboard Sport controller
  IMU/joint/contact feedback -> balance, gait, foot placement
                         |
                         v
motor controllers
  encoder/current feedback -> motor effort
```

`SportClient.Move(vx, vy, vyaw)` supplies a body-velocity target to Unitree's
onboard closed-loop locomotion. A successful Python return indicates transport
delivery, not proof of physical movement. Parcel therefore subscribes to
`rt/sportmodestate` and supervises locally timestamped feedback.

This is a **nested closed-loop design**, not open-loop control:

- Unitree closes the hard real-time balance/gait loop around IMU, joint, and
  contact feedback.
- `ControlManager` closes a supervisory loop around feedback freshness, mode,
  tilt/fault state, command leases, and measured stop confirmation.
- Navigation/follow/spatial controllers close the task loop around odometry and
  camera/LiDAR observations.

The outer loops do not make `Move` a precision trajectory servo. Parcel does
not currently compare commanded and measured velocity to regulate away a
tracking error, estimate slip, or prove that a requested displacement occurred.
Task controllers infer progress from fresh pose/perception, and the manager
uses measured velocity primarily for readiness and stopping. Exact path
tracking therefore still depends on correctly framed odometry and the opaque
onboard Sport response.

The public message definition does not document whether planar velocity is in
odometry or body coordinates. Parcel therefore makes that choice explicit with
`state_velocity_frame`, rotates only when it is configured as `odom`, and
refuses to construct the physical controller until
`state_frame_commissioned: true` is set after a real low-speed test.

## Why use Sport first

| Design choice | Advantage | Limitation / consequence |
| --- | --- | --- |
| Reuse Unitree Sport balance/gait | A proven onboard high-rate controller absorbs the hardest contact-control problem; Parcel can iterate on companion behavior safely at body-velocity level | Opaque firmware behavior, modes, tracking quality, foothold choices, and stop semantics remain vendor-specific |
| Supervise Sport from Python | Python is appropriate for the current 10 Hz behavior loop and 50 Hz watchdog because hard real-time balance stays onboard | Python, DDS, and the host OS are not an independent real-time crash-stop layer; an onboard/native watchdog and physical E-stop remain required |
| One leased `base_link` velocity contract | Simulator, Unitree, and a future vendor/custom controller share the same upper stack | A lowest-common-denominator SE(2) command cannot expose terrain-aware footsteps or whole-body maneuvers |
| Feedback-confirm every physical stop | Prevents a transport acknowledgment from being mistaken for a stationary robot | Adds latency and rejects new motion if timestamps, sequence numbers, frame calibration, or feedback delivery are wrong |
| Lazy vendor imports and registered factories | Normal simulation/test imports remain independent of Unitree SDK and a second vendor needs no generic-code edit | Process-global DDS and Unitree's non-releasable Python lease still require a dedicated physical driver process |
| Fail-closed commissioning flags | Wrong mode/frame/axis assumptions cannot silently move hardware | Physical construction is intentionally impossible with the repository defaults until a human completes commissioning |

## Replaceable controller contract

The controller-neutral types live under `parcel_robot.control`:

- `TimedVelocitySetpoint` carries command, source, sequence, frame, issue time,
  and deadline.
- `RobotMotionState` carries locally timestamped pose, attitude, body-frame
  velocity, controller mode/error, and optional joint/contact state.
- `LocomotionController` owns activation, update, stop, emergency stop, and
  shutdown behavior.
- `RobotStateSource` supplies the latest physical feedback independently of
  external camera/LiDAR perception.
- `ControlManager` is the exclusive writer and lifecycle/watchdog owner.

Controller implementations have a deliberately strict concurrency contract:
`activate()` is passive and bounded, every vendor I/O call is bounded and
internally serialized, and `latest()` is nonblocking. This lets an E-stop latch
without waiting for passive activation and lets shutdown wait for an in-flight
update before sending its final compensating stop. `io_quiesce_timeout_s` is the
maximum time shutdown waits for such a call; it must exceed the controller's
largest activation/RPC bound.

A future custom locomotion implementation receives the same body-velocity
setpoint but privately runs its own faster estimator and IMU/joint controller:

```python
class CustomLocomotionController:
    name = "custom"
    capabilities = ControllerCapabilities(
        high_level_balance=False,
        low_level_joint_control=True,
        requires_stop_confirmation=True,
    )

    def activate(self): ...

    def update(self, target, state, *, now):
        # Run or feed a private high-rate native controller. Do not expose
        # joint/torque commands to the LLM or navigation layers.
        ...

    def stop(self, reason): ...
    def emergency_stop(self): ...
    def clear_emergency_stop(self): ...
    def close(self): ...
```

When Unitree's built-in motion service is disabled for a custom low-level
controller, replace `UnitreeSportStateSource` with a `LowState`-based state
source and estimator. Never publish Unitree `LowCmd` while Sport mode is active.

## Configuration

The default browser/simulator stack uses the simulator controller adapter:

```yaml
control:
  controller: simulator
  control_hz: 50
  command_timeout_s: 0.35
  state_timeout_s: 0.25
  startup_timeout_s: 2.0
  stop_timeout_s: 1.0
  stop_retry_s: 0.2
  io_quiesce_timeout_s: 2.5
  stop_settled_samples: 2
  settled_linear_speed_mps: 0.08
  settled_yaw_speed_rad_s: 0.12
  max_tilt_rad: 0.75
  command_refresh_s: 0.2
  unitree_sport:
    interface: enp3s0
    domain_id: 0
    state_topic: rt/sportmodestate
    rpc_timeout_s: 0.2
    command_refresh_s: 0.1
    enable_lease: true
    lease_acquire_timeout_s: 2.0
    axes_commissioned: false
    state_velocity_frame: odom
    state_frame_commissioned: false
    lateral_sign: 1
    yaw_sign: 1
    allowed_modes: []
```

Important network distinction:

| Target | DDS domain | Interface |
| --- | ---: | --- |
| Official Unitree MuJoCo | `1` | `lo` |
| Physical Go2 | `0` | dedicated robot Ethernet NIC |

Physical settings must be explicit. Do not silently reuse the simulator's
domain and loopback interface.

The public Unitree examples establish positive `vx` as forward. Verify the
lateral and yaw signs at very low speed with the robot supported and a human
holding the physical E-stop. `lateral_sign` and `yaw_sign` map a commissioned
robot/firmware convention to Parcel's `base_link` convention. Set
`axes_commissioned: true` only after all three axes have been checked.

`allowed_modes` is intentionally empty until the exact robot firmware's Sport
mode table has been verified. An empty list prevents the physical manager from
being built; when populated, every other mode fails before `Move` is sent.

The SDK lease is mandatory in the physical builder and activation waits for a
nonzero lease ID. Every `Move` checks that the lease is still nonzero before it
crosses the I/O lock. This prevents silently running without the requested
Unitree ownership mechanism. Treat the lease as command ownership, not as a
proven crash-stop guarantee: verify loss-of-process behavior on the exact
firmware and retain an independent physical E-stop.

The official Python lease implementation starts a renewal thread but exposes no
public release/close operation. Parcel consequently treats a real SDK lease as
process-lifetime and permits only one real activation in an OS process. Run the
physical driver in a dedicated process and terminate that process when replacing
Sport with a custom controller. The commissioning CLI already has that process
lifetime; a production runtime still needs a typed IPC/ROS 2 boundary to a
dedicated driver process.

The older `motion.backend: sport|rl` section remains a compatibility facade for
skill and voice intent selection. It no longer initializes DDS or sends
physical commands. Hardware delivery belongs only to `ControlManager`.

## Forward-preferred motion and lateral velocity

Parcel's body contract is holonomic: positive `vx` is forward, positive `vy`
is left, and positive `vyaw` is counter-clockwise after commissioned sign
mapping. Unitree Sport declares lateral-velocity support, and manual control or
a future local planner may strafe.

Ordinary point-goal, grid, follow, and owner-orbit controllers currently prefer
turn-then-forward motion and normally emit `vy=0`. When a controller requests a
pure turn, the runtime immediately clears residual translation instead of
letting the acceleration smoother create an arc. Lateral motion is therefore a
supported capability, not the preferred way to make sustained progress toward
a place.

This choice makes the dog's body orientation legible, avoids the simulator's
diagonal-slide appearance, and permits a future non-strafing controller to
reuse most of the stack. It also gives up some holonomic efficiency and can be
slower around moving people. Capability enforcement is at the dispatch
boundary: a controller that declares `lateral_velocity=False` rejects nonzero
`vy` rather than silently discarding it. Every lateral command still passes
the same acceleration, directional collision, TTL, and physical-limit checks
as forward motion.

## Implemented versus commissioned

| Capability | Repository status | Evidence boundary |
| --- | --- | --- |
| Simulator body-velocity path through `ControlManager` | Implemented and used by `RobotRuntime` | Unit/integration tests and MuJoCo behavior only |
| Vendor-neutral lifecycle and portability | Implemented; mock second-vendor adapter covers arming, motion, watchdog, stop, and E-stop | No second physical robot |
| Unitree Sport DDS/RPC/state adapter | Implemented and tested with injected SDK doubles | Not run against a physical Go2 from this workstation |
| Frame, axis, and allowed-mode gates | Implemented and defaulted closed | Values remain uncommissioned in `configs/robot.yaml` |
| Physical camera/LiDAR runtime backend | Contract documented | Not implemented |
| Physical poses/trajectories | Rejected by runtime after a stop | No whole-body controller/handoff implemented |
| Custom low-level gait/balance controller | Interface sketch only | No `LowCmd` controller, estimator, or policy integrated |
| Independent hardware E-stop / robot-side watchdog | Required production hardware | Outside this repository today |

## Safe commissioning command

Install Unitree's official `unitree_sdk2_python` and CycloneDDS in a supported
environment. Confirm the dedicated Ethernet interface in `configs/robot.yaml`.

Before invoking the tool, populate `allowed_modes` from the mode table verified
for the connected robot and firmware. Commission the velocity frame and axis
signs, then set `state_frame_commissioned` and `axes_commissioned` to `true`.
The CLI refuses to initialize or move hardware without those gates and an
explicit `--arm` acknowledgement, allows only one axis at a time, caps
linear/yaw speed at `0.10 m/s` and `0.25 rad/s`, limits each run to two seconds,
waits for fresh Sport feedback, refreshes a short command lease, and always
calls `StopMove` during shutdown:

```bash
.parcel/bin/python -m parcel_robot.unitree_control \
  --config configs/robot.yaml \
  --vx 0.05 \
  --duration 1.0 \
  --arm
```

Before running it:

1. Place the robot on a support stand or in a fenced commissioning area.
2. Keep a trained operator at the physical E-stop.
3. Ensure the Unitree app/remote and Parcel are not competing for motion.
4. Begin with a very small forward command.
5. Separately commission lateral and yaw signs.

This tool is for the locomotion boundary only. It does not provide camera/LiDAR
navigation, owner following, or an independent hardware E-stop.

## Stop and failure behavior

Motion is rejected or stopped when:

- Robot feedback is absent or stale.
- The body-velocity lease expires.
- A target is non-finite or outside physical limits.
- Unitree reports a nonzero controller error.
- Roll or pitch exceeds the configured limit.
- `Move` or `StopMove` raises or returns an error.
- The operator stops, closes, or emergency-stops the runtime.

Ordinary stops use Unitree `StopMove`. Parcel does not automatically use
`Damp`, `StandDown`, or another posture transition. Those operations have
different physical meanings and must be separately commissioned.

Physical stopping is accepted only from the configured number of distinct
settled samples whose host receipt times and sequence numbers are newer than the
final successful `StopMove` return. Until then, `StopMove` is retried at a
bounded interval. Closing irreversibly rejects new targets, waits for activation,
updates, E-stop, and clear calls to quiesce, and keeps feedback alive until stop
confirmation arrives. It raises after the stop deadline but still releases
resources if physical confirmation never arrives. If a plugin call violates its
I/O bound, close instead leaves the controller in the non-commandable `CLOSING`
state and asks the caller to retry teardown after that call returns; it never
closes a plugin underneath its own I/O.

Simulator adapters may explicitly declare synchronous stop semantics and skip
the physical-feedback handshake. Their vendor access is still serialized, and
the first actuator interaction after an offline startup sends `stop` before a
new velocity so a reconnected simulator cannot inherit a persistent old target.

A controller-thread exception is contained, latched as a fault, and also enters
the stop retry path. The E-stop request is dispatched independently of an
in-flight ordinary update; if that update returns afterward, the manager sends
a compensating stop so the stale `Move` cannot be the final command. A pre-start
E-stop blocks activation until the operator clears it. If an E-stop arrives
during passive activation, it latches immediately and is delivered as soon as
activation returns. A newer E-stop also supersedes an in-flight clear, and close
can never be overwritten back to `IDLE` by a late clear completion.

For a physical driver, the software E-stop clears only after fresh post-stop
feedback confirms settling. It is not a substitute for a hardware E-stop
independent of Parcel, Python, DDS, the network, and the onboard computer.

## Integrating with the full runtime

The simulator runtime constructs a `BackendVelocityController` automatically.
A physical runtime supplies the Unitree manager explicitly alongside a
camera/LiDAR perception backend:

```python
from parcel_robot.config import ConfigStore
from parcel_robot.control import build_unitree_sport_control_manager
from parcel_robot.runtime import RobotRuntime

store = ConfigStore("configs/robot.yaml")
manager = build_unitree_sport_control_manager(
    store.section("control"),
    store.safety_limits(),
)

runtime = RobotRuntime(
    "configs/robot.yaml",
    physical_camera_lidar_backend,
    control_manager=manager,
)
```

This direct integration requires the full runtime process to terminate when the
Sport driver is closed, because the SDK lease cannot be released in-process.
For production, preserve the same `ControlManager`/controller contract across a
separate driver-process IPC boundary.

Physical pose and joint-trajectory calls are rejected by this runtime until
they are implemented as controller-owned whole-body actions with a confirmed
locomotion-to-pose handoff. This prevents another backend from writing
actuators beside Sport control.

The physical camera/LiDAR backend is deliberately separate. Unitree
`SportModeState` supplies internal body feedback; it does not replace owner
tracking, obstacle perception, localization, or the navigation world model.

## Remaining production work

This implementation is a functional Python supervisory loop around Unitree's
closed-loop Sport controller, but it has not been run against a physical robot
from this workstation. Before unsupervised operation, add:

- A native C++ (or equivalently bounded native) control/safety driver process
  with the same typed contract; the conversation, planning, and product logic
  do not need a whole-codebase rewrite.
- A process-independent command watchdog on the robot side.
- Hardware E-stop and safe arming circuitry/procedures.
- Verified firmware-specific mode and stop-settling checks.
- Physical camera/LiDAR perception and localization.
- Fault-injection, hardware-in-the-loop, load, and soak testing.
- Typed ROS 2 messages/actions instead of JSON `std_msgs/String` topics.

Keeping Python above this boundary is a deliberate productionization choice:
language, semantic planning, UI, and orchestration benefit from Python's model
ecosystem and do not run a hard real-time motor loop. Moving the bounded
hardware writer/watchdog first reduces crash-stop and scheduling risk without
duplicating the well-tested semantic stack. A future custom low-level balance
controller is a separate project and must move estimator/joint/torque work into
that native real-time process before Sport mode is disabled.

## Official references

- [Unitree SDK2 Python](https://github.com/unitreerobotics/unitree_sdk2_python)
- [Official Go2 SportClient example](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/go2/high_level/go2_sport_client.py)
- [Official SportClient implementation](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/go2/sport/sport_client.py)
- [Official RPC lease implementation](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/rpc/lease_client.py)
- [Unitree ROS 2 SportModeState message](https://github.com/unitreerobotics/unitree_ros2/blob/master/cyclonedds_ws/src/unitree/unitree_go/msg/SportModeState.msg)
- [Unitree MuJoCo and sim-to-real setup](https://github.com/unitreerobotics/unitree_mujoco)
