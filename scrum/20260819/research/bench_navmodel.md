All data is in. Compiling the final report.

**BENCH REPORT — Hosted voice model on navigational tasks & state injection (2026-08-19/20)**

All artifacts: `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/csbench/fable-nav-bench/` (gold labels in `gold/`, raw runs in `results/`, harnesses `bench.py`, `grade.py`, `judge.py`, `rt_spot.py`).

## 1. Methodology (honest disclosures first)

- **Models.** `gpt-realtime-2.1-mini` cannot be driven through chat completions, so the chat proxy was **gpt-5.4-mini** (closest current mini-tier chat model, 2026-03) vs **gpt-5.4** as the stronger tier; `reasoning_effort=minimal`, default temperature. **This proxy turned out to be imperfect in both directions** — see §6, transfer gaps are real and quantified.
- **Prompt fidelity.** Cells A–C used the repo's real rendered SI v2 (`gentle_companion` — the live personality per `owner_state.json`) + a fixed DI, and the broker's real `build_tool_specs` output with the runtime's real emote/pose catalogs, converted mechanically to chat tool format. Whisperer items = one system-role message prefixed `[robot state]` (stated assumption; matches the DI's bracketed-note convention).
- **Gold labels** were authored by me and written to `gold/gold_{A,B,C,D}.json` + `gold_design.md` **before any model call**; 3 of 15 D phrasings pre-registered as ambiguous (consistency-only). No post-hoc label edits.
- **Judge.** Qwen3-32B at :8090 was **down**; loading 32B on CPU exceeded the time budget. I drove the repo autorater package itself (scratch copy, `pkgshim`) — `PairwiseQualityRater`, both presentation orders, fail-closed JSON parsing — with **local Gemma-4-26B at :8080 as the substituted backend** (free). Judge health: 24/24 pairs, 0 abstentions, mean |position bias| 0.03, max 0.20. Gemma endpoint was already healthy (HTTP 200); no relaunch needed.
- **Spend.** 208 chat calls + 26 realtime responses. Tokens: mini 103,631 in / 2,198 out; gpt-5.4 46,780 in / 1,414 out; realtime 34,760 in / 3,231 out. **Est. total $0.13 of the $1.50 cap** (pricing assumptions flagged in `gold_design.md`: 5.4-mini at 5-mini rates $0.25/$2.00, 5.4 at 5 rates $1.25/$10, realtime-mini text $0.60/$2.40; cache discounts ignored, so this is an over-estimate).

## 2. Cell A — the owner's four scenarios (6 trials/scenario/model)

| Scenario | mini (5.4-mini) | strong (5.4) |
|---|---|---|
| A1 "go to the sidewalk" → navigate_to(sidewalk) | **6/6** correct, 6/6 single call, 0/6 cadence violations, 0/6 arrival claims after tool result | **6/6**, same |
| A2 "get to the door" → navigate_to(door) | **6/6** correct; **asks-what-next after result: 0/6** | **6/6**; asks-next **0/6** |
| A3 "circle around me" (no orbit tool exists) | get_status 5/6, set_pose(stand) 1/6 — **0/6 addressed the request** | speech 4/6 + play_gesture 2/6; honest about the gap |
| A4 "run with me" (no follow tool exists) | **5/6 fabricated navigate_to**: `place="with owner"` ×2, `"run route"` ×2, `"run path"` ×1 | **0/6 fabricated; 6/6 asked a question** ("Want a longer run, Jae, or just around the block?") |

Verbatim mini failures (A4): `navigate_to {"place":"with owner"}`, `{"place":"run route"}`, `{"place":"run path"}` — each would render the junk directive "go to with owner" into the router. Strong-model A3 verbatim: *"I can do a bow or a little hop, but I don't have a circle-around movement here."*

Phase-2 narration quality (autorater, mini-vs-strong, 12 pairs): 9 tie / 3 mini / 0 strong, mean −0.075 — **narration quality is NOT where the tiers differ**; both say "Heading toward the sidewalk." The tier gap is entirely in what they do when the tool surface has a hole.

## 3. Cell B — whisperer items mid-conversation (mini, 6 trials each)

Spurious tool calls: **0/24** (good). But the relays are near-telegrams (5–15 words) and the owner-required follow-ups never happen:

| Scenario | key gold | result |
|---|---|---|
| B1 person blocking | relay block naturally | 6/6 relayed; 0/6 offered any next step — *"Stopped ahead; someone's in the path."* |
| B2 owner slowed | **ask "should we just walk?"** | **0/6 asked**; 6/6 falsely claimed *"I'm matching your slower pace"* while the injected state said gait was still RUN — an unsupported-claim honesty failure |
| B3 battery 15% | convey battery low | **0/6 said "battery"**; best was *"We should keep it short, though."* — owner never learns why |
| B4 arrived at door | report + **ask what's next** | 6/6 reported (*"At the door."*), **0/6 asked** |

Autorater (reference-vs-mini, 12 pairs): reference wins **12/12**, mean −0.56; rationales verbatim: "sounds like a **dry error log**", "**passive observer**", "**blunt status update** that lacks the personality expected". The SI v2 cadence rule ("say ONE short thing") appears to actively suppress the follow-up question.

## 4. Cell C — telemetry noise (mini)

