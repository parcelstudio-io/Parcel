# Closed-loop locomotion and Unitree Sport

Implementation snapshot: 2026-08-29. Parcel has one **runtime body-velocity
owner**, `ControlManager`, and one **device-wide vendor writer**, the isolated
`parcel-gateway` process. Voice, navigation, owner search, follow, spatial
behavior, and manual control may propose motion; none may construct an SDK
client or bypass the manager/gateway transaction.

Targeted correction (2026-08-22): the P0 post-shaper final-stop boundary has
landed in committed code, and the speed envelope below has been rechecked. The
claims remain software/simulator claims; no physical braking or Go2 speed
commissioning was performed by this documentation recheck.

That qualification matters. Simulator-only pose and trajectory skills use a
separate backend channel after the runtime serializes ownership and confirms a
velocity stop. The physical runtime rejects those calls because no
controller-owned whole-body handoff exists yet. The current architecture does
not claim that `ControlManager` arbitrates arbitrary joint or torque writes.

```text
voice / navigation / search / follow / spatial / manual
                 |
                 v
       arbiter + source TTL
                 |
                 v
       acceleration smoothing
                 |
                 v
 final camera/LiDAR proximity + TTC gates
                 |
                 v
 jerk-limited actuator hand-off
                 |
                 v
 typed final stop disposition
   hard: exact all-axis zero + reset
   proximity: exact-zero translation, gated yaw only
   nominal ramp: opt-in, monotone, and re-gated
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
 simulator adapter   Unix gateway client
                            |
                            v
                  parcel-gateway sole writer
                  Unitree Sport Move/StopMove
```

This fixes the previous split path in which a voice request could call
`SportClient.Move` before runtime smoothing and collision checks while
follow/navigation commands went only to the simulator.

**Landed P0 correction:** the ordinary proximity/TTC decision still runs before
the final S-curve shaper, but `core/hard_stop.py::finalize_command` now executes
after every shaper and immediately before dispatch. `HARD_STOP` reasserts exact
`(0, 0, 0)` and attempts every downstream reset; `PROXIMITY_STOP` zeros
translation exactly while preserving only finite yaw already admitted by the
gate. The optional `NOMINAL_STOP` path accepts only a finite, sign-preserving,
non-increasing command relative to the prior command, and the runtime re-gates
each ramp candidate. It is off in the shipped config; a missing prior command,
malformed/non-monotone candidate, expired intent, or new veto takes the hard
path. This is a tested command-boundary property, not proof of physical stop
response. See [NAVIGATION_ALGORITHM_2026.md](NAVIGATION_ALGORITHM_2026.md).

## Where authority lives

The body-velocity path has intentionally separate policy and transport
boundaries:

| Layer | Owns | Does not own |
| --- | --- | --- |
| Behavior producers | A short-lived desired `VelocityCommand` | Priority, final collision decision, vendor I/O |
| `CommandArbiter` | One active source by priority and TTL | Acceleration, perception, physical feedback |
| `VelocitySmoother` | Bounded acceleration/deceleration | Safety authority; environmental stops are evaluated after this stage |
| Runtime proximity and TTC gates | Directional person/owner/obstacle slowdown or translation stop, plus constant-velocity dynamic-track braking, using fresh camera/LiDAR observations | Vendor state, balance, RPC delivery, or socially optimal prediction |
| `SCurveVelocityShaper` | Per-axis acceleration/jerk limits at the final SE(2) hand-off; optional calm profile | Collision authority; the current calm signal is derived from the robot's synthesized speech rather than owner affect |
| `FinalStopDecision` | Non-relaxable post-shaper dispatch class: exact hard stop, translation-zero proximity stop, or validated nominal stop | Physical braking, balance, contact, or independent hardware E-stop behavior |
| `ControlManager` | Exclusive runtime velocity owner, body limits, feedback freshness, controller faults/tilt, lease expiry, stop/E-stop lifecycle | Environmental collision perception, route planning, or direct vendor access |
| `parcel-gateway` | Device-wide SDK writer lock, boot epoch, writer identity, command sequence/TTL, stop dominance, vendor I/O and evidence | Tasks, language, navigation goals, or permission to re-arm on restart |
| Unitree Sport | Fast balance, gait, foot placement, and motor control for the requested body velocity | Semantic goals and external obstacle avoidance |

The arbiter's current priority order is navigation (30), search (35), follow
(40), spatial (50), voice (60), manual (80), and safety (100). A software
E-stop is not a priority-100 command; it is a separate persistent latch in both
the runtime arbiter and `ControlManager`.

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
Parcel ControlManager (50 Hz physical/external-manager default)
  feedback freshness, target lease, faults, stop watchdog
                         |
                         v
