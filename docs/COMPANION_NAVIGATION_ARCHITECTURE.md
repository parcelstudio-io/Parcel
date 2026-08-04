# Companion navigation and instruction-following architecture

Current implementation snapshot (2026-08-04), aligned with
[REDESIGN_2026_ARCHITECTURE.md](REDESIGN_2026_ARCHITECTURE.md). This document
describes the default implemented code path, not a target architecture or a
claim of physical deployment.

## Decision

Parcel is not one language model that continuously predicts body velocity. It
is a hierarchical, closed-loop system with a probabilistic semantic layer and
deterministic motion authority:

```text
final audio/text + camera/LiDAR tracks + task/control state
  -> deterministic IntentFrame router
       |-> conversation
       |-> bounded direct skill
       |-> asynchronous semantic PlanIR proposal
       `-> clarify / abstain
  -> system compiler + PlanValidator + TaskExecutive
  -> deterministic behavior controller
       |-> DirectiveNavigator (place / semantic goal)
       |-> FollowOwnerController
       `-> SpatialBehaviorController (bounded relative move / owner orbit)
  -> CommandArbiter (one time-limited velocity intent)
  -> acceleration smoothing
  -> final runtime reactive-safety gate
  -> ControlManager (limits, feedback, lifecycle, watchdog, E-stop)
  -> simulator adapter or Unitree Sport Move/StopMove
  -> fresh robot/perception feedback closes the task loop
```

The reasoning model proposes semantic skills and arguments. It does not choose
motor priority, collision policy, joint targets, or velocity ticks. Plan fields
that affect safety, verification, retry, resources, or interruption are compiled
or bounded by the system before the executive can run them.

Useful external patterns informed the interfaces but are not Parcel
controllers: SayCan/Inner-Monologue-style affordance feedback,
InternVLA-N1/NaVILA-style slow semantics over a fast controller, and the
classical global-plan/local-control/independent-shield split.

## Authority boundaries

| Boundary | Current authority | Explicitly not authoritative |
| --- | --- | --- |
| Meaning of a request | `IntentFrame` router; PlanIR only for deliberative tasks | Partial transcripts and model prose |
| Skill vocabulary and arguments | `brain/compiler.py`, `brain/validator.py`, admitted skill registry | Model-authored priorities, joint commands, arbitrary tools |
| Task ordering / interruption | `TaskExecutive` plus runtime activity coordination | The plan's requested interrupt by itself |
| Behavior command | Navigation, follow, or spatial controller selected for the task | Conversation model |
| Velocity ownership | `CommandArbiter` with a TTL | Any producer writing the backend directly |
| Environment collision veto | Final `navigation/reactive_safety.py` gate in `RobotRuntime` | Planner success or model confidence |
| Physical command and stop lifecycle | `ControlManager` and its one selected controller | Legacy `motion.backend` facade |
| Fast balance and gait on Go2 | Unitree's onboard Sport controller | Parcel's Python navigation loop |

`DirectiveNavigator` also applies `navigation/collision.py` to its own output.
That is useful local defense, but it is not the universal safety boundary. The
runtime applies `reactive_safety.py` after arbitration and smoothing to manual,
voice, follow, spatial, and navigation commands alike. `ControlManager` then
adds controller-state safety—fresh feedback, finite limits, tilt/fault checks,
command expiry, stop confirmation, and the software E-stop—but it has no camera
or LiDAR view of its own.

The current velocity priority order is:

```text
navigation (30) < follow (40) < spatial (50) < voice (60)
                < manual (80) < safety (100)
```

Every accepted intent expires unless refreshed. The E-stop is a separate,
latched state rather than merely another high-priority intent. These priorities
resolve simultaneous requests; runtime entry points also cancel incompatible
behaviors and use generation checks so a result computed before an ownership
change cannot silently regain the base.

Semantic-task interruption is a separate policy from velocity priority. The
model may request timing, but the executive decides: emergency, manual,
system-recovery, and explicit-stop events cancel immediately; corrections wait
for a checkpoint when required; social/gesture proposals wait for idle; and
conversation may overlap without acquiring the locomotion resource. Thus a
sympathetic gesture cannot interrupt an important navigation step merely
because the model emitted it.

## Semantic navigation path

A command such as “walk to the sidewalk” follows a concrete state machine:

1. The deterministic grammar rejects negated or hypothetical motion and
   extracts an explicit destination. A known POI may resolve from
   `configs/navigation/cities/demo_pois.yaml`; otherwise the destination becomes
   a typed object or region `SemanticGoal`.
2. `ActiveSemanticSearch` rotates in place. A camera/depth semantic candidate
   must meet the confidence threshold and be observed repeatedly before any
   translation is authorized.
3. `safe_approach_pose` samples an interior pose for a region or a stand-off
   ring for an object, checking camera semantics and observed LiDAR surfaces.
4. `grid_v1` builds a rolling LiDAR occupancy grid, inflates the Go2 footprint,
   runs A*, validates an observed segment, and emits a rotate-first,
   forward-preferred body-velocity command.
5. Navigation-local braking, runtime-wide reactive safety, arbitration, and the
   controller watchdog remain active on every tick.
6. Reaching the geometric tolerance requests an actual locomotion stop. A
   semantic task succeeds only after fresh perception still proves the requested
   relation (`inside` or `near`) and controller feedback proves the body has
   settled. Failed verification can re-ground the target within a bounded retry
   count.

