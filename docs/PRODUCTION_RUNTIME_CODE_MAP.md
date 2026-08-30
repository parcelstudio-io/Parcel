# Production runtime: one-page code map

**Current outcome (2026-08-30): autonomous physical motion is NO-GO.** Parcel
has a guarded desktop/simulator transaction and a non-speaking execution-fact
observer. It does not have a commissioned Go2/Orin perception, audio,
localization, or independent-stop stack. Solid arrows below are composed now;
dashed arrows are uncommissioned target seams.

```text
COMPOSED DESKTOP / INJECTED PATH — no physical actuator authority

backend.observe -> SIMULATION snapshot -> explicit controller -> TTL arbiter
                                                        -> final safety -> simulator
owner-qualified turn -> compiler/validator -> TaskExecutive -> skill adapter
local STOP =================================> software latch / arbiter STOP
TaskExecutive -> transition journal -> authenticated observer -> non-speaking Model-B frame

UNCOMMISSIONED PHYSICAL TARGET

camera/LiDAR/LIO - - -> PHYSICAL snapshot - - -> Model A proposal - - -> planner/tracker
                                                                  - - -> final safety
remote/software STOP - - -> separate stop principal - - -> ControlManager/gateway STOP
physical E-stop - - -> physically independent hardware stop (not yet composed)
planner/tracker - - -> ControlManager - - -> Unix gateway - - -> Unitree Sport - - -> Go2
accepted event - - -> supervised Model B - - -> Realtime wording/audio
```

## How one transaction fits together

1. **Ingress and state.** [`web_panel.py`](../src/parcel_robot/web_panel.py)
   constructs [`RobotRuntime`](../src/parcel_robot/runtime.py) for today’s
   simulator stack. Backend observations pass through
   [`CarrierObservationSource`](../src/parcel_robot/observation/sources.py) and
   [`SnapshotAssembler`](../src/parcel_robot/observation/assembler.py) into a
   time- and lineage-stamped
   [`NavigationSnapshotV2`](../src/parcel_robot/contracts/navigation_snapshot_v2.py).
   Normal runtime stamps this path `SIMULATION`; the synchronized
   `PhysicalObservationSource` in the same sources module is a fail-closed
   skeleton. [`Go2Backend`](../src/parcel_robot/backends/go2.py) may read selected
   telemetry but cannot supply physical motion authority.

   Local/legacy speech uses
   [`audio/voice_loop.py`](../src/parcel_robot/audio/voice_loop.py); its
   `SpeakerSink` implementation is in
   [`audio/speaker.py`](../src/parcel_robot/audio/speaker.py). Hosted audio is a
   path through [`realtime/lane.py`](../src/parcel_robot/realtime/lane.py),
   [`realtime/audio_gateway.py`](../src/parcel_robot/realtime/audio_gateway.py),
   and [`realtime/browser_sink.py`](../src/parcel_robot/realtime/browser_sink.py).
   Emergency STOP goes directly to the software latch, independent of identity,
   planning, models, and cloud.

2. **Mission authority.** Agent/tool proposals are compiled and validated in
   [`brain/compiler.py`](../src/parcel_robot/brain/compiler.py) and
   [`brain/validator.py`](../src/parcel_robot/brain/validator.py).
   [`TaskExecutive`](../src/parcel_robot/brain/executive.py) alone owns queueing,
   revision, interruption, dispatch, accepted results, and terminal state. Each
   request/result is bound to `task + revision + step + attempt`. Revision
   replacement in
   [`executive_revision_transaction.py`](../src/parcel_robot/brain/executive_revision_transaction.py)
   locks every registered sink in one process-wide order across commit, owner-journal append, or
   compensation, preventing concurrent proposal publication/arbitration from
   observing a failed half-commit. It is thread-isolated in one process, not
   crash-durable or distributed.
   [`ExecutiveTransitionV1`](../src/parcel_robot/brain/executive_journal.py) and
   its bounded journal live beside the executive's split helpers,
   [`executive_interrupts.py`](../src/parcel_robot/brain/executive_interrupts.py)
   and [`executive_reporting.py`](../src/parcel_robot/brain/executive_reporting.py);
   [`SemanticTaskRuntimeAdapter`](../src/parcel_robot/brain/runtime_adapter.py)
   dispatches admitted skills without giving the executive actuator access.

