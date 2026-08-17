# Voice-agent evaluation, selection, and replaceable provider architecture

**Evidence date:** 2026-08-16  
**Scope:** conversational voice for the Parcel robot dog; research and target
design, not a claim that a cloud provider is wired or commissioned.

This document answers three separate questions:

1. which current voice systems look strongest in public evidence;
2. what they are likely to cost; and
3. how Parcel can trial or replace any of them without moving motion authority,
   conversation history, or product identity into a vendor SDK.

The short answer is deliberately not “pick the top leaderboard row.” The current
public aggregate leader is Qwen Audio 3.0 Realtime Plus, but its documented
deployment is mainland China. Grok Voice Think Fast 2.0 High is the strongest
globally interesting challenger in the same external table, but the public xAI API
exposes a moving `grok-voice-latest` alias rather than the exact benchmark name.
GPT-Realtime-2.1 is the most defensible **first managed adapter** for Parcel because
it combines strong measured duplex and task performance with a named public model,
function calling, and a mature realtime protocol. It is also materially more
expensive than Gemini Live.

Therefore:

- keep Parcel's local, typed STT -> brain -> TTS cascade as the rollback/control
  baseline for the first ODD;
- implement GPT-Realtime-2.1 first as an opt-in, conversation-only managed adapter;
- run Grok Voice and Gemini Live as the capability and cost challengers on exactly
  the same captured turns;
- keep Qwen Audio 3.0 Plus as a research challenger until region, latency, privacy,
  and procurement are acceptable for this US deployment;
- evaluate Hume EVI for emotional expression, and Fish/Deepgram/ElevenLabs as
  modular or managed-pipeline alternatives, not as already proven reasoning
  leaders; and
- make no provider the physical-command principal. Every provider output remains an
  untrusted proposal behind `CommittedTurnV1`, `CommandAuthorityV1`, task admission,
  and the local safety/gateway path.

No candidate is promoted by this research. The winner is the first exact
endpoint/configuration to pass the hard gates and robot-specific bake-off below.

## 1. What the public evidence really measures

### 1.1 Evidence hierarchy

| Evidence | What it contributes | What it cannot establish |
| --- | --- | --- |
| Parcel paired chassis/audio evaluation | Exact owner, microphone, speaker, body noise, tools, authority, network, and cost | A broader vendor SLA or new ODD |
| Independent reproducible benchmark on the exact API/model | Strong shortlist prior | Parcel acoustics, local safety, privacy policy, or replacement behavior |
| Peer-reviewed/open benchmark on an older model family | Failure modes and reusable cases | Current-version ranking |
| Disclosed vendor study | Useful hypothesis about a specialty such as empathy | An independent comparison or product acceptance |
| Consumer/app review | Perceived experience in one app | API model identity, prompt, tools, latency path, cost, or reproducibility |

Consumer reviews of ChatGPT Voice, Gemini Live, and other apps are especially easy
to misread: the app may add memory, search, endpointing, moderation, and UI behavior
that the developer API does not provide. They are useful for discovering test cases,
but they do not receive score weight here.

### 1.2 Best current cross-provider screen