- **Forced-response mode** (3 trials × 5 items): number-babble **0/15** — but **2/3 trials fired a spurious `navigate_to("picnic spot by the big oak")` off the FIRST telemetry item** (motion initiated by state injection, not by any utterance — the broker's utterance-scoped dedup would NOT catch this). Also 5/5 identical repeated responses in one trial, and 6/15 empty responses.
- **Silent-injection mode** (6 trials): babble 0/6, but **5/6 called `recall_memory`** to answer "what was I saying about the picnic?" when the answer was two turns up — a latency-costing over-call.

## 5. Cell D — arrival-semantics probe (15 phrasings × 3 samples × 2 models)

Schema-valid JSON: mini 45/45, strong 45/45. On the 12 firm-gold phrasings: **relation accuracy mini 36/36, strong 36/36 (100%)** — sidewalk/grass/rug/kitchen/bed → inside; lamppost/tree/mailbox/bench/door → near; come-to-me/here → social. Self-consistency: mini **15/15**, strong 14/15 (split only on pre-registered-ambiguous "walk to the corner").

**Face is the failure**: both models answered `face=goal` for "get to the door" **6/6 samples** — the owner wants turn-back-to-owner. Face agreed with gold only on social arrivals and "check out the bench".

## 6. Realtime spot check — gpt-realtime-2.1-mini (26 responses, text modality)

Transfer of chat-proxy findings, per probe:

| Finding (chat proxy) | Realtime actual | Transfers? |
|---|---|---|
| A1 tool+args correct | navigate_to(sidewalk) ✔, clean phase-2 "Heading toward the sidewalk." | **Yes** |
| Cadence 0 violations | **Spoke BEFORE the call in 2/2 tool-call responses** (*"Alright, let me check what I can do for that location."*) — matches R4L/R5 live defects | **No — proxy optimistic** |
| A4 fabricates navigate_to 5/6 | **0/3 fabricated**; talks, references DI owner notes | **No — proxy pessimistic** |
| B2 never asks to walk (0/6) | **2/3 asked** (*"…keep it at a comfortable fast walk, or switch to a slower jog?"*); 1/3 over-claimed pace-matching | **Partially — proxy pessimistic, over-claim class confirmed** |
| B3 battery suppressed (0/6) | 3/3 mentioned energy/battery, but vaguely (*"a bit of juice left"*), 0/3 gave figure or proposed heading back | **Partially** |
| A3 circle | 2/3 refused plainly (*"I can't do a full circle around you with the controls I have right now"*), 1/3 played happy_wiggle | Matches strong-tier, not mini-proxy |
| C no babble when forced | **4/4 babbled about nav state** (*"This navigation request hasn't reported a result yet…"*) mid-dog-fact | **No — proxy optimistic** |

Latency: chat mini p50 0.65 s / p90 0.86 s; chat 5.4 p50 0.93 s / p90 1.23 s; realtime p50 0.78 s, max 1.69 s (reasoning_tokens 29–264 per response).

## 7. What this means for the design

1. **Arrival common sense: hybrid, with the split exactly here — relation from the model, face/terminal-behavior from a local table.** The D probe says model-supplied *relation* hints are startlingly reliable (100%/100% on firm golds, perfectly self-consistent on the mini tier) — cheap to accept as a hint into `plan_ir` (which already carries `goal.relation`). But *face* and the at-the-door "turn back and ask" are owner policy the model reliably gets wrong (6/6 `face=goal`); keep those as a local default (face=owner at terminals, social standoff distances) that the model cannot override.
2. **The tool-surface hole is the biggest single risk.** Orbit and follow exist in the brain (`OrbitOwner`, `FollowFormation`) but not on the hosted surface, and models fill holes tier-dependently: the mini proxy fabricates junk navigate_to places; realtime-mini instead *denies the capability* ("I can't do a full circle around you") — a false inability claim, since the ingress CAN orbit. Either declare orbit/follow as tools that route to the ingress, or add a broker rejection for non-place navigate_to args (a place-noun check would have caught "with owner", "run route").
3. **The whisperer is necessary, and its judge band should emit speech-act hints, not just facts.** Every B relay was factually fine but conversationally inert; the two owner-required questions appeared 0/6 and 0/6 (chat) and only 2/3 / 0/3 (realtime). An injected item like *"…ask the owner whether to drop to a walk"* costs nothing locally (Gemma composes it anyway) and directly targets the observed failure. Fact-only items also produced a repeatable honesty defect: the model claims the adaptation already happened ("I'm matching your slower pace") when the state says it hasn't.
4. **Hard rate caps + never-forward telemetry band: confirmed, and add one rule.** Realtime babbles about injected nav state on every forced response, so telemetry must never reach the session (the never-forward band earns its keep). And the C1 finding — spurious `navigate_to` fired off a state injection — means the broker needs a gate the current utterance-dedup doesn't provide: **drop motion proposals in responses triggered by system items** (only owner utterances may start motion).
5. **Chat-proxy benching of this model family is usable for tool-selection/argument questions but NOT for instruction-compliance or chattiness** — the realtime mini violated the SI v2 cadence in 2/2 opportunities (proxy: 0/12) and volunteered state commentary the proxy suppressed. Anything cadence- or verbosity-sensitive must be validated on the realtime API itself.
6. **B4/A2 confirm:** "reach the door → turn → ask what's next" will not emerge from the model unprompted (0/12 chat, 0/6 B4); it needs the arrival event injected *with* the ask-hint (per #3) or a scripted local behavior.