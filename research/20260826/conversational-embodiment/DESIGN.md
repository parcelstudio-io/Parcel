# Conversational embodiment: capability closure, dialogue state, initiative, and routing

Date: 2026-08-26
Status: pre-registered before the first execution of `experiment.py`
Target: Unitree Go2 EDU+ with a proposed Jetson AGX Orin 64 GB companion-compute module
Evidence tier: repository audit plus deterministic authored desktop replay

Post-registration worktree note: another concurrent task introduced
`si-companion-v4` and companion-relationship wording before this experiment was
executed. The machine result therefore audits v4 worktree bytes (and records
their SHA-256), although the initial audit below refers to the v3 state that was
present when this design was drafted. This study did not author or edit that
product change. No hypothesis, fixture, threshold, or research policy was
changed in response.

## Decision this work can and cannot support

This study asks whether four *software architecture* changes are worth building:

1. close every conversational body proposal over the robot's effective runtime
   capability surface;
2. put action receipts, conversational referents, and temporal owner facts in a
   deterministic state graph around the language model;
3. admit proactive speech locally through a typed, fail-closed policy; and
4. route closed/safety acts locally, ordinary dialogue to realtime voice, and
   slow novel reasoning to a separate deliberative tier.

The experiment has no microphone, speaker, hosted model, simulator, Orin, or
robot. It cannot establish language understanding, owner preference, spoken
latency, acoustic robustness, motion quality, sim-to-real transfer, or physical
mount readiness. Fixture labels and all natural-language semantic frames are
authored by this researcher. The proposed policies are authored heuristics, not
learned-model evidence.

## Audit of the current architecture

### Prompt and capability plane

The hosted realtime SI is versioned and digest-pinned in
`src/parcel_robot/realtime/prompting.py`. Its preamble already calls the robot a
"conversational companion quadruped friend" and its v3 cadence correctly says
to call a tool first, wait for the result, and speak once about the result. The
DI contains location, time, owner, owner notes, a six-line history digest, and a
session-open scene snapshot. It does **not** carry a typed body-state,
initiative, identity-confidence, or action-receipt envelope.

`build_tool_specs` does expose a strong session-time capability hint: actual
gesture and pose names are inlined as JSON-schema enums. The broker then
validates the call locally, blocks system-initiated travel, and distinguishes
`started` from terminal completion. These are good authority boundaries.

There is nevertheless a concrete closure defect before model inference. The
three live personality YAML files contain nine affect-action mappings. The
effective `go2_edu_plus` profile inherits only nine runtime emotes from
`configs/robot.yaml`. Static inspection found that eight of the nine personality
mappings name gestures outside that emote surface. The experiment re-derives
this result from `ConfigStore`, `PromptLibrary`, and `build_tool_specs`; it does
not hard-code the count.

There is also a split prompt architecture. The local dynamic prompt builder has
an `EmotePolicySource` that enumerates admissible emotes, while the hosted
realtime prompt uses tool schemas plus prose. Capability names are therefore
represented in more than one plane and can drift from personality preferences.

### Skills and execution plane

The skill catalog/registry/executor is deterministic and typed, and the
effective agent config separately allowlists semantic brain skills and gesture
emotes. `ConfigStore.poses()` merges catalog poses into the runtime pose map;
the realtime broker then converts model proposals into the same typed/safety
doors rather than exposing raw control. That is the right layering. The missing
link is cross-plane validation: `PromptLibrary` validates affect-action names
syntactically, but does not require them to exist in the effective skill/emote
catalog. A name can therefore be trusted prompt data while still not being an
installed skill. H1 makes that closure explicit at session/boot time.

### Conversation, action, and memory state

The repository has three-tier memory snapshots, turn/provenance identifiers,
owner-fact policy, recent tool-result prompt sources, and broker receipts.
However, the language model still sees a small history tail/digest and natural
language result messages. The DI schema has no explicit pending referent,
pending action, terminal receipt, correction/cancel state, or versioned temporal
fact view. The QEV evidence identifies the resulting observable failures:
premature completion claims, unsupported monitoring/perception claims, memory
confabulation, and poor personal-conversation performance.

### Realtime and turn-taking

The realtime lane is stateful, supports interruptions and tool-result turns,
and intentionally avoids mid-session instruction rewrites that would disturb
prompt caching. The frozen acoustic suite is still red on endpointing,
barge-in-to-stop, acknowledgement latency, and prosody. Consequently the
desktop TTFT numbers cannot be treated as spoken latency.

### Initiative

The 2026-08-24 conversation-opportunity study provides a useful architecture:
continuous local sensing -> deterministic admission -> hosted phrasing. Its
authored replay scored perfectly, but post-registered probes showed two exact
product blockers: a false owner assertion admitted 14/17 affected cases, and a
permissive dictionary contract admitted 9/9 malformed candidates. This study
tests a typed replacement contract; it does not retune the social threshold or
claim that people want the interruptions.

