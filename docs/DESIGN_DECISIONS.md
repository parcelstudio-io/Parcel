# Crucial design decisions

This is Parcel's lightweight architecture-decision record. It complements the
[redesign assessment](REDESIGN_2026_ASSESSMENT.md) and the
[target architecture](REDESIGN_2026_ARCHITECTURE.md) by stating the choices
that must remain visible during refactors: why each choice exists, what it buys,
what it costs, and what evidence would justify changing it.

For the difference between implemented, wired, and operational, see
[CURRENT_STATUS.md](CURRENT_STATUS.md).

## Decision map

```text
voice/text → deterministic intent routing → typed PlanIR → validation/executive
                                                        ↓
camera/LiDAR observations → semantic grounding → grid/behavior controller
                                                        ↓
                                     priority arbiter + safety veto
                                                        ↓
                                leased body velocity → ControlManager
                                                        ↓
                              simulator or Unitree Sport controller

conversation/prosody ──→ subordinate expression channel (never locomotion authority)
```

## D1. The model emits semantic intent, never raw motor control

**Decision:** LLM output is parsed into a closed, typed PlanIR/PlanSketch
contract, validated against current observations and allowlisted skill
contracts, then executed by deterministic code. Raw velocity, joint, torque,
priority, and `force` fields are forbidden. Relevant code:
[`brain/contracts.py`](../src/parcel_robot/brain/contracts.py),
[`brain/validator.py`](../src/parcel_robot/brain/validator.py), and
[`brain/runtime_adapter.py`](../src/parcel_robot/brain/runtime_adapter.py).

**Advantages:** model replacement does not redefine the actuator API; malformed
or hallucinated actions fail closed; success conditions and interruption policy
are inspectable; the same plan contract is testable headlessly.

**Limitations:** strict schemas make novel instructions harder; grounding still
depends on perception and skill coverage; a valid plan can be foolish even when
it is syntactically safe. Validation is therefore necessary, not sufficient.

**Revisit when:** a new planner improves frozen semantic and embodied gates
without weakening the contract. End-to-end motor-token policies may propose
waypoints in research, but do not replace this safety boundary.

## D2. Nested closed loops and a single locomotion writer

**Decision:** `RobotRuntime` arbitrates semantic activities and short-lived
motion intents; [`ControlManager`](../src/parcel_robot/control/manager.py) is
the sole body-velocity writer on the product runtime path and supervises leases, state freshness, limits,
faults, stop confirmation, and E-stop; Unitree's Sport service initially owns
the high-rate balance/foot-placement loop. A future custom controller must
implement the same HAL contracts in
[`control/base.py`](../src/parcel_robot/control/base.py).

Viewer hotkeys, direct simulator IPC, and the standalone `Dog` API are explicit
debug/development bypasses and do not inherit this whole boundary.

**Advantages:** each loop runs at its appropriate timescale; stale processes
decay to stop; vendor replacement is bounded; application Python does not have
to solve balance before the product behavior is useful.

**Limitations:** Sport is a closed vendor subsystem with limited internal
observability and tuning; feedback does not prove every foot is safe; network,
frame, mode, and firmware commissioning remain hardware-specific. The software
E-stop is not independent hardware protection.

**Revisit when:** repeated tasks require dynamics Sport cannot express, and a
new controller passes simulator, hardware-in-the-loop, fall, thermal, and stop
tests behind the same manager. Never run Sport and direct `LowCmd` together.

## D3. Classical geometry is the admitted navigation default

**Decision:** `grid_v1` consumes the rolling raycast/LiDAR contract, constructs
occupancy, plans with A*, and produces forward-preferred mid-level motion.
[`reactive_safety.py`](../src/parcel_robot/navigation/reactive_safety.py) applies
an independent final veto to `RobotRuntime` velocity sources. Learned entries fail closed until an inference
adapter and evaluation evidence exist.

**Advantages:** deterministic, debuggable, cheap, reproducible, and usable on
CPU; collision logic does not depend on model compliance; failures leave maps,
paths, and reason codes.

**Limitations:** a 2-D local grid is weak on curbs, stairs, overhangs,
non-stationary crowd prediction, long-range localization, and ambiguous visual
semantics. A reactive veto can stop safely yet deadlock. Simulation labels make
semantic grounding look easier than it will be on hardware.

**Revisit when:** a learned or model-predictive proposer improves product
scenario metrics and external proxies while the independent safety layer and
SE(2) command contract remain intact.

## D4. Forward-preferred does not mean nonholonomic

**Decision:** ordinary point-goal motion aligns first, then translates mostly
forward. Body-frame lateral velocity remains available for manual control,
close repositioning, recovery, and intentionally holonomic planners.

