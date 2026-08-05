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
       |-> SearchOwnerController (bounded reacquisition)
       `-> SpatialBehaviorController (bounded relative move / owner orbit)
  -> CommandArbiter (one time-limited velocity intent)
  -> acceleration smoothing
  -> final runtime proximity + constant-velocity TTC gates
  -> jerk-limited actuator hand-off (hard stops bypass it)
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
| Task ordering / interruption | `TaskExecutive`, `PreemptionTable`, and runtime activity coordination | The plan's requested interrupt by itself |
| Behavior command | Navigation, search, follow, or spatial controller selected for the task | Conversation model |
| Velocity ownership | `CommandArbiter` with a TTL | Any producer writing the backend directly |
| Environment collision veto | Final runtime `reactive_safety.py` proximity/TTC logic plus the configured outgoing dynamic-track TTC gate | Planner success, soft route costs, or model confidence |
| Physical command and stop lifecycle | `ControlManager` and its one selected controller | Legacy `motion.backend` facade |
| Fast balance and gait on Go2 | Unitree's onboard Sport controller | Parcel's Python navigation loop |

`DirectiveNavigator` also applies `navigation/collision.py` to its own output.
That is useful local defense, but it is not the universal safety boundary. The
runtime applies `reactive_safety.py` and a configured constant-velocity
time-to-collision brake after arbitration and smoothing to manual, voice,
follow, search, spatial, and navigation commands alike. The later S-curve
shaper cannot release a stop: all stop paths use its emergency bypass.
`ControlManager` then adds controller-state safety—fresh feedback, finite
limits, tilt/fault checks, command expiry, stop confirmation, and the software
E-stop—but it has no camera or LiDAR view of its own.

The current velocity priority order is:

```text
navigation (30) < search (35) < follow (40) < spatial (50) < voice (60)
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
ordinary conversation may overlap without acquiring the locomotion resource.
The voice policy can mark an owner summons as `suspended`, which releases the
executive resource lease and pauses a navigation/search channel without
advancing its budget. That lifecycle is only partly integrated today:
`resume_task()` requeues the executive step, but semantic redispatch does not
yet consume the channel's `ResumeIntent` automatically. Explicit
`resume_navigation()` works; full cross-channel automatic resume and central
enforcement of `requires_fresh_observation` remain unfinished. See
[PAUSE_SEMANTICS.md](PAUSE_SEMANTICS.md).

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
   adds a soft two-second constant-velocity cost field for current dynamic
   tracks, runs A*, validates an observed segment, and emits a rotate-first,
   forward-preferred body-velocity command.
5. Navigation-local braking, runtime-wide proximity/TTC braking, arbitration,
   and the controller watchdog remain active on every tick. Dynamic costs are
   route preferences rather than collision masks; the safety gates remain
   authoritative.
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

The static occupancy and route geometry consume pose plus a calibrated planar
LiDAR scan. The optional dynamic cost additionally consumes bounded agent and
owner tracks. Semantic tasks and owner following consume typed tracks that a
physical adapter must derive from camera/depth and transform into the odometry
frame. The MuJoCo adapter currently synthesizes those tracks from scene
metadata with range/FOV filtering. That is useful for behavior regression, but
it is not a trained camera detector, visual localization stack, or proof of
real-world perception. The demo POI file is likewise a static coordinate prior,
not live Google Maps; using it on hardware requires a commissioned map frame
and localization.

## What is authoritative today

| Layer | Implemented default | Status / limitation |
| --- | --- | --- |
| Conversation and planning | Shared configured Gemma provider, logically split into conversation and planner roles, behind `IntentFrame` and PlanIR | Model service is optional; deterministic routes still work without it |
| Geometric navigation | `active_model: grid_v1` over the occlusion-true MuJoCo scan | Physical scan/localization adapter not implemented or commissioned |
| Semantic goal resolution | Typed simulator camera/depth tracks, bounded search, safe approach, terminal verification | Simulator tracks are metadata-derived; real open-vocabulary perception is absent |
| Owner-relative motion | Direct/behind follow, bounded step/orbit, lead-point prediction, and three-stage owner reacquisition | Depends on fresh, enrolled camera owner tracks; no identity re-identification stack; search degrades to coverage-only ranking without calibrated LiDAR |
| Dynamic-agent handling | Per-tick constant-velocity A* cost field plus two outgoing TTC/proximity checks | Bounded prediction only: no uncertainty model, interaction model, ORCA negotiation, or hardware safety certification |
| Locomotion | `ControlManager` plus simulator adapter by default; Unitree Sport adapter available behind commissioning gates | Unitree path is untested on a physical dog from this workstation |
| Product navigation evaluation | `evals/companion_nav/`, `evals/companion/embodied_plan_v1/`, and headless city behavior tests | Kinematic simulation, metadata-derived semantics, and currently unsupported `FollowFormation` in the embodied-plan harness |

Learned visual navigators (CityWalker, NaVILA, NoMaD, ViNT) remain research
metadata/checkpoints only. `build_navigator` accepts only `stub` and `grid` and
fails closed for learned types until a tested inference adapter exists. See
[NAVIGATION_CITY.md](NAVIGATION_CITY.md).

## Crucial design choices and tradeoffs

| Choice | Advantage | Limitation / cost |
| --- | --- | --- |
| Semantic LLM output, deterministic motion | Natural-language flexibility cannot bypass typed skills or the motor boundary | The fixed skill vocabulary cannot yet express every reasonable request |
| Separate conversation and planning roles, shared default backbone | Conversation can stream quickly while only physical multi-step tasks pay planning cost; one loaded model fits the device | Shared service contention and a single model's failure mode remain; logical separation is not independent redundancy |
| Classical grid planner as default | Inspectable, CPU-fast, sensor-grounded, deterministic regression behavior | Flat 2-D world, rolling local memory, no loop closure or terrain model, and only bounded constant-velocity crowd prediction |
| Rotate first, then move forward | Avoids diagonal “sliding,” matches quadruped-facing behavior, and also works on non-holonomic adapters | Longer/slower than a holonomic optimum and can hesitate in dense crowds |
| Keep `vy` in the contract | Manual strafing and future local planners remain possible without changing the HAL | Every controller and safety check must reason about arbitrary travel direction |
| Soft dynamic route cost plus independent hard gates | A* can prefer a route away from predicted people without granting the predictor safety authority | Constant-velocity Gaussian lobes can be wrong; malformed tracks disable the soft layer for that tick, and the hard gates still need fresh geometry |
| Layered speed envelope | Planner tuning, behavior policy, and hardware/body limits can be changed independently | The numbers are easy to misread: current `grid_v1` asks for `0.85 m/s`, the navigation wrapper caps it at `0.45 m/s`, and the global body clamp is `1.0 m/s` |
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

**Embodied-plan gate:** `evals/companion/embodied_plan_v1/` runs accepted PlanIR
through the executive and the same headless navigation/spatial controllers.
Four physical skill cases are supported; `FollowFormation` is explicitly
reported as unsupported rather than counted as a failure or silently mocked.
The committed JSON result is a historical run, so regenerate it before citing
metrics for the current configuration.

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