This split gives “near the lamppost” a region of acceptable, collision-free
poses instead of pretending that a landmark center is a drivable point. It also
makes success an observed predicate, not merely the planner reporting
`arrived`.

## Perception and world-model boundary

Parcel's configured environmental sensors are exactly camera and LiDAR.
Locomotion feedback/odometry is still required to estimate the robot pose and
close control loops; it is internal robot state, not a third environmental
sensor. Google Maps is a disabled `NullMapProvider` placeholder and currently
has no route authority.

The normal geometric planner consumes only pose plus a calibrated planar LiDAR
scan. Semantic tasks and owner following consume typed tracks that a physical
adapter must derive from camera/depth and transform into the odometry frame.
The MuJoCo adapter currently synthesizes those tracks from scene metadata with
range/FOV filtering. That is useful for behavior regression, but it is not a
trained camera detector, visual localization stack, or proof of real-world
perception. The demo POI file is likewise a static coordinate prior, not live
Google Maps; using it on hardware requires a commissioned map frame and
localization.

## What is authoritative today

| Layer | Implemented default | Status / limitation |
| --- | --- | --- |
| Conversation and planning | Shared configured Gemma provider, logically split into conversation and planner roles, behind `IntentFrame` and PlanIR | Model service is optional; deterministic routes still work without it |
| Geometric navigation | `active_model: grid_v1` over the occlusion-true MuJoCo scan | Physical scan/localization adapter not implemented or commissioned |
| Semantic goal resolution | Typed simulator camera/depth tracks, bounded search, safe approach, terminal verification | Simulator tracks are metadata-derived; real open-vocabulary perception is absent |
| Owner-relative motion | Direct/behind follow and bounded step/orbit controllers | Depends on fresh, enrolled camera owner tracks; no identity re-identification stack |
| Collision | Navigation-local `collision.py` plus runtime-wide `reactive_safety.py` | Reactive rather than time-indexed crowd planning; no hardware safety certification |
| Locomotion | `ControlManager` plus simulator adapter by default; Unitree Sport adapter available behind commissioning gates | Unitree path is untested on a physical dog from this workstation |
| Product navigation evaluation | `evals/companion_nav/` plus headless city behavior tests | Kinematic simulation, not contact-dynamics or sim-to-real evidence |

Learned visual navigators (CityWalker, NaVILA, NoMaD, ViNT) remain research
metadata/checkpoints only. `build_navigator` accepts only `stub` and `grid` and
fails closed for learned types until a tested inference adapter exists. See
[NAVIGATION_CITY.md](NAVIGATION_CITY.md).

## Crucial design choices and tradeoffs

| Choice | Advantage | Limitation / cost |
| --- | --- | --- |
| Semantic LLM output, deterministic motion | Natural-language flexibility cannot bypass typed skills or the motor boundary | The fixed skill vocabulary cannot yet express every reasonable request |
| Separate conversation and planning roles, shared default backbone | Conversation can stream quickly while only physical multi-step tasks pay planning cost; one loaded model fits the device | Shared service contention and a single model's failure mode remain; logical separation is not independent redundancy |
| Classical grid planner as default | Inspectable, CPU-fast, sensor-grounded, deterministic regression behavior | Flat 2-D world, rolling local memory, no loop closure, terrain, or crowd prediction |
| Rotate first, then move forward | Avoids diagonal “sliding,” matches quadruped-facing behavior, and also works on non-holonomic adapters | Longer/slower than a holonomic optimum and can hesitate in dense crowds |
| Keep `vy` in the contract | Manual strafing and future local planners remain possible without changing the HAL | Every controller and safety check must reason about arbitrary travel direction |
| Two independent collision layers | Navigation bugs and competing manual/voice sources still meet a final veto | Duplicated thresholds require careful configuration; neither layer replaces a certified hardware stop |
| TTLs plus feedback-confirmed stopping | Dead producers decay to stop and semantic arrival cannot be declared while coasting | Adds stop latency and can reject progress when feedback is delayed or misframed |
| Loud point-goal fallback when the calibrated scan is missing | Simulator/API continuity and obvious telemetry instead of a hidden mode change | The fallback is less capable and may still translate; a hardware deployment must treat `scan_missing_fallback` as a degraded condition, not normal navigation |

## Evaluation policy

**Product gate:** companion-nav scenarios under `evals/companion_nav/` measure
following success, hard collisions (no sliding forgiveness), personal-space
intrusion, jerk, and time to reacquire.

**Fast semantic regression gate:** `tests/test_headless_city_tasks.py` and
related tests verify sidewalk, lamppost, and owner-orbit outcome predicates.
The headless base is kinematic and the semantic tracks are simulator-generated,
so this gate proves task logic rather than gait physics or camera recognition.

**Research/offline proxies:** BARN and Habitat adapters under
`evals/external/` stress metric planning on non-Go2 abstractions. They do not
measure companion quality, and official leaderboard claims still require the
organizers' stacks and attestation.

## Non-goals that stay non-goals

- LLM tokens never cross the motor trust boundary.
- BARN Jackal differential-drive success is not a Go2 companion quality metric.
- MuJoCo semantic metadata is not evidence of physical camera perception.
- A software E-stop is not a substitute for an independent hardware E-stop.
- MetaUrban, Isaac/URBAN-SIM, and SimWorld remain optional backends or services,
  not imports into the Python 3.14 runtime.