**Advantages:** motion reads like a quadruped rather than a sliding game token;
heading simplifies camera coverage and obstacle reasoning; the hardware's
useful strafing capability is retained.

**Limitations:** rotate-first can be slower or oscillate in tight crowds; strict
forward bias can make lateral escape inefficient; kinematic MuJoCo smoothness
does not establish physical stability.

**Revisit when:** a local MPC/MPPI controller can choose lateral motion from
footprint, dynamics, and predicted agents while preserving comfort and safety
metrics.

## D5. Camera and LiDAR are the perception authority

**Decision:** planning receives camera-derived tracks/semantics and the planar
LiDAR contract. Simulator geometry may generate those observations, but code
outside the simulator must not query privileged world truth. Google Maps is a
disabled, advisory placeholder, never local collision or pose authority.

**Advantages:** sim-to-real interfaces stay honest; unit tests can inject sensor
records; external maps cannot override immediate evidence.

**Limitations:** the simulated semantic detector is currently much cleaner than
real perception; planar LiDAR misses important 3-D hazards; localization,
calibration, occlusion, identity continuity, and sensor disagreement are not
solved by the contract alone.

**Revisit when:** hardware sensors land. Add uncertainty, timestamps, calibration
health, and 3-D/elevation observations without exposing simulator-only state.

## D6. Hybrid duplex voice keeps text as the action boundary

**Decision:** audio capture, endpointing, replaceable ASR, a text reasoner, and
cancellable TTS are separate components. The present mic path submits a whole
committed utterance to whisper.cpp; true streaming ASR is the target. Partial
transcripts may reduce latency or interrupt output, but only a committed/final
turn can dispatch an action. Audio codec tokens remain inside a speech provider. See
[`voice_audio.py`](../src/parcel_robot/voice_audio.py),
[`voice_pipeline.py`](../src/parcel_robot/voice_pipeline.py), and
[`providers.py`](../src/parcel_robot/providers.py).

**Advantages:** STT/TTS models remain replaceable; text plans are auditable;
barge-in does not grant uncommitted speech motor authority; degraded text mode
continues when hardware or a service fails.

**Limitations:** cascades compound latency and recognition errors; text loses
prosody; full duplex without AEC is fragile; sentence chunking is less natural
than a native streaming speech model. Current desktop audio is not operational.

**Revisit when:** an open speech-to-speech model fits target compute and meets
tool reliability, cancellation, privacy, and latency gates. Even then, treat its
action output as a proposal to the same PlanIR validator.

## D7. Conversation and planning are separable lanes, not separate authorities

**Decision:** the runtime accepts distinct `language_model` and `planner_model`
providers. The deterministic intent router chooses when deliberative planning
is needed; both lanes terminate at the same typed contract. The default shares
Gemma because measured specialist challengers did not clear quality gates.

**Advantages:** a fast conversational model and a slower spatial planner can be
tuned, scaled, and measured independently; ordinary chat avoids planning
latency; failures are attributable by role.

**Limitations:** two models add memory, service orchestration, consistency
problems, and duplicated context. Intent-routing mistakes can send a hard task
to the wrong lane. A second model is not automatically a second opinion.

**Revisit when:** a candidate clears conversation and embodied-plan gates by
role, including cold start and resource contention with STT/TTS/navigation.

## D8. Expression is an additive, subordinate channel

**Decision:** the LLM chooses bounded semantic gesture categories; prosody
chooses fine timing. Idle, reaction, and beat layers are additive, clamped,
epoch-scoped, and gated off by skills, hazards, critical battery, or E-stop.
The expression loop runs at 50 Hz because timing needs are different from the
10 Hz decision loop. See [`expression.py`](../src/parcel_robot/expression.py)
and [`prosody.py`](../src/parcel_robot/prosody.py).

**Advantages:** personality does not become locomotion authority; interruption
can atomically cancel speech-synchronized motion; deterministic motion remains
responsive without an LLM call per beat.

**Limitations:** additive joint offsets can still conflict with an unknown
vendor controller; simulator appeal does not prove support-polygon or torque
safety; pitch/accent heuristics are language- and voice-dependent; Go2 has no
neck joint, so the current head-nod state is not a directly actuated gesture on
that embodiment.

**Revisit when:** hardware actuation lag and safe envelopes are measured. A
whole-body motion mixer may replace offsets, but must retain epoch cancellation,
clamps, and higher-priority suppression.

## D9. MuJoCo is the deterministic inner loop; rich worlds stay out of process