### Yesterday's quality evidence and Claude scope

The committed QEV report is the available evidence for yesterday's work. It
reports:

- 10/10 parse success but only 2/10 machine-pass on the live pinned local-model
  set, with capability safety 0.20;
- 3/13 passing personal-conversation turns and one of eight passing families;
- 6 PASS / 8 MIXED / 11 FAIL semantic-review threads (43/76 expectations);
- 5/9 passing virtual-acoustic gates; and
- no physical observation/actuation, Orin, independent STOP, stopping-envelope,
  or mounted-audio evidence.

The referenced Claude artifact could not be retrieved as reviewable content
from this environment: the public URL rendered a not-found shell and its frame
endpoint was not accessible. No claim below is attributed to that unavailable
artifact. Only committed repository evidence is audited.

## Research synthesis and design translation

Primary-source claims and exact URLs/versions are recorded in `SOURCES.json`.
The design implications are deliberately narrower than the papers' claims:

- SayCan grounds high-level language against available skills and learned
  affordance values. Here that becomes an exact capability enum plus local
  body/affordance admission; a prompt is never motion authority.
- Inner Monologue shows the value of closed-loop environment feedback. Here the
  only admissible feedback is a typed start/reject/terminal receipt and
  time-stamped state, not a free-form self-narrated success claim.
- LongMemEval separates extraction, multi-session reasoning, temporal
  reasoning, update, and abstention. Here owner facts are source-bearing,
  versioned records and no-match/revoked queries must abstain.
- Dialogue-state-graph research suggests deterministic state control can improve
  robustness in incomplete and ambiguous situations. Here the graph owns
  pending/completed action state, correction, and "again" resolution.
- Recent proactive-HRI studies argue against treating interaction count as the
  goal. One group study found that proactivity increased interaction while its
  effects varied with experience/personality and the reactive arm had a
  descriptively higher task-success rate. ProVox first elicits partner
  preferences before proactive planning, while PACT scores the utility of asking
  instead of acting under incomplete cross-day context. Here those findings
  become explicit initiative consent, interruption/privacy gates, an `ask`
  outcome, and owner-specific evaluation of helpfulness versus burden.
- RouteLLM demonstrates that routing can lower cost at matched benchmark
  quality in general LLM settings. It does **not** validate this robot router;
  it motivates measuring route recall, invariant coverage, and cost separately.
- OpenAI's official voice guidance recommends the live audio path for natural
  turn taking, interruption, and low first-audio latency. Realtime conversation
  costs grow with repeated context, while stable prefixes can be cached. Here
  ordinary open dialogue stays on the realtime lane, capability schemas stay
  stable for a session, and fast local acts do not pay for an LLM response.
- A 2025 Unitree social-gesture paper reports strong simulation success but only
  limited physical validation and explicit balance/compliance transfer issues.
  Thus a gesture that exists in simulation is not added to the conversational
  capability envelope until its runtime adapter and physical commissioning
  evidence exist.
- NVIDIA's published AGX Orin results establish useful edge capacity, but an
  older MLPerf GPT-J 6B single-stream result is about 10.2 seconds. Memory size
  and TOPS alone therefore do not justify putting open-ended first-response
  dialogue on-device. Measure candidate models on the exact Orin power mode,
  quantization, audio load, and prompt before changing the route.

## Proposed architecture

```text
audio / app / world event
          |
          v
 local semantic frame + provenance
          |
          +--> emergency / closed act --> deterministic local response
          |
          +--> OpportunityCandidateV1 --> local initiative gate --> phrase or drop
          |
          +--> EmbodimentEnvelopeV1 --> local action admission --> runtime tool
          |                                                   |
          |                                              typed receipt
          |                                                   |
          +--> DialogueStateV1 <-------------------------------+
                   |
                   +--> ordinary open turn --> realtime voice
                   +--> novel long plan/memory --> deliberative text tier
```

The model may propose words and one semantic action. The envelope and runtime
remain the only motion authorities. `DialogueStateV1` is a compact read model,
not a second actuator: it stores the active referent, last completed action,
pending action receipt, corrections, and provenance-bearing owner facts.

### Prompt proposal (not applied by this study)

The initial audit recommended that the next SI version add this intent, with
exact wording owner-reviewed and then digest-pinned. Concurrent work introduced
v4 with closely aligned relationship language before experiment execution; the
remaining proposal below is retained as the pre-registered research target and
must not be read as a claim that this study edited product code:

> You are Parcel, the owner's companion friend by default: warm, reliable, and
> available across turns. Staying with them means being easy to find and
> remembering what matters, not shadowing, monitoring, interrupting, or
> following without permission. Respect quiet, privacy, personal space, and a
> request to be left alone. Support with natural words first. Body language may
> accompany the conversation only when the current capability tool names that
> exact action and the local gate permits it. Never invent or substitute a
> gesture. Treat emotion cues as tentative. A system or proactive event never
> authorizes travel; approaching, following, searching for, or leaving with the
> owner requires their explicit request plus local identity and navigation
> admission. Say an action started only after its tool accepts it, and say it
> finished only after a matching terminal receipt.

