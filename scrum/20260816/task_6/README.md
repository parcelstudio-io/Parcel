# Task 6 — voice-agent benchmark, selection, and swap boundary

**Date:** 2026-08-16  
**Type:** research/architecture handoff; no provider installation, credentials, or
paid API calls  
**Design of record:**
[`docs/VOICE_PROVIDER_ARCHITECTURE.md`](../../../docs/VOICE_PROVIDER_ARCHITECTURE.md)

## Objective

Choose the right voice-agent candidates for a capable conversational robot dog,
define a benchmark that measures the robot rather than a vendor demo, and make the
selected provider replaceable without changing conversation authority, task
authority, or motion safety.

## Board

| ID | Work | Durable owner | Status |
| --- | --- | --- | --- |
| R1 | Audit current public duplex/task/acoustic benchmarks and evidence quality | this research task | **done** |
| R2 | Normalize public pricing and hidden-cost assumptions | this research task | **done** |
| R3 | Audit Parcel's current provider, audio, authority, and eval seams | this research task | **done** |
| R4 | Publish shortlist, hard gates, weighted scorecard, and target adapter architecture | this research task | **done** |
| I1 / N35-A | One conversation/planning provider registry used by web, CLI, and ROS; isolated role lifecycle/cancel/fallback | N35 | **todo** |
| I2 / N37-A | Typed audio/media and managed-session provider contracts plus adapter conformance suite | N37 | **todo after N32 base** |
| I3 / N42-A | `provider_swap_v1` replay/live runner, causal usage/cost events, confidence intervals, human-review harness | N42 | **todo in slices** |
| P1 | Decide remote audio/text egress, recording, retention, residency, enrollment, and permitted voice authority | B18 / owner | **blocked on owner policy** |
| P2 | Run live microphone, AEC, chassis-noise, and human-preference promotion evidence | B3/B15/B21/B29 | **externally blocked** |

This task does not introduce N45 or a new implementation owner. N29 owns strict
provider/capability configuration, N32 owns the committed-turn and authority plane,
N35 owns model providers, N37 owns media/session adapters, N42 owns comparison
evidence, and B18 owns the remote-data policy.

## Recommendation

### What “most capable” means today

The current Artificial Analysis native speech-to-speech aggregate ranks:

1. Qwen Audio 3.0 Realtime Plus — 84.1;
2. Grok Voice Think Fast 2.0 High — 82.9;
3. GPT-Realtime-2.1 High — 79.1; and
4. Gemini 3.1 Flash Live Preview High — 69.5.

That is a shortlist prior, not a product decision. Qwen's documented realtime Plus
deployment is mainland China. The public xAI integration uses the moving
`grok-voice-latest` alias, whose equivalence to the benchmark configuration must be
proved. The benchmark is mostly audio reasoning, conversational dynamics, and
customer-service tasks; it does not test Parcel's microphone, body noise, owner,
authority, reconnect behavior, or local rollback.

### Recommended implementation order

1. Keep the current local Whisper/Gemma/Piper-or-Fish cascade as the control and
   offline rollback.
2. Implement GPT-Realtime-2.1 High as the first opt-in managed adapter. It is the
   strongest combination of a named public model, current duplex evidence, function
   calling, and protocol maturity among the immediately practical candidates. It is
   not the production default and is expensive.
3. Add Grok Voice as the capability challenger and Gemini 3.1 Live as the cost and
   live-vision challenger. Gemini needs an explicit no-response/tool-completion
   watchdog because current direct evidence includes silent tool cases.
4. Admit Qwen Audio 3.0 Plus to the research bake-off only after region, latency,
   privacy, procurement, and exact-version pinning are acceptable.
5. Use Hume EVI or PersonaPlex to test social expression, not as the sole task brain;
   use ElevenAgents and Deepgram when managed-cascade operations/BYO components are
   the objective; use Fish S2 as an expressive TTS component. Fish Agents remains
   exploratory until a public tariff and independent full-agent evidence exist.
