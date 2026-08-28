# Production-shaped runtime code map

**Code audit: 2026-08-26.** This is the shortest current-checkout map. Here,
“production-shaped” means authority and lifecycle boundaries intended for the
eventual robot—not a commissioned physical Go2. Use the [root README](../README.md)
for readiness and [robotics code design](ROBOTICS_CODE_DESIGN.md) for rationale.

## Runtime path

```text
launch_stack.sh -> launch_sim.sh -> web_panel.build_runtime -> RobotRuntime

browser turn
  +-- hosted -> RealtimeLane -> RealtimeToolBroker --+
  +-- local  -> VoiceAgent / deterministic router ----+
                                                    |
       +-- immediate bounded action -----------------------> runtime door
       +-- model- or system-authored PlanSketch/PlanIR -> compiler + validator
                  -> TaskExecutive + SemanticTaskRuntimeAdapter
                                                    |
                                      behavior / mission state
                                                    |
  +-- SE(2) velocity: manual/nav/follow/search/spatial -> submit_motion
  |      -> CommandArbiter -> RobotRuntime._dispatch_active
  |      -> input health/reactive/TTC/final STOP -> ControlManager -> backend
  +-- pose/trajectory: admitted door/coordinator -> stop SE(2) -> sim backend
  `-- expression: subordinate 50 Hz overlay ------------> simulator backend

feedback <- backend.observe -> carrier + NavigationSnapshotV2
         -> safety, planners, executive verification and /api/state
```

Local stop phrases and E-stop controls take a deterministic short path; they do
not wait for model generation or plan completion.

## Who owns what

- **Startup and turns.** [`scripts/launch_stack.sh`](../scripts/launch_stack.sh)
  prepares the hosted lane and optional local model services, then
  [`scripts/launch_sim.sh`](../scripts/launch_sim.sh) starts MuJoCo and the panel.
  [`web_panel.build_runtime`](../src/parcel_robot/web_panel.py) selects the backend
  and models and constructs [`RobotRuntime`](../src/parcel_robot/runtime.py).
  `RuntimeRequestHandler` keeps hosted and local/eval ingress separate;
  [`RealtimeLane`](../src/parcel_robot/realtime/lane.py) owns hosted turn/barge-in
  state, [`RealtimeToolBroker`](../src/parcel_robot/realtime/tool_broker.py)
  validates its bounded tools, and [`VoiceAgent`](../src/parcel_robot/voice/agent.py)
  owns the local lane.

- **Meaning and admission.** Ingress may use an immediate restricted runtime
  door or produce a model- or system-authored `PlanSketch`/`PlanIR`; local
  deterministic Follow, Hold and Come plus several hosted navigation tools use
  the latter path.
  Planned work flows through
  [`brain/compiler.py`](../src/parcel_robot/brain/compiler.py), where model-authored
  skill order/arguments remain proposals while the system supplies the contract
  envelope, and [`PlanValidator`](../src/parcel_robot/brain/validator.py).
  [`TaskExecutive`](../src/parcel_robot/brain/executive.py) and
  [`SemanticTaskRuntimeAdapter`](../src/parcel_robot/brain/runtime_adapter.py)
  own lifecycle, interruption, dispatch and evidence-based completion.
  [`CapabilityManifestV1`](../src/parcel_robot/capabilities/manifest.py) binds
  admitted actions to one deployment and authenticated commissioning evidence.

- **World state and decisions.** Every control tick begins with
  `backend.observe()`. [`CarrierObservationSource`](../src/parcel_robot/observation/sources.py),
  [`SnapshotAssembler`](../src/parcel_robot/observation/assembler.py) and
  [`NavigationSnapshotV2`](../src/parcel_robot/contracts/navigation_snapshot_v2.py)
  add timing, lineage, health, owner, traversability, track and semantic facts.
  V2 currently accompanies the legacy carrier; final reactive safety still reads
  the carrier. [`DirectiveNavigator`](../src/parcel_robot/navigation/pipeline.py)
  owns semantic grounding, `grid_v1`, progress/recovery and bounded velocity.

- **Effect authority.** Velocity producers enter
  [`CommandArbiter`](../src/parcel_robot/core/arbiter.py) with priority and TTL.
  `RobotRuntime._dispatch_active` then applies input-health, person/obstacle/TTC,
  shaping and [`finalize_command`](../src/parcel_robot/core/hard_stop.py) before
  the single **velocity/locomotion** owner,
  [`ControlManager`](../src/parcel_robot/control/manager.py). The normal simulator
  uses [`BackendVelocityController`](../src/parcel_robot/control/adapters.py) and
  [`MujocoSocketBackend`](../src/parcel_robot/backends/mujoco.py). Social gestures
  and hosted pose proposals use
  [`ActivityCoordinator`](../src/parcel_robot/core/activities.py); admitted plan
  steps, local catalog calls and pose review can reach `RobotRuntime._run_pose`
  or `_run_trajectory` directly. Both routes stop locomotion before the simulator
  backend call. Expression is a separate subordinate lane in
  [`motion/expression.py`](../src/parcel_robot/motion/expression.py).
  Pose/trajectory are refused with external physical control; Go2 expression
  has no actuation channel and degrades to snapshot-only.

- **Feedback and learning.** Backend observations and controller snapshots feed
  planners, runtime verification and `/api/state`. The default-off
  [`research_plane/`](../src/parcel_robot/research_plane/) and
  [`learning_loop/`](../src/parcel_robot/learning_loop/) may record evidence or
  propose candidates, but cannot command, train/deploy automatically, or activate
  a model.

## Current deployment truth

The full normal product composition is the simulator panel path above. Manual
browser velocity can move MuJoCo through arbitration and final safety. Automatic
navigation, poses and gestures fail closed because `web_panel.build_runtime`
does not supply a capability manifest, deployment target or commissioning
authenticator. Explicit emote configuration is a desired optional set: a
commissioned runtime intersects it with the authenticated manifest, excludes
uncommissioned entries such as the aerial `hop` trajectory, and exposes every
omission under `/api/state` at `brain.emote_capabilities` plus a structured
startup warning. The CLI and ROS nodes are reduced request boundaries, not the
complete observation/arbitration/final-safety runtime.

Physical pieces remain separate. [`Go2Backend`](../src/parcel_robot/backends/go2.py)
is observe-only. A guarded direct [`UnitreeSportController`](../src/parcel_robot/control/unitree_sport.py)
and [`unitree_control` commissioning CLI](../src/parcel_robot/unitree_control.py)
exist, but are not composed into autonomous runtime. The gateway process still
uses fake Sport; its explicitly injected
[`DisarmedGatewayControllerV1`](../src/parcel_robot/control/motion_gateway.py)
uses [`MotionGatewayClientV1`](../src/parcel_robot/bridge/gateway_client.py) for state/stops but
exposes no acquire or velocity command.

A vendor-backed gateway writer, synchronized physical V2 evidence, AGX timing and
stopping measurements, and one commissioned launcher are still missing. The
five-service Orin layout is a [deployment skeleton](../deploy/orin/services/README.md),
not the current topology. Autonomous physical operation remains **NO-GO**.