parcel-gateway (separate process; sole SDK writer)
  boot epoch, sequence/TTL, local limits, stop dominance
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

This is a **nested closed-loop design**, not open-loop control. One simulator
qualification matters: the built-in synchronous compatibility manager is
ticked by the approximately 10 Hz `RobotRuntime` loop, so `control_hz: 50` is
not an independent 50 Hz simulator watchdog thread. An explicitly supplied
physical/external manager uses its configured control thread.

- Unitree closes the hard real-time balance/gait loop around IMU, joint, and
  contact feedback.
- `ControlManager` closes a supervisory loop around feedback freshness, mode,
  tilt/fault state, command leases, and measured stop confirmation.
- Navigation/search/follow/spatial controllers close the task loop around
  odometry and camera/LiDAR observations.

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
| Two smoothers around the environmental gate, then a final stop disposition | Behavior commands change legibly, the hand-off bounds jerk, and shaping cannot relax a hard/proximity stop | Cascaded filters still add lag; command-space stop correctness does not measure the physical Sport response, braking distance, or balance transient |
| Feedback-confirm every physical stop | Prevents a transport acknowledgment from being mistaken for a stationary robot | Adds latency and rejects new motion if timestamps, sequence numbers, frame calibration, or feedback delivery are wrong |
| Dedicated gateway plus fixed device lock | Product/runtime imports remain independent of Unitree SDK; autonomous and commissioning writers cannot coexist | The SDK lease is process-lifetime, so replacement requires process exit and commissioning must stop the gateway first |
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

The default browser/simulator stack uses the simulator controller adapter. The
`unitree_sport` block shown beside it is retained only as input to the
supervised `parcel-unitree-control` commissioning workflow; selecting or
completing it cannot restore the retired in-process runtime writer:

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

The active body limits and shaping settings are separate from that controller
lifecycle block:

```yaml
motion:
  max_vx: 1.0
  max_vy: 0.5
  max_vyaw: 1.5
  smoothing:
    linear_accel: 0.9
    linear_decel: 1.4
    yaw_accel: 1.8
  shaping:
    enabled: true
    linear_max_accel: 1.2
    linear_max_jerk: 3.0
    yaw_max_accel: 2.4
    yaw_max_jerk: 6.0
    calm_scale: 0.6
    calm_below_arousal: 0.35
    arousal_valid_s: 20.0
```

These are maximum envelopes, not commanded speeds. The default navigation
wrapper allows up to `0.9 m/s`, while `grid_v1`'s desired cruise is
`0.85 m/s`; manual, spatial, and other producers can use different bounded
portions of the wider `1.0 m/s` body envelope. Heading/distance tapers, slew,
arbitration, safety, and shaping can all command less. The values were tuned
from simulator pacing observations and are not physically commissioned Go2
limits.

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
mode table has been verified. An empty list prevents armed commissioning from
proceeding; a reviewed record may populate it for the gateway's box-day
environment. It never enables direct runtime SDK construction.

The SDK lease is mandatory in both the vendor gateway and the armed
commissioning writer, and activation waits for a nonzero lease ID. Every
`Move` checks that the lease is still nonzero before it crosses vendor I/O.
This prevents silently running without the requested Unitree ownership
mechanism. Treat the lease as command ownership, not as a proven crash-stop
guarantee: verify loss-of-process behavior on the exact firmware and retain an
independent physical E-stop.

The official Python lease implementation starts a renewal thread but exposes no
public release/close operation. Parcel consequently treats a real SDK lease as
process-lifetime and permits only one real activation in an OS process. The
fixed `/run/parcel-gateway/unitree-writer.lock` additionally excludes a second
SDK writer across processes. Autonomous control uses the typed Unix gateway
boundary; the old registered `unitree_sport` runtime factory is retired and
always refuses. Armed commissioning is a mutually exclusive maintenance mode:
stop `parcel-gateway.service`, run the CLI as the same `parcel-gateway` UID, and
let the commissioning process exit before restarting the service.

The older `motion.backend: sport|rl` section remains a compatibility facade for
skill and voice intent selection. It no longer initializes DDS or sends
physical commands. `ControlManager` owns application-side motion delivery. On
a physical composition it reaches only `motion_gateway_commissioned` and the
gateway socket; `parcel-gateway` alone owns vendor delivery and the SDK handle.

## Forward-preferred motion and lateral velocity