The independent commercial [Artificial Analysis Speech-to-Speech
Index](https://artificialanalysis.ai/speech-to-speech) equally weights speech
reasoning, a subset of Full-Duplex-Bench, and grounded task completion from
tau-Voice. Its [methodology](https://artificialanalysis.ai/methodology/speech-to-speech-benchmarking)
uses 1,000 audio reasoning questions, pause/turn/interruption/backchannel cases, and
278 airline/retail/telecom tasks. These are useful priors, not Parcel scores.

| Exact evaluated configuration | Index | Reasoning | Conversational dynamics | Agentic pass@1 | TTFA | Benchmark cost / input-audio hour |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen Audio 3.0 Realtime Plus | **84.1%** | 99% | **98.4%** | 54.6% | 1.54 s | $4.42 |
| Grok Voice Think Fast 2.0 High | 82.9% | 97% | 95.1% | **56.5%** | **0.70 s** | $4.80 |
| GPT-Realtime-2.1 High | 79.1% | 96% | 95.7% | 45.7% | 1.21 s | $10.75 |
| Gemini 3.1 Flash Live Preview High | 69.5% | 97% | 74.3% | 37.7% | 2.99 s | $1.75 |

Important qualifications:

- the index is an equal-weight composite chosen by Artificial Analysis, not by
  Parcel;
- the GPT-Realtime-2.1 task score is currently based on two trials, not three;
- TTFA is measured on audio reasoning questions, not after robot endpointing, a
  tool call, playback buffering, or motion noise;
- “cost per input-audio hour” includes the benchmark's input, output, text, and
  reasoning usage, but excludes cached discounts and tool-call fees; and
- managed services change without weight releases, so the exact model ID, reasoning
  effort, region, voice, prompt, codec, and run date must accompany every score.

### 1.3 Benchmarks worth importing into Parcel

| Benchmark | Useful dimensions | Main limitation for this decision |
| --- | --- | --- |
| [Full-Duplex-Bench v1/v1.5/v3](https://github.com/DanielLin94144/Full-Duplex-Bench) | pause handling, turn taking, interruption, backchannels, real disfluency, chained tools | Versions and model configurations differ; early sets are static/synthetic |
| [tau-Voice](https://arxiv.org/abs/2603.13686) | 278 grounded multi-turn tasks with tools, noise, accents, and interruptions | Customer-service domains, not an embodied companion |
| [EVA-Bench](https://github.com/ServiceNow/eva) | task completion, speech fidelity, faithfulness, progression, concision, turn taking, latency, repeated trials | Automated bot-to-bot simulation; judges and enterprise workflows are not owner preference |
| [SID-Bench](https://github.com/xkx-hub/SID-bench) | real human interruption intent, false interruption rate, interruption latency, average penalty time, noise | Interruption detector evaluation, not a full agent |
| [VocalBench](https://github.com/SJTU-OmniAgent/VocalBench) | knowledge, reasoning, acoustic quality, instruction following, empathy, safety, robustness | Several LLM-as-judge metrics and incomplete current managed-API coverage |
| [CAVA](https://talkarena.org/cava) | turn taking, instruction following, function calling, tone awareness, safety, latency | Initial results use 2025-era models; use the task design, not its ranking |
| [RW-Voice-EQ](https://arxiv.org/abs/2607.14846) | naturalness, expressiveness, identity stability, reliability, affect, accents/noise | Hume-authored; valuable rubric, not independent vendor selection |

The most useful direct-study results add texture that an aggregate hides:

- [Full-Duplex-Bench v3](https://arxiv.org/html/2604.04847v1) used 100 real-
  human recordings from 12 speakers. The older GPT-Realtime-1.5 configuration
  reached tool F1 0.876, argument accuracy 0.680, pass@1 0.600, and 96% turn
  taking. Gemini 3.1 reached 0.817, 0.588, 0.540, and only 78%, respectively;
  it was silent on 22 of 100 cases even though most silent cases still invoked a
  tool. Those are valuable failure modes, but the GPT numbers must not be relabeled
  as GPT-Realtime-2.1 results.
- [EVA-Bench](https://arxiv.org/html/2605.13841) ran 213 enterprise scenarios with
  five clean trials. Gemini 3.1 Flash Live scored EVA-A 0.292 +/- 0.048 and EVA-X
  0.589 +/- 0.035: good measured experience with much weaker strict task accuracy.
  GPT-Realtime-1.5 scored 0.467 +/- 0.052 and 0.566 +/- 0.039. An exact
  ElevenAgents configuration scored pass@1 0.490 but pass^5 only 0.269, showing why
  a best-of-five demo is not repeatable reliability.
- NVIDIA's [PersonaPlex paper](https://arxiv.org/html/2602.06053) reports strong
  human-rated full-duplex behavior for its research system, but the released
  checkpoint scores lower and the paper leaves external tool integration as future
  work. Artificial Analysis likewise reports 91.0 conversational dynamics but only
  19 reasoning for PersonaPlex.
- Hume's [EVI 3 comparison](https://www.hume.ai/blog/introducing-evi-3) is a blind
  vendor study that favors EVI on empathy, expressiveness, naturalness,
  interruption, speed, and audio quality, but it publishes no participant count,
  raw score table, uncertainty, or full tool/task benchmark. It justifies an
  expression trial, not an autonomy ranking.
- Fish S2 has credible output-quality evidence in RW-Voice-EQ, including strong
  identity and language stability, while Fish's own hosted-agent test framework
  still describes multi-turn tests as forthcoming. Treat its TTS evidence as TTS
  evidence.

Two findings should set expectations. In the original tau-Voice study, voice agents
completed only 31-51% of clean tasks and 26-38% of realistic tasks, versus 85% for
the text reasoning baseline. Full-Duplex-Bench v3 likewise reports self-correction
and hard multi-step reasoning as persistent failures. A fluent demo is not evidence
of dependable task completion.

Paralinguistic access is not yet dependable authority either. The independent
[“Real-Time Voice AI Hears but Does Not Listen”](https://arxiv.org/abs/2606.26083)
study found that GPT Realtime 2, Gemini 3.1 Live, and two Qwen realtime systems often
detected fear, distress, or sarcasm when explicitly asked, but still acted mainly on
the words when vocal delivery conflicted with them. Parcel may use tone as a social
cue; it must not use inferred emotion as identity, consent, emergency, or motion
authority.

## 2. Candidate review for this robot

| Candidate | Capability reading | Integration / replacement reading | Recommended role |
| --- | --- | --- | --- |
| **GPT-Realtime-2.1** | Strong current index, duplex behavior, configurable reasoning, and tool use. Official model page reports improved noise, silence, alphanumeric, and interruption behavior. | Named model and WebRTC/WebSocket protocols are favorable; token/context billing and provider-specific events still require an adapter. | First managed adapter and provisional quality ceiling; opt-in conversation only until Parcel gates pass. |
| **Grok Voice** | Highest globally interesting result in the current index and fastest of the four rows above. | Official API starts at $0.05/min and supports realtime tools, but documents `grok-voice-latest`; equivalence to the benchmark's Think Fast 2.0 High configuration must be demonstrated. | Capability challenger; never compare an unpinned moving alias as if it were the benchmark row. |
| **Gemini Live** | Strong audio reasoning and low cost, but the evaluated High configuration trails on conversational dynamics and grounded tasks. | Native Live API and function calling are usable; current selected model is a preview and must be fenced by capability/version checks. | Cost challenger and failover experiment. |
| **Qwen Audio 3.0 Realtime Plus** | Current index leader, including the strongest conversational-dynamics score. | Official realtime service/pricing currently documents mainland-China deployment, creating region, latency, governance, and procurement questions for this robot. | Research challenger only until those questions are closed. |
| **Hume EVI** | Purpose-built expressive/empathic speech and strong vendor-reported human preference evidence. No comparable current composite score establishes superior tool/task reasoning. | Managed session can use Hume's or a custom language model; per-minute pricing is simple, but emotional state/events are vendor-specific. | Expression/persona challenger behind local task authority. |
| **Deepgram Voice Agent** | Integrated STT, orchestration, LLM, and TTS with operationally clear tiers; not represented as a native-S2S leader in the current index. | BYO LLM/TTS options reduce lock-in. Connected-minute billing is predictable. | Managed-cascade operational baseline. |
| **ElevenAgents** | Strong voice catalog and managed conversation stack; public evidence is stronger for voice quality than robot task reliability. | BYO/custom components are possible, but connection billing, proprietary orchestration, and stored session data need explicit policy. | Managed UX/voice challenger. |
| **Fish core APIs** | Competitive modular TTS and inexpensive ASR. The compatibility realtime socket is STT+TTS, not a native conversational brain. | Good replaceable components; explicit cancel exists in the beta OpenAI-compatible socket. Parcel's current `FishSpeechProvider` is instead the local Fish Speech service. | TTS/ASR component baseline, not the motion or dialogue authority. |
| **Fish Agents** | Hosted full-duplex orchestration with ASR, turn taking, TTS, LiveKit sessions, transcripts, and barge-in. No independent current end-to-end score or public agent tariff was found. | Managed LiveKit wire protocol; JS/React is the documented SDK path. | Exploratory only until price, native client, data, and benchmark evidence are known. |
| **PersonaPlex** | Interesting self-hosted full-duplex model and privacy option; its paper leaves external tools as future work. | No API fee, but GPU sizing, HA, tool integration, and production SLA become Parcel's problem. | Offline/privacy research track. |
| **Sesame** | Consumer preview demonstrates natural conversation; released CSM-1B is contextual speech generation, not a complete duplex agent. | No public production API, SDK, tariff, or SLA. | Not an integration candidate. |

The strongest voice and the strongest task brain need not be the same service. Parcel
should be able to use a managed native conversation model, a managed cascade, or a
local STT/LLM/TTS pipeline without changing the downstream authority contracts.

## 3. Pricing normalized for Parcel

Pricing changes quickly. The calculations below use public rates checked on
2026-08-16 and deliberately exclude tax, cellular service, relay/egress, search and
tool calls, vector stores, HA, support, and engineering.

### 3.1 Usage profiles

- **Low:** 30 connected minutes/day x 22 days = 660 min/month.
- **Medium:** 2 connected hours/day x 26 days = 3,120 min/month (52 h).
- **Heavy:** 8 connected hours/day x 30 days = 14,400 min/month (240 h).

For token-priced raw-audio floors, the reference active hour contains 21 minutes of
owner speech, 18 minutes of robot speech, and 21 minutes of silence/tool time. It
does not include replayed context, reasoning/text tokens, transcription, or tools.

### 3.2 Comparable cost signals

| Service / configuration | Public billing basis | Useful normalized signal | Medium-month screen |
| --- | --- | ---: | ---: |
| GPT-Realtime-2.1 | audio $32/M input and $64/M output tokens; text/reasoning extra | about **$1.79/h raw-new-audio floor** for the reference mix; **$10.75/h** on the Artificial Analysis workload | about $93 floor to $559 benchmark-workload projection |
| GPT-Realtime-2.1 Mini | audio $10/M input and $20/M output tokens | about **$0.56/h raw-new-audio floor**; external quality index is materially lower than full 2.1 | about $29 floor, plus context/text/tools |
| Gemini 3.1 Live | audio equivalent to about $0.005 input minute and $0.018 output minute | about **$0.43/h raw-new-audio floor**; **$1.75/h** for evaluated High config on the external workload | about $22 floor to $91 benchmark-workload projection |
| Qwen Audio 3.0 Plus | token priced; official service currently mainland China | **$4.42/h** external benchmark workload | about $230, before region/network implications |
| Grok Voice | realtime **starting at $0.05 connected minute** | $3/h starting rate; evaluated High configuration measured at $4.80/h externally | $156 starting rate |
| Fish core ASR + S2 TTS | $0.36/audio hour ASR + $15/M UTF-8 TTS bytes | roughly **$0.37-$0.60/h** for this speech mix, audio components only | about $19-$31 **plus** brain, media, and orchestration |
| Deepgram Custom BYO LLM | $0.059 connected minute | $3.54/h plus the external brain | about $184 plus brain |
| Hume EVI | tiered plans, effectively $0.04-$0.06 overage minute | chosen public tier: $185.20 at medium use | $185.20 plus external/custom brain where used |
| ElevenAgents | about $0.08 connected minute on recurring plans; LLM extra | $4.80/h plus LLM | about $249.56 plus LLM |
| Fish Agents / Sesame | no public production tariff found | **unknown** | not estimable |

For the platforms with connected-minute or tier schedules, the same assumptions
produce this voice-service-only monthly view:

| Service | Low: 660 min | Medium: 3,120 min | Heavy: 14,400 min |
| --- | ---: | ---: | ---: |
| Grok Voice, documented starting rate | $33.00 | $156.00 | $720.00 |
| Deepgram Custom BYO LLM | $38.94 | $184.08 | $849.60 |
| Hume EVI, cheapest applicable public tier | $70.00 | $185.20 | $576.00 |
| ElevenAgents, cheapest applicable recurring tier | $52.80 | $249.56 | $1,151.96 |

“BYO/custom brain” is not free. As a transparent sensitivity—not a vendor quote—
1,500 input plus 300 output tokens per connected minute on Gemini 3.5 Flash at the
current public rates adds about $0.00495/minute, or $3.27/$15.44/$71.28 to those
three profiles. A different prompt, tool loop, context policy, or model can dominate
that number.

Official sources: [OpenAI model/pricing](https://developers.openai.com/api/docs/models/gpt-realtime-2.1),
[OpenAI realtime cost mechanics](https://developers.openai.com/api/docs/guides/realtime-costs),
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Qwen pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing),
[xAI Voice](https://docs.x.ai/developers/model-capabilities/audio/voice),
[Fish pricing](https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits),
[Deepgram pricing](https://deepgram.com/pricing),
[Hume pricing](https://www.hume.ai/pricing), and
[ElevenAgents pricing](https://elevenlabs.io/pricing/agents).

The raw OpenAI/Gemini floor is intentionally paired with an observed external
workload number. Realtime APIs resend or retain growing conversation context, use
reasoning/text tokens, and may separately bill transcription and tools; multiplying
only fresh audio by a token rate systematically understates a real conversation.
The correct production metric is **total invoice divided by successful committed
turns and successful tasks**, with provider/model/region attached.

## 4. Parcel-specific acceptance benchmark

### 4.1 Hard gates: a weighted score cannot compensate for failure

1. A provider cannot write a robot command, mint `CommandAuthorityV1`, or report a
   physical task complete. Tool calls are proposals; deterministic local code owns
   admission and `TerminalWitnessV2`.
2. Partial transcripts, model audio, inferred emotion, read-only tool text, and
   untrusted speakers never authorize positive motion.
3. Local emergency and physical stop paths work while the provider, LLM, network,
   logger, and UI are unavailable. Barge-in stops speech; it does not silently
   mutate a task.
4. Cancel, timeout, disconnect, fallback, and reconnect emit one terminal event;
   late/duplicate/reordered audio and tool proposals cannot replay speech or action.
5. No unsafe/unauthorized tool call, fabricated tool success, stale command,
   duplicate action, or cross-session memory leak occurs in the preregistered suite.
6. Retention, recording default, deletion/export, credential handling, residency,
   redaction, and the audit of what was actually heard satisfy the owner-approved
   B18 policy.

### 4.2 Weighted capability score after the hard gates (100 points)

| Dimension | Weight | Measurements |
| --- | ---: | --- |
| Grounded task and tool correctness | 20 | pass@1/pass@k/pass^k, exact tool and slots, policy adherence, truthful spoken disposition |
| Natural multi-turn companion quality | 15 | blinded human preference, coherence, concision, persona consistency, helpfulness, punt/repetition rate |
| Duplex timing and overlap | 15 | turn-take rate, pause/backchannel handling, barge-in stop/re-entry, false yield and false response |
| Robot acoustic robustness | 15 | intent/critical-slot accuracy and WER by distance, angle, SNR, motor/fan/footstep/TTS echo, accent, reverberation |
| Correction, reference, and memory | 10 | self-correction, “there/that one/continue,” changed world, revocation/forgetting, task-progress explanation |
| Reliability and recovery | 10 | p50/p95/p99 latency, 429/5xx, loss/jitter, process/session restart, outage fallback, soak failures/hour |
| Portability, governance, and observability | 10 | adapter conformance, version pinning, event completeness, data controls, fallback equivalence |
| Fully loaded cost | 5 | invoice/successful committed turn and task, including media, LLM, tools, relay, logs, storage, and standby |

Provisional performance targets for the first bake-off—not claims about current
Parcel or any vendor—are:

- end-of-owner-speech to first meaningful audible frame: p50 <= 700 ms,
  p95 <= 1.2 s, p99 <= 1.8 s;
- deliberate barge-in detected in at least 98% of cases; owner onset to playback
  below -30 dB p50 <= 250 ms and p95 <= 500 ms;
- backchannel false-cancel <= 3%, side-speech false response <= 2%, and motor/ambient
  false wake <= 0.1/hour;
- navigation-intent accuracy >= 98% and critical-slot exactness >= 99% on the held-
  out corpus, while voice stop remains supplemental to the independent stop; and
- zero duplicate, stale, or unauthorized tool/action admissions in the safety
  campaign.

Measure each stage separately: capture/VAD/endpointer, transcript commit, brain/tool,
first audio from provider, network, decode, speaker enqueue, acoustic presentation,
and cancel acknowledgement. TTFA alone can look excellent while a user waits through
endpointing or a tool call.

Use paired repeated measures over identical hidden audio/turn seeds, randomize order
and time blocks, and freeze model, reasoning effort, voice, prompt, region, codec,
buffers, AEC, chassis/firmware, and tool schema. Run at least 30 repetitions per
scenario/config for distributions and at least 10 live humans for a pilot; power the
final human study from that pilot. Report paired-bootstrap confidence intervals,
Wilson intervals for binary rates, and human-rating rater/prompt effects. Zero rare
failures is not proof: the rule of three gives an approximate 95% upper bound of
3/n.

### 4.3 Reuse instead of starting over

The bake-off should extend, not overwrite:

- `conversation_quality_v1` for structured/machine cases;
- `personal_convo_v1` for multi-turn companion families;
- `duplex_v1` for cancellation/overlap invariants;
- `acoustic_loop_v1` for the existing virtual-rig baseline;
- the new `evals/autorater/` pairwise and side metrics; and
- N42's causal envelope and promotion ledger.

Add a new versioned `evals/companion/provider_swap_v1/`. Its credential-free fixture
and recorded-replay lane may gate CI; live provider and live-microphone lanes report
separately. The AutoRater is not a promotion authority until it is calibrated against
held-out human preference.

## 5. Replaceable provider architecture

### 5.1 Current checkout truth

Parcel already has useful safety and injection seams, but it is not plug-and-play:

- `providers.py` exposes synchronous text planning/conversation, batch ASR, and
  text-to-audio-byte protocols, not a versioned realtime session contract;
- web, CLI, and legacy ROS entry points construct llama.cpp directly instead of one
  provider registry;
- the speech factory is a hard-coded `if/elif` over Whisper, Piper, and local Fish;
- the microphone path buffers a complete utterance before batch STT;
- the speaker infers WAV versus raw PCM bytes rather than receiving a typed audio
  format, sequence, and presentation clock;
- `DuplexVoiceSession` relies on optional duck-typed callbacks and cancellation; and
- the current `FishSpeechProvider` is the **local self-host Fish Speech** service,
  not Fish cloud TTS or Fish Agents.

These are good prototype seams, but adding a vendor directly to them would spread
provider event names, codecs, credentials, pricing fields, and cancellation behavior
through the runtime.

### 5.2 Target ports and event state machine

```text
microphone / WebRTC / replay
            |
            v
 AudioFrameV1 + AudioFormatV1
            |
   VoiceMediaProviderV1 adapter  <---- provider-specific SDK / WS / WebRTC
            |
 normalized transcript, audio, state, usage, fault, tool-proposal events
            |
      CommittedTurnV1 + CommandAuthorityV1     (local, provider-neutral)
            |
 deterministic router / TaskExecutive / DialogueNarrator
            |
      untrusted reply + tool/action proposal
            |
 local validation / safety / gateway             speaker
```

The contracts should include:

- `AudioFormatV1`: codec, sample rate, channels, sample width, frame duration;
- `AudioFrameV1`: session/turn/generation, monotonic sequence, capture and receive
  clocks, source principal, payload and bounded size;
- `ProviderCapabilitiesV1`: modalities, streaming/final transcripts, server/client
  endpointing, cancel acknowledgement, tool proposals, codec/rate support, region,
  retention class, context and session limits;
- `ConversationProviderV1` and `PlanningProviderV1`: text/model roles with separate
  lifecycle, queue, budget, cancellation, health, identity, and circuit breaker;
- `StreamingRecognizerV1` and `StreamingSynthesizerV1`: typed partial/final and
  audio events with exactly one terminal event;
- optional `ManagedVoiceSessionAdapterV1`: opens/closes a native duplex session,
  accepts normalized audio and committed tool results, and emits only normalized
  transcript/reply/audio/tool **proposals**; and
- `ProviderUsageV1`/`ProviderFaultV1`: provider/model/config/region/session/request
  identity, native usage units, normalized estimated cost, retryability, and causal
  trace IDs.

Provider-specific IDs never become task, authority, or memory primary keys. A local
generation fence rejects late events after cancel/fallback. Switching providers
creates a new session/generation; it never resumes a vendor session into an existing
positive-motion authority interval.

### 5.3 Configuration and credentials

One strict registry resolves every entry point. Configuration names a provider
profile and a credential **reference**, never a secret value. N29 validates required
capabilities, local/remote classification, region, data policy, model/version, codec,
and fallback before startup. Unknown keys or a provider whose declared capabilities
cannot satisfy the selected profile fail closed.

Keep transport optional. LiveKit or Pipecat may implement media/orchestration
adapters, but neither becomes Parcel's domain contract. A direct provider adapter and
a local cascade must pass the same conformance suite.

### 5.4 Fallback and rollout

1. Establish the current local cascade as `control` with exact replay/evidence.
2. Land provider contracts and a scripted fake; prove cancel, backpressure, codec
   normalization, generation fencing, and local STOP independence.
3. Add one managed adapter in shadow/replay mode. Only the incumbent is audible and
   no challenger tool proposal executes.
4. Run paired credentialed lab audio, then live microphone/AEC, then stationary
   chassis, then walking-body-noise cases.
5. Promote a provider profile only with a signed model/config/region/cost manifest,
   passing hard gates, confidence-bounded score, and tested one-config rollback.
6. Retain the local text/typed command path through every cloud outage.

## 6. Ownership and next work

This design does not create a competing backlog owner:

| Owner | Provider work it owns |
| --- | --- |
| N29 | strict provider profiles, capability admission, credential references, release/model/data-region identity |
| N32 | immutable committed transcript, principal/authority, and provider-independent narration/disposition |
| N35-A | conversation/planning provider registry, role isolation, lifecycle, deadlines, cancellation, fallback |
| N37-A | typed audio/media contracts, managed-session adapters, normalization, cancellation acknowledgement, adapter conformance |
| N42-A | causal provider/usage/cost events, recorded replay, provider-swap runner, scorecard, confidence intervals, human-review harness |
| B18 | owner decision on remote audio/text egress, retention, enrollment, and permitted voice authority |

The dated execution handoff is
[`scrum/20260816/task_6/README.md`](../scrum/20260816/task_6/README.md).

## 7. What this does not prove

- No cloud credential, SDK, provider session, or live API call was used.
- No current provider has passed Parcel's adapter conformance or hard authority
  gates.
- No microphone, speaker, AEC, chassis-noise, human-preference, or billed-cost
  measurement was collected.
- External composite scores are not physical safety, companion quality, privacy,
  uptime, or first-ODD evidence.
- The proposed latency/error targets are preregistration candidates, not achieved
  values.
- “First adapter” does not mean “production default,” and the local cascade remains
  the rollback path until a later evidence-backed decision explicitly changes it.
