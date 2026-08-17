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

observed replies + admitted behavior ──→ D0 TEXT/ACT frames ──→ local corpus
                                      (shadow consumer; no control authority)
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

Normal outgoing commands are jerk-limited after arbitration and collision/TTC
safety and immediately before `ControlManager`. Explicit E-stop/terminal stop
paths reset or call through to manager stopping, but a 2026-08-09 audit found
that the ordinary environmental-veto path enters a bounded emergency ramp
rather than reasserting exact zero. The intended decision remains a single
actuator handoff with non-relaxable post-shaper safety; implementing that typed
final disposition is now P0 work.

Interruption semantics distinguish **pause** from **stop**. A pausable channel
releases its lease and records a bounded `ResumeIntent`; the intended resumption
path re-enters the controller/executive rather than replaying a stale velocity.
That contract is incomplete today: semantic NavigateTo redispatch does not
consume the stored intent or call `resume_navigation`, fresh-observation is only
metadata, and search→follow still uses a legacy tuple.

Viewer hotkeys, direct simulator IPC, and the standalone `Dog` API are explicit
debug/development bypasses and do not inherit this whole boundary.

**Advantages:** each loop runs at its appropriate timescale; stale processes
decay to stop; vendor replacement is bounded; application Python does not have
to solve balance before the product behavior is useful.

**Limitations:** Sport is a closed vendor subsystem with limited internal
observability and tuning; feedback does not prove every foot is safe; network,
frame, mode, and firmware commissioning remain hardware-specific. The software
E-stop is not independent hardware protection. The measured 42% commanded-jerk
reduction uses a companion-eval replica that stops before `ControlManager` and
the HAL; it is not a physical smoothness result.

**Revisit when:** repeated tasks require dynamics Sport cannot express, and a
new controller passes simulator, hardware-in-the-loop, fall, thermal, and stop
tests behind the same manager. Never run Sport and direct `LowCmd` together.

## D3. Classical geometry is the admitted navigation default

**Decision:** `grid_v1` consumes the rolling raycast/LiDAR contract, constructs
occupancy, plans with A*, and produces forward-preferred mid-level motion.
It overlays bounded predicted-agent costs on A* and applies an all-track
time-to-collision brake before command shaping.
[`reactive_safety.py`](../src/parcel_robot/navigation/reactive_safety.py) applies
an independent final veto to `RobotRuntime` velocity sources. Learned entries fail closed until an inference
adapter and evaluation evidence exist.

**Advantages:** deterministic, debuggable, cheap, reproducible, and usable on
CPU; collision logic does not depend on model compliance; failures leave maps,
paths, and reason codes.

**Limitations:** a 2-D local grid is weak on curbs, stairs, overhangs,
non-stationary crowd prediction, long-range localization, and ambiguous visual
semantics. A reactive veto can stop safely yet deadlock. Simulation labels make
semantic grounding look easier than it will be on hardware. The current dynamic
cost can leave a predicted corridor; its normalized gradient and smoothing
exposure checks prevent two earlier erasure modes. Arrival-time-free sampling
still does not establish socially correct pass-behind behavior. The predictive
TTC gate engages, but its benefit is not yet separated from the existing
reactive-person brake.

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

The D0 10 Hz TEXT+ACT frame overlay is an aligned observation/logging contract,
not a second action authority; see D14. The audio path is still turn-committed
input, not simultaneous streaming acoustic tokens.

**Advantages:** STT/TTS models remain replaceable; text plans are auditable;
barge-in does not grant uncommitted speech motor authority; degraded text mode
continues when hardware or a service fails.

**Limitations:** cascades compound latency and recognition errors; text loses
prosody; full duplex without AEC is fragile; sentence chunking is less natural
than a native streaming speech model. Current desktop audio is not operational,
and deterministic fillers have only fake-TTS/scripted-clock evidence.

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
that embodiment. Owner-proximity gating suppresses expression through much of
some follow episodes. The new `StimulusBus` and `ReactionArbiter` are pure,
unit-tested foundations only; they are not yet fed or ticked by the runtime.

**Revisit when:** hardware actuation lag and safe envelopes are measured. A
whole-body motion mixer may replace offsets, but must retain epoch cancellation,
clamps, and higher-priority suppression.

The 2026-08-09 starter palette adds short self-returning social trajectories
and persistent explicit poses as a separate, serialized whole-body skill path.
They do not weaken this decision: inferred reactions defer while the base is
busy, and all custom joint targets remain simulator-only/hardware-unverified.
See [EMBODIED_EXPRESSION.md](EMBODIED_EXPRESSION.md).