6. Do not integrate Sesame: no public production API, SDK, price, or SLA was found.

No provider receives physical authority. Native tool calls, partial transcripts,
audio deltas, and affect labels are untrusted proposals. An exact committed turn,
local principal/authority, freshness/deduplication, task admission, and the
independent gateway/safety chain remain mandatory.

## First implementation slice

N35-A and N37-A should first land a scripted fake, not a cloud SDK. The smallest
useful slice is:

- `ProviderCapabilitiesV1`, `AudioFormatV1`, `AudioFrameV1`, normalized transcript,
  reply/audio/tool-proposal, usage, fault, cancel-ack, and terminal events;
- one provider registry used by every front door;
- one local-cascade adapter and one scripted managed-session adapter;
- monotonic sequence/generation fencing, bounded queues/backpressure, exactly one
  terminal event, no post-cancel audio, and reconnect without replay;
- credential references and remote/local/data-region classification, never secrets
  in YAML or logs; and
- local STOP and final-only physical authorization while the fake provider is dead,
  slow, malformed, duplicated, reordered, or rate-limited.

Only after that conformance suite passes should a real GPT-Realtime adapter land.
LiveKit or Pipecat may be transport implementations, but neither becomes the Parcel
domain contract.

## Bake-off entry and exit

Run identical hidden audio/turn seeds through the local control and every challenger.
Hard gates precede score. The weighted score is: grounded task/tool correctness 20,
human companion quality 15, duplex behavior 15, robot acoustic robustness 15,
correction/reference/memory 10, reliability/recovery 10, portability/governance 10,
and fully loaded cost 5.

Minimum reporting:

- exact provider/model/reasoning/voice/prompt/region/codec/AEC/chassis manifest;
- pass@1/pass@k/pass^k and exact tool/slot/task-state results;
- end-of-speech-to-audible and barge-in p50/p95/p99 with stage decomposition;
- false cancellation, false response, no-response, echo/self-command, duplicate,
  stale, reconnect, and outage rates;
- blinded human preference with confidence intervals;
- invoice per connected minute, committed turn, and successful task; and
- `does_not_prove` for every fixture, replay, lab, and chassis rung.

Promotion requires every hard gate, a confidence-bounded win or explicit cost/
privacy tradeoff, one-config rollback, and the applicable B18/B3/B15/B21/B29 owner
and physical evidence. Overlapping confidence intervals or a composite difference
under three points is a tie.

## Cost planning snapshot

At medium use (3,120 connected minutes/month), public-rate screens are roughly:

- Gemini 3.1 Live: about $22 raw-audio floor to $91 when linearly projecting the
  external benchmark workload;
- GPT-Realtime-2.1: about $93 raw-audio floor to $559 on that workload;
- Grok Voice: $156 at the documented starting rate;
- Deepgram Custom BYO LLM: about $184 plus the brain;
- Hume EVI: about $185 on the cheapest applicable public tier, plus a custom brain
  where used;
- Qwen Audio 3.0 Plus: about $230 from the external workload, with the mainland-
  China deployment caveat;
- ElevenAgents: about $250 plus LLM; and
- Fish core ASR+TTS: about $19-$31 for audio components only, plus the brain, media,
  and orchestration.

These are planning numbers, not quotes. They exclude cellular/relay/egress, tools,
retrieval, logs/audio retention, HA, support, taxes, and engineering. Actual cost must
come from captured provider usage plus invoices.

## Does not prove

- No provider adapter or provider registry landed in this task.
- No API/model was called and no rate, capability, data policy, or SLA was accepted.
- No current provider passed Parcel's authority/conformance gates.
- No live microphone, AEC, body-noise, human, billed-cost, or robot result exists.
- Public and vendor benchmarks do not prove companion quality, safe autonomy, or
  first-ODD readiness.
