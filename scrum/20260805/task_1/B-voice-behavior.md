# Workstream B — voice-driven planning and natural companion behavior

## Decision

Split the current `VoiceAgent` into three logical model lanes plus one trusted
fast lane:

```text
partial/final speech events
  |-> deterministic reflex/direct-command router
  |-> conversation service ------------> DialogueAct + SocialCue
  |-> task-planning service ------------> PlanSketch
  `-> cancellation/endpoint events

PlanSketch -> trusted compiler -> PlanIR -> validator -> TaskExecutive
SocialCue  -> personality policy -> ReactionProposal -> ReactionArbiter
```

“The model outputs the next action” should mean **the next semantic skill or
goal proposal**, never the next velocity tick. The local navigator continuously
re-evaluates motion from fresh geometry; the executive continuously re-evaluates
task state and resources. This is the useful division demonstrated by
[SayCan](https://arxiv.org/abs/2204.01691),
[Inner Monologue](https://arxiv.org/abs/2207.05608),
[RT-H](https://arxiv.org/abs/2403.01823), and
[NaVILA](https://navila-bot.github.io/).

## Current code diagnosis

Keep these existing primitives:

- `brain/contracts.py::IntentFrame` and `PlanIR`;
- `brain/plan_sketch.py::PlanSketch`;
- trusted compilation in `brain/compiler.py`;
- fail-closed validation in `brain/validator.py`;
- resource, task state, and preemption in `brain/executive.py`;
- semantic dispatch and feedback in `brain/runtime_adapter.py`;
- `ActionProposal`, `ActivityCoordinator`, command TTLs, and generation guards;
- `attention/StimulusBus` and `ReactionArbiter` as pure tested components;
- duplex cancellation and the latency ledger.

Repair these debts:

1. `agent.py::_handle_text()` is a sequential dispatcher. Only explicitly
   deliberative turns enter `_handle_plan`; direct follow, navigation, and
   spatial commands bypass the common task lifecycle.
2. A task-planning turn replaces normal conversation generation. The dog can
   be planning safely or conversing naturally, but not both concurrently.
3. The conversation model still receives physical tool definitions and is
   guarded after generation. It should never receive physical authority.
4. The activity coordinator treats navigation/follow as a whole-body busy
   state. A chuckle or speech acknowledgment should overlap, while a bow,
   stretch, scan, or posture change should acquire the specific tracks it uses.
5. `StimulusBus` and `ReactionArbiter` are unwired; inferred affect currently
   has fragmented paths.
6. Barge-in, spoken stop, task correction, owner summons, and ambient speech
   need distinct semantics.
7. `Vocalize` completion must reflect the audio lifecycle, not merely that text
   was handed to an output function.

## Four lanes

### 1. Deterministic reflex/direct-command lane

Only a reviewed negative-authority subset may react to a partial transcript:

- emergency stop;
- stop/hold;
- cancel current speech;
- optionally slow down.

Partial speech must never initiate positive motion. Once the turn is final, a
deterministic grammar may compile common unambiguous commands—follow, wait,
walk five steps, orbit once, sit, or explicit gesture—into a system-authored
`PlanSketch`. This gets the common task lifecycle without paying LLM latency.
Emergency/stop retains the existing faster cancellation path and then records
the corresponding executive event; it must not wait for plan construction.

### 2. Conversation lane

The conversation model receives personality, dialogue history, a bounded
summary of current task/scene state, and verified task events. It emits no tool
calls:

```text
DialogueActV1 {
  schema_version
  turn_id
  text
  speech_style
  acknowledgement_kind
  claims[]                  # each claim cites verified state or is marked tentative
  social_cues[]
  asks_clarification
}
```

Rules:

- It may acknowledge, explain, laugh, empathize, or ask a question.
- It may say “I'll inspect and find a safe route” once the task is admitted.
- It may not say “I found the sidewalk” before grounded evidence exists or “I
  arrived” before the semantic predicate and physical stop are verified.
- It has no velocity, backend, goal-coordinate, priority, or physical-skill
  schema.
- Barge-in cancels TTS/model output for that speech epoch; it does not change
  an active physical task unless the new utterance has an admitted physical
  intent.

### 3. Task-planning lane

The planner receives:

- the final transcript and `IntentFrame`;
- one immutable observation/world revision;
- the relevant semantic-map subgraph, not an unbounded raw world dump;
- active task, revision, checkpoint, resources, and recent feedback;
- the admitted skill contracts and the `PlanSketch` response schema.

It outputs `PlanSketch`. Trusted code binds task IDs, plan revisions,
resources, priorities, interruptibility, safety invariants, retries, timeouts,
success predicates, and recovery bounds before creating `PlanIR`.

Conversation and task planning start concurrently after final end-of-turn. A
short truthful acknowledgement can be streamed while the task plan is being
computed. On the current 32 GB desktop, use separate logical sessions and GPU
QoS/cancellation rather than loading duplicate large backbones by default:

- voice decode has latency priority;
- planner prefill/decode is interruptible;
- perception has reserved capacity and bounded queues;
- record queue wait, model TTFT, accepted-plan time, VRAM, and deadline misses;
- compare a small distilled intent/planner only after accepted traces exist.

### 4. Social-reaction lane

Models and prosody modules emit evidence, not body commands:

```text
SocialCueV1 {
  cue_id
  source_turn_id
  kind: explicit_affect | joke | greeting | praise | frustration | attention_bid
  modality: transcript | prosody | camera
  evidence_ref
  confidence
  valence / arousal
  observed_at / expires_at
}