Parcel's body contract is holonomic: positive `vx` is forward, positive `vy`
is left, and positive `vyaw` is counter-clockwise after commissioned sign
mapping. Unitree Sport declares lateral-velocity support, and manual control or
a future local planner may strafe.

Ordinary point-goal, grid, search, follow, and owner-orbit controllers currently
prefer turn-then-forward motion and normally emit `vy=0`. When a controller
requests a pure turn, the runtime immediately clears residual translation
instead of letting the acceleration smoother create an arc. Lateral motion is
therefore a supported capability, not the preferred way to make sustained
progress toward a place.

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
| Runtime S-curve actuator shaping | Implemented after the collision gates; the shipped config keeps the optional nominal-stop ramp off | The calm profile follows prosody measured from Parcel's own TTS audio; physical response/lag remains unverified |
| Post-shaper final stop disposition | Implemented immediately before `set_target`: hard stops are exact all-axis zero/reset, proximity stops are exact-zero translation, and opt-in nominal ramps are monotone and re-gated | Verified in the software dispatch pipeline; no physical braking-distance, stop-latency, or balance result |
| Vendor-neutral lifecycle and portability | Implemented; mock second-vendor adapter covers arming, motion, watchdog, stop, and E-stop | No second physical robot |
| Commissioned runtime -> Unix gateway client | Implemented with explicit arm, compatibility hashes, physical-origin state and restart-disarmed behavior | Desktop/fake and injected protocol evidence; no deployed Orin launcher |
| Gateway Unitree Sport DDS/RPC/state adapter | Implemented behind the sole-writer process and tested with injected SDK doubles | Not run against a physical Go2 from this workstation |
| Device-wide writer exclusion | Fixed persistent lock is required before real SDK construction by either gateway or commissioning; the old in-process runtime factory always refuses | Kernel/software evidence only; Unitree lease/crash behavior remains unmeasured |
| Frame, axis, and allowed-mode gates | Implemented and defaulted closed | Values remain uncommissioned in `configs/robot.yaml` |
| Physical camera/LiDAR runtime backend | Contract documented | Not implemented |
| Physical poses/trajectories | Rejected by runtime after a stop | No whole-body controller/handoff implemented |
| Custom low-level gait/balance controller | Interface sketch only | No `LowCmd` controller, estimator, or policy integrated |
| Independent hardware E-stop / robot-side watchdog | Required production hardware | Outside this repository today |

## Commissioning workflow — maintenance mode, not autonomous runtime

Install Unitree's official `unitree_sdk2_python` and CycloneDDS in the dedicated
gateway environment and confirm the robot NIC. Commissioning is a four-stage
evidence workflow: read-only `observe`, explicitly armed `run`, second-person
`review`, then print-only `apply`. It does not require already-commissioned
mode/frame/axis flags; it exists to measure them.

The read-only phase claims no lease and constructs no controller. Use the CLI
help and the signed box-day runbook for exact parameters:

```bash
python3 -m parcel_robot.unitree_control observe --help
python3 -m parcel_robot.unitree_control run --help
python3 -m parcel_robot.unitree_control review --help
python3 -m parcel_robot.unitree_control apply --help
```

The armed `run` phase is mutually exclusive with autonomous gateway service:

1. Stop `parcel-runtime.service` and `parcel-gateway.service`; verify neither
   process holds the fixed writer lock.
2. Run the armed command as the dedicated **`parcel-gateway` UID**, not as the
   ordinary operator or `parcel-runtime`. The persistent `0600` lock inode is
   owned by that UID and permissions must not be widened.
3. Keep the robot on its support rig in a fenced area, with a second person at
   an independent physical E-stop, and supply every CLI acknowledgement.
4. Use only modes actually captured by `observe`, one named axis at a time.
   Linear speed is restricted to 0.02–0.05 m/s; yaw is derived from the same
   tangential-speed band; a step lasts at most one configured stop budget
   (normally 1.0 s).
5. Let the commissioning process exit after it records and confirms stop. The
   SDK lease and writer lock are process-lifetime after activation; do not
   restart the gateway until that process has exited.
6. A different person reviews the record. `apply` only prints configuration
   authorized by an accepted, complete record; a human transfers the reviewed
   values into the gateway's box-day environment.

Writer contention refuses before configuration, DDS channel, or SDK controller
construction. This tool is for supervised locomotion measurement only. It does
not provide camera/LiDAR navigation, owner following, an independent hardware
E-stop, or evidence that autonomous physical motion is ready.

## Stop and failure behavior

Motion is rejected or stopped when:

- Robot feedback is absent or stale.
- The body-velocity lease expires.
- A target is non-finite or outside physical limits.
- Unitree reports a nonzero controller error.
- Roll or pitch exceeds the configured limit.
- `Move` or `StopMove` raises or returns an error.
- The operator stops, closes, or emergency-stops the runtime.

Environmental stops happen above this list: stale perception cancels active
autonomy, directional proximity can zero translation, and the TTC gate can
only scale a command down. The post-gate S-curve uses an emergency transition
for zero/safety/E-stop commands, so jerk limiting never delays a stop. This is
still software behavior on a non-real-time host and is not a certified crash
stop.

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
Physical production must not do that with an SDK-backed controller. The former
`build_unitree_sport_control_manager` entry is deliberately unregistered and
always raises; it is a migration refusal, not a recipe.

The target five-service composition is:

```text
parcel-runtime (task/navigation + commissioned ControlManager)
        |
        | MotionGatewayClientV1 over SOCK_SEQPACKET
        v
parcel-gateway (sole vendor writer + fixed writer lock)
        |
        v
Unitree SDK2 / DDS / Sport

parcel-safety  independent STOP and observation-health authority
parcel-lio     localization evidence
parcel-audio   capture, AEC/VAD, local STOP and playback
```

The registered `motion_gateway_commissioned` factory builds the runtime-side
controller/state pair. It requires an explicit commissioning-record ID, exact
configuration/capability/calibration/firmware compatibility hashes, and a
separately injected physical runtime composition. It connects only to the Unix
socket; it owns no vendor import, DDS credential, or SDK handle. The gateway
alone constructs the Unitree port after taking the device-wide lock.

There is intentionally no copy-paste physical runtime launch here. The Orin
service files are still skeletons: `parcel-runtime`, `parcel-safety`,
`parcel-lio`, and `parcel-audio` executables and the synchronized physical
observation composition do not yet exist. A valid contract factory is not a
commissioned deployment.

Physical pose and joint-trajectory calls are rejected by this runtime until
they are implemented as controller-owned whole-body actions with a confirmed
locomotion-to-pose handoff. This prevents another backend from writing
actuators beside Sport control.

The physical camera/LiDAR backend is deliberately separate. Unitree
`SportModeState` supplies internal body feedback; it does not replace owner
tracking, obstacle perception, localization, or the navigation world model.

## Remaining production work

The gateway and commissioned client are a functional, fail-closed software
boundary around Unitree Sport, tested with fake and injected SDK bindings. They
have not run against a physical robot or on the target Orin. Before any
motion-enabled deployment:

- implement and package the missing runtime, LIO, and audio service executables
  while preserving the five-service ownership table; install and qualify the
  source-level gateway and stop-only `parcel-safety` entry points on the Orin;
- connect reviewed local/remote stop inputs to `parcel-safety`, and provide a
  physical E-stop that does not depend on Parcel, Python, DDS, the network, the
  sole-writer gateway, or the Orin;
- bind commissioning evidence to the observed robot/firmware identity or
  authenticate the DDS peer, rather than trusting local launch hashes alone;
- assemble synchronized physical camera/LiDAR/body/localization evidence with
  calibrated frames, clocks, health, covariance, and missing/stale behavior;
- verify firmware-specific mode, lease, state, stop-settling, low-SOC, fault,
  restart, and link-loss behavior;
- run motors-disabled HIL, then stationary and tethered low-speed qualification
  with measured control timing, stop latency/distance, payload, power, thermal,
  and sensor load; and
- replace or independently backstop any Python/SDK operation whose measured
  target deadline cannot be bounded.

Keeping Python above this boundary is a deliberate productionization choice:
language, semantic planning, UI, and orchestration benefit from Python's model
ecosystem and do not run a hard real-time motor loop. The isolated gateway keeps
those workloads out of the vendor process, but it is not an independent
hardware crash-stop layer. A future custom low-level balance controller is a
separate project and must move estimator/joint/torque work into a native
real-time process before Sport mode is disabled.

## Official references

- [Unitree SDK2 Python](https://github.com/unitreerobotics/unitree_sdk2_python)
- [Official Go2 SportClient example](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/go2/high_level/go2_sport_client.py)
- [Official SportClient implementation](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/go2/sport/sport_client.py)
- [Official RPC lease implementation](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/rpc/lease_client.py)
- [Unitree ROS 2 SportModeState message](https://github.com/unitreerobotics/unitree_ros2/blob/master/cyclonedds_ws/src/unitree/unitree_go/msg/SportModeState.msg)
- [Unitree MuJoCo and sim-to-real setup](https://github.com/unitreerobotics/unitree_mujoco)