Do not rewrite session instructions every sensor tick. Keep persona, tool
schemas, and session capability enums in a stable cached prefix. Send compact,
versioned state changes as conversation/tool events, and continue enforcing the
same fields in the local broker even if the model ignores them.

Recommended envelope fields:

- schema version and monotonic snapshot time;
- exact tool, gesture, and pose enums plus capability-manifest digest;
- body mode, current/pending action ID, terminal receipt ID, and busy reason;
- locomotion commissioned/healthy, E-stop, navigation affordance and space;
- response initiator (`owner` or `system`), verified-owner confidence, and
  explicit motion/proactive-speech consent; and
- dialogue referent plus fact/query provenance IDs, never raw unrestricted
  database history.

## Falsifiable hypotheses

### H1 — capability-closed embodiment

On the authored embodied-intent set, a typed envelope built from the effective
Go2 profile and realtime tool schemas will produce:

- zero executed unavailable actions;
- zero executions for hypothetical, negated, quoted, unsafe-affordance, or
  system-initiated travel cases;
- at least 0.90 recall on safe explicit actions; and
- at least 0.90 exact decision/action accuracy.

Comparison: a deliberately simple `persona_only_proxy` that executes the
authored candidate name without availability or state admission. It is **not**
claimed to reproduce the current model.

### H2 — receipt- and time-aware dialogue state

On authored multi-turn state snapshots spanning repetition, started versus
terminal receipts, correction, stale receipts, temporal updates, provenance,
revocation, and abstention, the state graph will achieve at least 0.90 exact
outputs, zero false completion, and zero unsupported memory answers.

Comparison: a deliberately simple `tail_only_proxy` that treats the last
proposal as completed and returns the first matching fact. It is not the
repository's full memory implementation or a model benchmark.

### H3 — typed proactive admission

On a new authored initiative set and automatically generated malformed-input
refuters, a strict `OpportunityCandidateV1` validator plus local gate will:

- admit zero prohibited or malformed candidates;
- reach at least 0.80 precision and 0.80 recall on useful valid candidates;
- reject every missing-field, wrong-type, non-finite, unknown-field, and
  unknown-version mutation; and
- remain deterministic across ten semantic replays.

Comparison: a permissive-default proxy included solely to reproduce the class
of contract flaw found on 2026-08-24.

### H4 — risk-first edge/cloud routing

On an authored workload of closed/safety acts, ordinary dialogue, and novel
reasoning requests, a deterministic router will:

- route 100% of safety-critical cases through a local gate;
- reach at least 0.90 exact route accuracy;
- reduce hosted generations by at least 40% versus always-realtime while
  preserving all gold hosted dialogue/reasoning routes; and
- report, without treating it as measured spend, a monthly price projection at
  12,000 proportional turns using the accessed 2026-08-26 GPT-Realtime-2 list
  rates and explicit audio-token assumptions.

Local decision latency is microbenchmarked on this desktop for >=100,000
decisions with a p95 bar of 1 ms. This is only Python policy latency; it excludes
ASR, semantic parsing, TTS, network, provider generation, and motor response.

## Fixture and scoring protocol

`fixtures.json` is frozen authored data. Natural-language utterances are for
readability; the experiment consumes their authored semantic frames. Therefore
no score measures NLU or model response quality.

The script imports current repository components to derive:

- the effective `go2_edu_plus` configuration;
- live personality affect maps;
- the actual `play_gesture` and `set_pose` enums; and
- the current realtime tool names.

All exact comparisons are case-insensitive only where the fixture says so; no
cases are removed after execution. Semantic determinism hashes exclude clock
timings and machine metadata. Price projection assumptions are machine-readable
in the result and do not use a key or call an API.

## Immediate implementation sequence if hypotheses pass

1. Add a boot-time closure check that rejects or explicitly drops every
   personality affect action absent from the effective gesture enum. Generate
   all model-facing action hints from the same manifest.
2. Introduce `EmbodimentEnvelopeV1` and `DialogueStateV1` read models; retain the
   broker/supervisor as final authority. Feed tool terminal events back by
   action ID and make unmatched terminals stale rather than conversational fact.
3. Implement `OpportunityCandidateV1` validation before any initiative score;
   leave proactive speech default-off until owner identity, consent, and mounted
   interruption evidence pass.
4. Keep stop/hold/backchannel/closed acknowledgements local; use realtime voice
   for open companionship; call the deliberative tier only as a bounded tool.
5. Build a separate recorded eval with actual model outputs, through-air audio,
   owner/non-owner speech, and blinded human preference labels. Only those data
   can tune personality, non-clinginess, and perceived fluidity.