ReactionProposalV1 {
  proposal_id
  source_cue_ids[]
  behavior_id
  required_tracks[]
  confidence / urgency
  earliest_start / expires_at
  minimum_dwell / maximum_duration
  interruption_policy
  suppress_if[]
  personality_rule_id
}
```

A deterministic personality policy maps a cue into allowlisted candidates;
`ReactionArbiter` decides whether to execute, overlay, defer, suppress, or
expire. For inferred reactions, optimize precision before recall. Doing
nothing is safer and more natural than a confidently inappropriate full-body
gesture.

Examples:

- “I'm sad” while idle: immediate empathetic speech; optional safe play-bow.
- “I'm sad” during a road crossing: speech may overlap; posture/body reaction
  is suppressed or expires.
- a joke while following: acoustic chuckle may overlap; base motion continues.
- “stretch your leg”: an explicit gesture task, not an inferred reaction.
- low battery: a deterministic system recovery task that reaches a safe pose
  and explains the state; it is not affect inference.
- “look over there”: a real perception task. Since Go2 has no neck, a scan
  owns `base + attention` and runs only at a safe navigation checkpoint.

An affect model such as [emotion2vec](https://github.com/ddlBoJack/emotion2vec)
may be evaluated as one low-stakes evidence producer. It never overrides an
explicit transcript, task state, safety event, or owner preference.

## Resource and interruption policy

Use resource tracks, priority class, checkpoint state, and interrupt policy;
priority alone is insufficient.

Resources expand from the current `base/posture/voice/attention` vocabulary to
make overlap explicit while preserving backward compatibility:

```text
base, posture, voice, attention, perception_scan, expression_audio
```

`expression_audio` may overlap locomotion. A scan on this embodiment maps to
`base + attention + perception_scan`. A full-body bow or stretch maps to
`base + posture`. The compiler, not a model, assigns these claims.

| Event | Base/posture | Voice | Existing task |
| --- | --- | --- | --- |
| hardware safety / E-stop | cancel and stop immediately | interrupt | cancel |
| manual control | preempt immediately | may continue | suspend/cancel by system policy |
| explicit spoken stop | cancel and stop immediately | confirm | cancel |
| barge-in without motion intent | unchanged | interrupt current TTS | continue |
| correction | checkpoint replace unless unsafe to wait | acknowledge | increment revision; stale results rejected |
| owner summons | stop/suspend safely, then approach | respond | save resumable checkpoint |
| ordinary new task | queue/suspend/replace by policy | acknowledge | no model-authored preemption |
| social reaction | never preempt base | audio may overlay | physical part defer/drop |
| low battery | minimum motion to safe state | explain | system recovery owns required tracks |

Additional invariants:

- emergencies/manual safety override every `never` setting;
- controllers report critical phases—road crossing, collision recovery,
  unstable posture—not the language model;
- suspension stores task ID, plan revision, step/checkpoint, scene revision,
  goal, expiry, and resume preconditions;
- resume takes a fresh scene, re-grounds/replans, and never reuses stale
  velocity or waypoints;
- accepted/deferred/rejected/expired are explicit outcomes;
- callbacks carry task/plan/generation IDs and cannot revive old work;
- task completion is verified sensor/controller feedback, not model prose.

## Mission executive and skill behavior trees

Keep `TaskExecutive` as mission-level authority. Use ROS 2 Actions for
long-running skills because they have goal, feedback, result, cancellation, and
preemption semantics. Use small BehaviorTree.CPP/Nav2 trees inside complex
skills rather than replacing the entire executive with one giant tree.

```text
NavigateToSemantic
  GroundTarget
  VerifyFreshEvidence
  SelectGoalRegion
  NavigateAndReplan
  VerifyRelationAndStop
  BoundedRecoveryOrReport