Contextual chuckle/nod/shake/shrug/tilt proposals are a separate short-lived
class: they execute only while idle, expire within two seconds, and are skipped
if navigation, following, manual control, or another physical activity already
owns the body. Explicit owner gesture commands may still defer. This prevents a
social reaction from replaying after its conversational meaning has gone stale.

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
drifted; its legacy speech keys are rejected by current validation. Only
source-checkout/editable execution is supported.

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

The live `current_situation` source already renders in the volatile `turn`
plane. Future retrieval therefore extends the snapshot/refresh mechanism rather
than moving runtime state back into the stable prefix.

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
audio is not required for core latency measurement. D0 duplex session logs are
a separate, local aligned-stream corpus with an explicit configuration kill
switch; they are not the dashboard and have no control privilege.

**Advantages:** separates user-facing E2E latency from model, TTS, endpointing,
control, and navigation bottlenecks; supports regression work without granting
the dashboard authority.

**Limitations:** software timestamps can cross unsynchronized clocks or omit
device buffers; logging transcripts creates privacy risk; percentile summaries
can hide failed/cancelled turns. Duplex rotation has not been exercised over a
long session, its <2 MB/hour budget is a target rather than evidence, and no
retention/deletion policy is enforced.

**Revisit when:** physical hardware is connected. Add monotonic clock mapping,
audio-device and actuator-feedback markers, failure/cancellation stratification,
and an explicit data-retention policy before collecting real conversations.

## D14. Dual-stream behavior is introduced shadow-first

**Decision:** D0 freezes a shared nominal-10 Hz `DuplexFrame {t, epoch, text, act}`
contract. Reply text entering the spoken/text delivery path populates TEXT;
events already admitted
by planning, arbitration, expression, and safety populate ACT; silence/idle fill
the gaps. Epoch changes drop stale frames. The consumer remains shadow-only and
the local writer may build an aligned behavior-cloning corpus. See
[`duplex/`](../src/parcel_robot/duplex) and
[`DUPLEX_DUAL_STREAM_DESIGN.md`](DUPLEX_DUAL_STREAM_DESIGN.md).

**Advantages:** the eventual model boundary is testable before training a model;
idle becomes an explicit negative action label; TEXT and ACT share cancellation
semantics; D0 cannot accidentally acquire actuator authority.

**Limitations:** continuity proves index production and epoch/drop rules, not a
10 Hz wall-clock deadline—the caller supplies cadence and `missing_frames`
cannot detect a late tick. It also does not show that a model chose a good
action. D0 records effects of the current stack and can encode its biases; its
shadow round-trip is not a closed-loop policy eval. Reply-derived text and
owner/context values are sensitive even though the user transcript is not
written today. There is no D1 dual-head model, streaming audio input, or
non-shadow ACT execution in this checkout.

**Revisit when:** a D1 candidate is trained from consented/reviewed data and
beats D0 on identical duplex and product-navigation scenarios. Promotion still
requires PlanIR/admissibility, epoch atomicity, collision, latency, and
interruption gates; a model token never bypasses the existing authority chain.

## D15. Voice providers are optional adapters, not conversation or motion owners

**Decision:** retain the local typed STT -> brain -> TTS cascade as the first-ODD
rollback while allowing modular and native speech-to-speech services through one
provider-neutral registry and normalized media/session contracts. A managed provider
may emit transcripts, reply audio, usage, state, and tool proposals; it cannot mint a
`CommittedTurnV1`, `CommandAuthorityV1`, task event, terminal witness, or gateway
command. Provider/model/session IDs remain evidence fields rather than domain
identity. See [VOICE_PROVIDER_ARCHITECTURE.md](VOICE_PROVIDER_ARCHITECTURE.md).

**Advantages:** OpenAI, Gemini, Grok, Qwen, Hume, managed cascades, and the local
stack can be compared or replaced without rewriting authority, memory, tools, audio
playback, or safety. One conformance suite catches cancellation, codec, sequence,
backpressure, and reconnect differences. A cloud outage does not remove local STOP
or text/typed control.

**Limitations:** normalization cannot erase real capability differences; native
sessions may hide endpointing, transcripts, context, or token use; transcoding and
an extra abstraction add latency and implementation work. Supporting several
providers multiplies credentials, privacy reviews, failure modes, and live test cost.

**Revisit when:** a provider-neutral adapter has exact on-chassis evidence that a
vendor-specific capability cannot be represented without a material quality loss.
Even then, add an optional capability extension rather than granting a vendor SDK
authority or making its event IDs durable product state.

## Change discipline

For a decision-changing pull request:

1. update the relevant decision and its revisit evidence;
2. update [CURRENT_STATUS.md](CURRENT_STATUS.md) if operational state changed;
3. add or update a regression/eval that tests the promised boundary; and
4. keep aspirational research language clearly marked as planned or
   experimental.