3. **Model A and motion.** Model A is an unintegrated, proposal-only seam. It
   may eventually suggest short-lived trajectories, attention/expression, or a
   replan, but may not emit joints, bypass safety, or certify completion. Today,
   explicit controllers such as
   [`DirectiveNavigator`](../src/parcel_robot/navigation/pipeline.py) feed
   [`CommandArbiter`](../src/parcel_robot/core/arbiter.py). Runtime and
   [`core/hard_stop.py`](../src/parcel_robot/core/hard_stop.py) apply freshness,
   person/obstacle/TTC, and STOP gates before
   [`ControlManager`](../src/parcel_robot/control/manager.py), which owns leased
   velocity, stop confirmation, and controller faults.

   The uncomposed physical gateway facade is
   [`motion_gateway.py`](../src/parcel_robot/control/motion_gateway.py), with
   commissioned, session, and state logic in
   [`motion_gateway_commissioned.py`](../src/parcel_robot/control/motion_gateway_commissioned.py),
   [`motion_gateway_session.py`](../src/parcel_robot/control/motion_gateway_session.py),
   and [`motion_gateway_state.py`](../src/parcel_robot/control/motion_gateway_state.py).
   Wire contracts live in
   [`bridge/protocol.py`](../src/parcel_robot/bridge/protocol.py) and
   [`state_v2_codec.py`](../src/parcel_robot/bridge/state_v2_codec.py), ahead of
   [`gateway/core.py`](../gateway/core.py) and sole SDK2 writer
   [`gateway/ports.py`](../gateway/ports.py). No non-test caller arms this path;
   `Go2Backend` refuses move, pose, and trajectory calls.

4. **Model B and speech truth.** `RobotRuntime` polls the executive journal via
   [`JournalOnlyNarrativeRuntimeV1`](../src/parcel_robot/voice/execution_narrative_runtime.py)
   and [`execution_narrative_bridge.py`](../src/parcel_robot/brain/execution_narrative_bridge.py),
   producing bounded records from
   [`voice/execution_narrative.py`](../src/parcel_robot/voice/execution_narrative.py).
   These facts are authenticated, non-actuating, and fail-closed. Frames retain
   plan/step/attempt/mission/action/evidence/epoch/generation/deadline lineage;
   drain atomically rechecks epoch, generation, and expiry. Live Model B is not
   composed: commit-time timestamps, persistence/restart, an authenticated live
   speech epoch, provider/audio acknowledgement, and authoritative child/resume
   lineage are absent. A frame is not proof that speech was heard. The
   companion-friend default lives in
   [`relationship_prompt.py`](../src/parcel_robot/realtime/relationship_prompt.py).

## Mount boundary

[`deploy/orin/services/`](../deploy/orin/services/) now contains an explicit
boot-disarmed `parcel.target` graph, and its runtime unit selects the reviewed
`go2_edu_plus` overlay. Runtime binds to gateway and safety; stopping the target
deliberately leaves the safety principal alive, and fixed disarm/role/socket
invariants override optional environment files. Target-active is not readiness.
Runtime/LIO/audio executables, pinned aarch64 install, physical observation, and
an Orin run are still absent.
The next permissible rung is checklist-reviewed, permanently disarmed
physical-shadow or motors-disabled HIL. Powered motion additionally requires
synchronized mounted perception/localization, calibrated audio/AEC, robot
identity, measured AGX timing/thermals, commissioned credentials and launch,
real physical/remote STOP inputs, braking-distance evidence, and a physically
independent E-stop. Sidewalks, crosswalks, elevators, stairs, close pedestrians,
and all autonomous physical movement remain **NO-GO**; see the
[current product verdict](../research/20260829/product-evals/VERDICT.md).