FollowFormation
  VerifyEnrolledOwner
  FollowDynamicGoal
  PreserveVisibilityAndClearance
  AmbiguousStop
  ReacquireOrReport
```

[BehaviorTree.CPP](https://www.behaviortree.dev/docs/guides/asynchronous_nodes/)
requires asynchronous actions to return promptly and support halt. Nav2's
[behavior-tree framework](https://docs.nav2.org/behavior_trees/) is therefore
a good per-skill execution layer. PlanSys2/PDDL remains a later challenger for
large combinatorial tasks; the current bounded companion vocabulary does not
justify replacing PlanIR.

## Behavior-to-perception query seam

Skills request evidence through a broker rather than instantiating detectors:

```text
SceneQueryV1 {
  query_id / task_id / plan_revision
  terms[]
  requested_relation
  freshness_required_ms
  minimum_confidence
  search_budget_s
  allow_cached / allow_active_scan
}

SkillFeedbackV1 {
  task_id / plan_revision / step_id
  status
  checkpoint / critical_phase
  progress
  verified_facts[]
  evidence_refs[]
  blocking_reason
  scene_revision
}
```

The broker supplies existing memory evidence immediately when allowed, runs
fast closed-set detectors continuously, and schedules expensive open-vocabulary
or OCR work on demand. Skills see the same typed result regardless of detector
choice. Multi-frame confirmation and metric uncertainty are required before a
semantic result becomes a navigation goal.

## Implementation cards

### B0 — contracts, traceability, and replay

Deliver:

- `DialogueActV1`, `SocialCueV1`, `ReactionProposalV1`, `SceneQueryV1`, and
  `SkillFeedbackV1` with exact-field parsing, bounds, timestamps, TTLs, and
  provenance;
- one event/correlation ID chain from audio/text through dialogue, plan,
  executive, skill, command, feedback, and spoken/visible result;
- deterministic voice/perception/executive event replay;
- baseline cases recorded before refactor.

Gate: every physical action names one admitted user/system event and task
revision; every stale/invalid event fails closed.

### B1 — split the monolith

Primary files: `agent.py`, `voice_pipeline.py`, `brain/router.py`,
`brain/compiler.py`, provider adapters, and `runtime.py`.

Deliver:

- distinct router, conversation, and planner services;
- remove physical tools from conversation schemas;
- compile unambiguous final commands into local `PlanSketch`/`PlanIR`;
- concurrent truthful acknowledgement and planning;
- cancellation tokens, bounded queues, and GPU service priority;
- explicit separation of TTS barge-in and task interruption.

Gate: zero model-authored raw controls; schema-invalid plans never dispatch;
conversation remains responsive when the planner is slow or unavailable;
barge-in without physical intent never changes motion.

### B2 — finish arbitration and resume

Primary files: `attention/*`, `core/activities.py`, `brain/executive.py`,
`brain/runtime_adapter.py`, `runtime_channels.py`, `core/resume.py`, and
`runtime.py`.

Deliver:

- wire `StimulusBus` ADD/REVOKE/COMMIT lifecycle and `ReactionArbiter`;
- replace coarse busy gating with per-track leases;
- controller-authored checkpoints and critical phases;
- full navigation/follow/search pause/resume consumption with fresh replanning;
- audio sink onset/completion/cancel evidence for `Vocalize`;
- personality policy as bounded parameters over allowed reactions, never
  safety/priority changes.

Gate: emergency/manual preemption always wins; false social preemption of the
base is zero; stale callbacks cannot restart a task; pause/resume scenarios
pass across scene changes and expired goals.

### B3 — behavior quality hillclimb

Deliver:

- held-out direct/compound/correction/negation/ambiguity command suite;
- reaction appropriateness corpus with multiple personalities and explicit
  owner preferences;
- affordance/feasibility score per skill and closed-loop feedback/replanning;
- planner/provider registry with paired comparisons;
- optional distilled small intent/planner candidate trained only after
  accepted/verified traces exist.

Gate: statistically significant task/reaction gain on held-out cases with no
collision, false-action, identity, stop, latency, or verified-success
regression.

## Evaluation cases

### Direct and deliberative intent

- “walk five steps away from me,” “circle me once,” “follow behind me,” and
  “wait here” compile locally;
- “go to the sidewalk and wait near the blue storefront” uses the planner;
- “don't walk to the street,” a hypothetical, and an information question
  never cause positive motion;
- malformed/unsupported/stale plans produce a useful clarification or honest
  failure;
- “no, the other lamppost” increments task revision and rejects old feedback.

### Interaction under task load

- joke while following: chuckle begins without changing formation;
- sadness while crossing: empathetic audio only;
- stop while planner is decoding: zero command wins and late plan cannot commit;
- barge-in while navigating: TTS stops, navigation continues;
- summons during navigation: safe suspension, approach owner, fresh-scene
  re-ground and resume;
- low battery during ordinary travel versus during a critical crossing;
- reaction proposal expires instead of firing unnaturally long after the cue.

### Metrics

- intent-route accuracy and schema-valid/admitted plan rate;
- unsafe admission and false physical-action count, target zero;
- verified-success precision and truthful-acknowledgement rate;
- task completion, recovery, replan, and stale-result rejection;
- social cue/reaction precision, inappropriate-action rate, defer/drop/expiry,
  and owner preference;
- task-interruption and resume correctness;
- query-end to first acknowledgement/reasoning/plan/audio/physical feedback;
- queue wait, cancellation latency, p50/p95/p99, GPU/VRAM, and deadline misses.

## Provisional latency gates

These are design targets, not current measurements:

| Path | Target |
| --- | ---: |
| audio chunk -> streaming ASR availability | P95 <= 100 ms |
| emergency phrase end -> issued zero command | P99 <= 100 ms |
| final text -> deterministic route | P95 <= 10 ms |
| query end -> first acknowledgement text | P50 <= 150 ms; P95 <= 300 ms |
| query end -> first audible response | P50 <= 350 ms; P95 <= 700 ms |
| query end -> first valid PlanSketch | P50 <= 300 ms; P95 <= 700 ms |
| query end -> admitted plan | P50 <= 400 ms; P95 <= 900 ms |
| admitted plan -> first skill dispatch | P95 <= 100 ms |
| nonblocking cue -> audible/visible onset | P95 <= 500 ms |
| confirmed physical emergency stop | P99 <= 300 ms, measured on hardware |

Keep the user's existing headline metrics:
`UserQueryEndToFirstResponse` and
`UserQueryEndToFirstReasoningResponse`. Add query-end-to-router,
first-valid-plan, admitted-plan, first-skill-dispatch, first-issued-command,
first-controller-feedback, first-visible-motion, first-audio-sink-onset,
interruption-complete, resume-admitted, and event-to-reaction-onset. Preserve
failed, cancelled, deferred, and superseded traces; otherwise tail latency and
unsafe late work disappear from the dashboard.