**Decision:** MuJoCo remains the daily simulator and headless regression
backend. MetaUrban, URBAN-SIM/Isaac, Habitat, and game engines integrate through
versioned process/IPC adapters rather than being imported into Parcel's Python
3.14 application environment.

**Advantages:** fast reproducible tests, low GPU contention, dependency
isolation, and one authoritative world process; simulator replacement does not
rewrite behavior or control contracts.

**Limitations:** the current compact city lacks photorealism, realistic crowd
policy, rich weather, and credible Go2 base dynamics. IPC adds schema/version
work and can hide timing differences between engines.

**Revisit when:** a richer backend has a complete observation/action adapter,
deterministic seed/replay, health/watchdog semantics, and regression parity.

## D10. Python orchestrates; native code is introduced at measured boundaries

**Decision:** keep product behavior, planning, evaluation, and orchestration in
Python for now. Use vendor-native C++/SDK processes for hard real-time drivers
and consider Rust only for isolated services where memory safety and predictable
latency provide measured value. Do not rewrite the entire codebase preemptively.

**Advantages:** fastest iteration across models/simulators; excellent ML and
robotics libraries; tests and contracts already encode substantial behavior;
process boundaries isolate the GIL from native real-time loops.

**Limitations:** Python threads are not hard real time; GC/GIL scheduling and
dynamic typing can hurt tail latency; packaging Python 3.14 alongside ROS Humble
is awkward. The current wheel is not relocatable because prompts and repository
configuration assets are not packaged and the internal fallback config has
drifted; only source-checkout/editable execution is supported.

**Revisit when:** profiling shows a specific deadline or resource budget is
missed. Port that component behind an existing protocol and compare identical
traces before broadening the rewrite.

## D11. External benchmarks are evidence, not the product objective

**Decision:** product companion scenarios are the admission gate. BARN,
Habitat, and other external environments are frozen, provenance-tracked proxies
used to expose navigation weaknesses. Adapters translate interfaces; they do
not alter Parcel behavior or benchmark semantics. Every run is append-only with
date, run ID, change description, metrics, and `does_not_prove` boundaries.

**Advantages:** prevents benchmark-specific behavior from silently replacing
the robot-dog embodiment; preserves reproducibility; enables useful comparison
with published systems.

**Limitations:** proxy scores may weakly correlate with following, voice,
quadruped stability, or social comfort; official runtimes can be expensive or
incompatible; top-decile targets are meaningless without matched protocol.

**Revisit when:** an external task materially matches the product sensor,
action, embodiment, and success contracts. Promote it only with an explicit
mapping and retained product gates.

## D12. Dynamic context is bounded, local, and non-blocking

**Decision:** stable prompt instructions and volatile per-turn context are
composed in separate budgeted planes. Context sources must return snapshots
without blocking; information tools are named, read-only, and fail closed.
Arbitrary UI-provided system prompts are not accepted. See
[`dynamic_prompting.py`](../src/parcel_robot/dynamic_prompting.py) and the
trusted [`prompts/`](../prompts) tree.

**Advantages:** protects latency and prompt-cache stability; gives personality
and owner facts explicit provenance; limits prompt/tool escalation; exposes the
rendered prompt for debugging.

**Limitations:** stale snapshots can mislead; character budgets can discard
useful facts; owner-profile storage raises privacy and lifecycle questions;
read-only tools still need authentication, rate limits, and trust labels.

**Revisit when:** episodic memory or network retrieval is added. Prefetch off
the critical path, attach age/source/confidence, define retention/deletion, and
keep external results advisory until validated against sensors.

## D13. Observability must not become a shadow control path

**Decision:** turn traces and rolling component metrics are read-only
diagnostics. The latency panel shows user text, model response, reasoning source,
stage timestamps, and aggregates, but cannot issue commands. Sensitive raw
audio is not required for core latency measurement.

**Advantages:** separates user-facing E2E latency from model, TTS, endpointing,
control, and navigation bottlenecks; supports regression work without granting
the dashboard authority.

**Limitations:** software timestamps can cross unsynchronized clocks or omit
device buffers; logging transcripts creates privacy risk; percentile summaries
can hide failed/cancelled turns.

**Revisit when:** physical hardware is connected. Add monotonic clock mapping,
audio-device and actuator-feedback markers, failure/cancellation stratification,
and an explicit data-retention policy before collecting real conversations.

## Change discipline

For a decision-changing pull request:

1. update the relevant decision and its revisit evidence;
2. update [CURRENT_STATUS.md](CURRENT_STATUS.md) if operational state changed;
3. add or update a regression/eval that tests the promised boundary; and
4. keep aspirational research language clearly marked as planned or
   experimental.
