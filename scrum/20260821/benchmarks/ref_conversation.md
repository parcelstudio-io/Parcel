# Conversational-Quality Benchmarks vs. Parcel: A Comparability Audit

**Scope:** LMArena/Arena-Hard, MT-Bench lineage, multi-turn instruction benchmarks, hallucination/honesty (incl. over-claiming completed actions), persona consistency, proactive/mixed-initiative dialogue, and voice-agent-specific suites. Research date 2026-08-21. Source grade noted per benchmark: **[P]** primary (paper/official leaderboard fetched), **[S]** secondary (aggregator/search summary, treat as indicative).

---

## 0. The headline finding, stated first

Three things fell out of this survey that change how Parcel should talk about itself:

1. **Yes, there is now a named benchmark for Parcel's exact defect class.** "Done—I made a small circle around you" one second after admission is called **false success** in the literature, and it was characterized quantitatively in June 2026 across 9,876 trajectories. It is also encoded as `outcome_hallucination` in Agent-Diff (April 2026). Parcel's most distinctive failure is not an unmeasured curiosity — it is a named, actively-benchmarked phenomenon, and Parcel is architecturally unusually well-placed to measure it because its deterministic local chain already holds the ground-truth state that the hosted model's claim must be checked against.
2. **The single most damning published number for Parcel's model family is τ-Voice's "selectivity" metric: OpenAI's realtime lane scores 6%.** That is, when a user backchannels, coughs, or talks to someone else, the OpenAI realtime family responds anyway ~94% of the time. Parcel's silence problem is not a Parcel bug; it is the documented modal behavior of the hosted lane it rents.
3. **A public score already exists for approximately Parcel's model.** `gpt-realtime-mini-2025-12-15` scores **13.94% APR** on Audio MultiChallenge (audio-output), against 48.45% for `gpt-realtime-2` (xHigh) and 54.65% for Gemini 3 Pro. Parcel is building a companion on a model that ranks 11th of 13 on the only public multi-turn spoken-conversation leaderboard. Every Parcel result should be read against that ceiling.

Almost nothing else in this survey is comparable to Parcel's evidence. Details below.

---

## 1. Preference / Elo benchmarks

### 1.1 Arena (formerly LMArena / LMSYS Chatbot Arena) — Text **[P]**

**What it actually measures.** Crowdsourced blind pairwise preference on *user-chosen, unconstrained text prompts*. A voter types anything, sees two anonymous replies, picks a winner. Votes feed a Bradley–Terry model reported as an Elo-like "Arena score." The denominator is **votes, not tasks** — there is no fixed task set, no gold label, no ground truth, and the prompt distribution is whatever the internet types that week. Style control is available as a post-hoc regression to partial out markdown/length.

**Current numbers** (arena.ai/leaderboard/text, last updated **2026-08-19**): 393 models, 7,874,713 votes, score range **952–1508**.

| Rank | Model | Org | Score | CI | Votes |
|---|---|---|---|---|---|
| 1 | claude-fable-5 | Anthropic | 1507 | ±5 | 23,626 |
| 2 | claude-opus-4-6-high | Anthropic | 1505 | ±4 | 72,392 |
| 9 | gemini-3.7-flash-high | Google | 1490 | ±8 | 5,723 |
| 13 | gemini-3.1-pro-preview | Google | 1486 | ±3 | 98,068 |
| 18–19 | gpt-5.6-sol-xhigh / gpt-5.5-high | OpenAI | 1482 | ±4–5 | 18.5k / 58.5k |

**Where would a small realtime model sit?** Arena's text board does not list realtime/speech models at all. The nearest evidence is Scale's **Voice Showdown** (§1.3): GPT Realtime sits at **875 Elo (Dictate)** and **962 (S2S)** against Gemini 3 Pro at 1073 — i.e. roughly 100–200 Elo below frontier text-mode audio models, on a separate scale. A *mini* realtime variant is not in any public arena; the AudioMC gap (13.94 vs 37.61 APR) implies it would sit lower still.

**Comparability: NOT comparable.** Four independent blockers:
- **No shared denominator.** Arena has no task list; Parcel has 52 pre-registered queries with gold labels. You cannot map a per-query PASS/FAIL corpus onto a pairwise preference rating. There is no transformation.
- **No opponent.** Elo requires a paired competitor on the same prompt. Parcel has no second system answering the same 52 queries.
- **Wrong output space.** Arena scores text; Parcel's "output" is a tool call plus a physical consequence plus a spoken confirmation. A voter cannot judge whether the dog actually circled.
- **Voter ≠ owner.** Parcel's live run used the owner's real voice with owner-specific memory and persona. Arena's population is anonymous.

**Verdict:** Do not cite an Arena number in any Parcel document except as background on where the frontier is. There is no honest bridge.

### 1.2 Arena-Hard-Auto v2.0 **[P]**

**What it measures.** 500 hard real-world queries + 250 creative-writing queries sourced from Chatbot Arena. Automatic LLM judge (Gemini-2.5 primary; GPT-4.1 alternate) does pairwise comparison against a fixed baseline model; score is a **win-rate percentage with style control** (markdown + token length regressed out). Released **2025-04-23**.

**Current numbers** (hard prompts, style-controlled, Gemini-2.5 judge): o3-2025-04-16 **85.9%** (−0.8/+0.9); o4-mini-high **79.1%**; gemini-2.5 **79.0%**. Creative-writing board (ensemble judge): gemini-2.5 **90.8%**. Mid-tier reference from the v2.0 release table **[S]**: gpt-4.1 61.5%, gemma-3-27b-it 69.9%, QwQ-32B 60.9%.

**Comparability: NOT comparable.** Same structural problem as Arena plus one more: Arena-Hard's queries are *hard open-ended text tasks* (software engineering, math, creative writing). Parcel's surface is seven tools and a fixed intent taxonomy. There is no overlap in task distribution. A "transformation" would amount to running Arena-Hard's 500 prompts through Parcel, which would produce 500 refusals or 500 fabricated `navigate_to` calls and measure nothing.

**One thing worth stealing, not citing:** Arena-Hard's **style control** is the right idea for Parcel's `PairwiseQualityRater`. Parcel's autorater will otherwise reward the longer, warmer, more confident reply — which is precisely the reply that over-claims.

### 1.3 Voice Showdown (Scale Labs) **[P]**

**What it measures.** The first global preference arena for voice AI: blind pairwise comparison inside real user conversations, 60+ languages, diverse acoustics. Two battle types — **Dictate** (spoken prompt, compare two *text* responses) and **S2S** (compare two *spoken* responses, with diagnostic "why did you dislike the loser" categories). Bradley–Terry Elo, active-learning battle sampling, controls for position, in-flow bias, verbosity, and voice gender. As of **2026-03-18**: 11 frontier models, 52 model–voice pairs.

**Current numbers.** Dictate: Gemini 3 Pro **1073**, Gemini 3 Flash 1068, GPT-4o Audio 1019, Voxtral Small 925, **GPT Realtime 875**, Phi-4 Multimodal 729. S2S: Gemini 2.5 Flash Audio 1060, GPT-4o Audio 1059, Grok Voice 1024, **GPT Realtime 962**, **GPT Realtime 1.5 920**.

**Comparability: NOT comparable, but strategically important.** Parcel cannot produce an Elo. What it *can* do is note the ranking of its substrate. GPT Realtime sits 5th–7th on a board it shares with a 2024-vintage GPT-4o Audio that beats it. Parcel is not being let down by an unusual model; it is running near the bottom of the voice frontier, and a *mini* 2.1 variant is below even that.

---

## 2. Multi-turn instruction benchmarks

### 2.1 MT-Bench (Zheng et al. 2023) **[S]**

**What it measures.** 80 open-ended questions across 8 categories, each a 2-turn exchange. GPT-4 judge scores each answer 1–10 (single-answer grading), averaged. Denominator: 160 turns.

**Status in 2026.** Visibly saturated — top closed models cluster **above 9.0**, and remaining headroom is judge noise. Not formally deprecated; still discriminating for small open-weight models in the **7–8.5** band. Contamination is assumed.

**Comparability: NOT comparable.** MT-Bench is 2-turn free-form text with a 1–10 aesthetic judge. Parcel's corpus is single-turn spoken with binary/ternary gold labels against an intent taxonomy. Different modality, different turn count, different scoring rule, different denominator. Also: MT-Bench's saturation means even a *successful* Parcel MT-Bench number would carry zero information about a companion robot.

**Note for the record:** the fact that MT-Bench is saturated at 9.0+ while `gpt-realtime-mini` scores 13.94% on AudioMC is the cleanest available illustration of point (c) below — general conversational quality benchmarks stopped tracking anything that matters for embodied voice.

### 2.2 MT-Bench-101 (ACL 2024) **[S]**

**What it measures.** 13 multi-turn dialogue tasks in a 3-tier taxonomy (Perceptivity / Adaptability / Interactivity), **1,388 dialogues / 4,208 turns**. GPT-4 judge, 1–10, 87% agreement with human experts. 21 LLMs evaluated; GPT-4 leads at **8.86**. Notably includes a **proactive interaction** task and **context memory** / **anaphora resolution** tasks.

**Comparability: PARTIALLY comparable — the closest text benchmark to Parcel's category structure.** Three of MT-Bench-101's tasks map onto Parcel corpus categories almost one-to-one:

| MT-Bench-101 task | Parcel corpus category |
|---|---|
| Context Memory | `memory` |
| Anaphora Resolution | `nav-indirect`, `ambiguous` |
| Proactive Interaction | the missing follow-up question (0/6 in the chat bench) |

**Transformation needed to make a claim:** (a) re-author Parcel's 52 queries as multi-turn dialogues (MT-Bench-101 is 3–7 turns; Parcel's corpus is single-turn — this is the load-bearing gap); (b) replace Parcel's binary gold labels with MT-Bench-101's 1–10 judge rubric, or conversely re-label MT-Bench-101's memory/anaphora subsets with binary gold and run *those* through Parcel; (c) accept that Parcel would be scored on text transcripts, discarding the audio lane. The (c) direction — running MT-Bench-101's memory and anaphora subsets through Parcel's text path — is genuinely feasible and would be the cheapest external number Parcel could claim. It would still say nothing about the robot.

### 2.3 MultiChallenge (Scale, Jan 2025; judge upgraded to Gemini 2.5 Pro) **[S]**

**What it measures.** Realistic multi-turn conversations in four categories: **instruction retention**, **inference memory**, **reliable versioned editing**, **self-coherence**. Text only. LLM-as-judge, pass/fail per conversation.

**Current numbers [S]:** GPT-5 0.696 leading; GPT-5 Thinking 63.19; GPT-5.1 Thinking 63.41; Claude Opus 4.5 Thinking 58.97; Qwen3.5-397B-A17B 67.6%. ~24 models tracked. Frontier models sit in the **58–70%** band — this benchmark is *not* saturated.

**Comparability: NOT comparable directly.** But its **self-coherence** category is the text ancestor of what Parcel measured as "self-consistent 15/15." See §2.4 — the audio variant is the one that matters.

### 2.4 Audio MultiChallenge (AudioMC) — **the most relevant public leaderboard for Parcel** **[P]**

**What it measures.** Multi-turn conversational intelligence in **spoken** dialogue systems, including native speech-to-speech models. Explicitly *not* an ASR/TTS test: it measures whether a model can follow instructions, integrate prior context, remain self-consistent, and handle **natural speech corrections** across extended dialogues.

- **Size:** 452 conversations, 1,712 rubrics, 47 speakers, ~15 hours of natural unscripted user audio, 3–8 turns per conversation.
- **Scoring rule:** a task passes **only when all its rubrics are satisfied**. Primary metric **APR** (Average Pass Rate); secondary diagnostic **ARS** (Average Rubric Score). Judge: o4-mini, Cohen's κ ≈ 0.87 vs humans.
- **Two tracks** — Text Output and Audio Output — deliberately isolating the **modality gap**.

**Current numbers, Audio Output track:**

| Rank | Model | APR |
|---|---|---|
| 1 | gpt-realtime-2 (xHigh) | 48.45 ± 4.59 |
| 3 | gpt-realtime-2 | 37.61 ± 4.45 |
| 5 | gpt-realtime-1.5 | 34.73 ± 4.38 |
| 8 | gpt-4o-audio-preview-2025-06-03 | 23.23 ± 3.88 |
| 10 | gpt-realtime-2025-08-28 | 20.35 ± 3.70 |
| **11** | **gpt-realtime-mini-2025-12-15** | **13.94 ± 3.19** |
| 13 | gpt-4o-mini-audio-preview-2024-12-17 | 13.05 ± 3.11 |

Top overall (combined/ARS view): Gemini-3-Pro-Preview ARS **54.7%**, Gemini 2.5 Pro 46.9%, Gemini 2.5 Flash 40.0%; Inkling (Thinking) APR 56.64%. Modality gap is real and measured: GPT-4o Audio Preview drops **25.44% → 23.23%** moving from text output to native speech generation.

**Comparability: PARTIALLY comparable — and the closest thing to a legitimate Parcel reference point.**

*What's shared:* real unscripted human audio; multi-turn; all-rubrics-must-pass scoring (same shape as Parcel's strict PASS); self-consistency and instruction-retention categories; and — critically — **the same model family**, with a published number for a mini realtime snapshot.

*What blocks a direct claim:* (i) AudioMC is 3–8 turns; Parcel's corpus is **single-turn** — this alone disqualifies a shared number; (ii) AudioMC has no tool surface and no physical consequence; (iii) AudioMC's rubrics are conversational, Parcel's gold labels are intent+tool+args; (iv) n: 452 conversations / 1,712 rubrics vs Parcel's 52 queries.

*Transformation required:* Parcel would have to extend its corpus to multi-turn with per-turn rubrics, and either run AudioMC's public conversations through its audio gateway (measuring the hosted lane, not the product) or author a Parcel-domain rubric set in AudioMC's format. The **first** of these is cheap and is recommended in §8.

**Honest positioning today.** Parcel's `live_run_1` strict pass rate is **13/35 adjudicated = 37.1%** (Wilson 95% CI **[23.1%, 53.6%]**), or 25.0% if you use all 52 as the denominator. Superficially that number sits between `gpt-realtime-mini` (13.94) and `gpt-realtime-2` (37.61) on AudioMC. **This coincidence is meaningless and must not be reported as a comparison.** Parcel's tasks are single-turn and mostly short commands; AudioMC's are 3–8-turn with correction handling. Parcel's task distribution is dramatically easier per-turn and dramatically harder in consequence. The only legitimate use of the AudioMC table is as a **ceiling argument**: the hosted lane Parcel rents scored 13.94% on multi-turn spoken conversation, so any Parcel multi-turn conversational result in that neighborhood is the substrate's, not the product's.

---

## 3. Voice-agent task benchmarks — the nearest neighbors Parcel actually has

### 3.1 τ-Voice (arXiv 2603.13686, 2026-03-14) **[P]** — *the closest published analogue*

**What it measures.** Full-duplex voice agents on grounded customer-service tasks. Combines **verifiable completion of grounded tasks**, **full-duplex interaction**, and **realistic audio**. This is the τ-bench formula moved into voice.

- **Task distribution:** 278 tasks — Retail 114, Airline 50, Telecom 114.
- **Denominator/scoring:** **Pass@1**, binary success determined by **final database state matching annotated goals** — i.e. ground truth is the world, not the transcript. Exactly Parcel's situation.
- **Two conditions:** Clean (clear audio, American accents, no interruptions) vs **Realistic** (background noise, diverse accents, turn-taking dynamics).
- **User simulator:** waits for a **1s silence threshold** before speaking; an LLM periodically decides whether to interrupt during agent speech.

**Current numbers (Pass@1, all domains):**

| Condition | Google (gemini-live-2.5-flash-native-audio) | OpenAI (gpt-realtime-1.5) | xAI (grok-voice-agent) |
|---|---|---|---|
| Clean | 31% | 49% | 51% |
| Realistic | 26% | 35% | 38% |
| *GPT-5, text mode* | — | **85%** | — |

Voice-quality metrics (Realistic, Table 8):

| Provider | Latency | Responsiveness | Interrupt rate | **Selectivity** |
|---|---|---|---|---|
| OpenAI | 0.90s | 100% | 14% | **6%** |
| Google | 1.14s | 69% | 21% | 54% |
| xAI | 1.15s | 83% | 84% | 57% |

**Comparability: PARTIALLY comparable — the best available frame for Parcel's whole architecture, and the source of its most useful published caveat.**

*What's shared:* voice in, tool calls out, ground truth in world state rather than transcript, realistic audio degradation, a small fixed tool surface, an OpenAI realtime model evaluated by name.

*What blocks it:* (i) τ-Voice's world state is a **database**; Parcel's is a **physical simulation with a safety supervisor that can veto** — Parcel has a disposition layer τ-Voice's agents don't; (ii) τ-Voice is multi-turn task completion, Parcel's corpus is single-turn intent handling; (iii) 278 tasks vs 52 queries; (iv) domains are entirely different (retail/airline/telecom vs navigation/social-motion/gesture).

*Positioning that IS legitimate:*
- **The text→voice gap.** τ-Voice measures GPT-5 at 85% in text mode vs 35–51% in voice. Parcel independently observed the same shape: **chat-API 6/6 correct tool+args on direct navigation** vs a live spoken corpus at 37.1% strict. Parcel's own text-vs-voice gap is *the same phenomenon τ-Voice quantified*, and citing τ-Voice lets Parcel say "this gap is a documented property of the modality, not evidence that our chain is broken." With the caveat that Parcel's n=6 chat cell has a 95% CI of **[61%, 100%]** and cannot support a precise gap estimate.
- **Latency.** Parcel's realtime p50 **0.78s** / max 1.69s vs τ-Voice's OpenAI **0.90s** under realistic conditions. **Do not report this as "Parcel is faster."** τ-Voice defines latency as user-utterance-end → agent-response-onset; Parcel's number is explicitly *turn-level, not first-token*. Those are different quantities and Parcel's is almost certainly measuring a larger interval, which would make the comparison flattering and wrong. To compare, Parcel must instrument onset latency specifically (`duplex_v1` already gates TTFT p50 < 1s via `query_end`→`tts_first_chunk` — that IS the right definition and IS the number to report).

### 3.2 EVA-Bench (arXiv 2605.13841, 2026-05-13) **[P]** — *the best metric taxonomy to copy*

**What it measures.** End-to-end voice agents, **213 scenarios** across airline CSM, healthcare HRSD, and enterprise ITSM; **12 systems**, k=5 trials clean / k=3 perturbed. Splits into two axes:

- **EVA-A (Accuracy):** *Task Completion* (binary, final DB state via SHA-256 hash), *Faithfulness* (LLM-judge: are agent actions grounded in instructions, policies, tool results, user inputs), *Speech Fidelity* (LALM-judge on spoken named entities).
- **EVA-X (Experience):** *Conversation Progression*, *Conciseness* ("appropriately brief for spoken delivery"), *Turn-Taking* (timestamp-based, piecewise-linear latency curve, penalizes both interruption **and excessive silence**, and counts failure-to-respond).
- **Pass rule:** EVA-A passes iff completion=1.0 AND faithfulness≥0.5 AND speech fidelity≥0.95. EVA-X passes iff turn-taking≥0.8 AND progression≥0.5 AND conciseness≥0.5. Reports pass@1, pass@k, **pass^k**.

**Current numbers.** Best EVA-A pass@1: **0.504** (Nova-3 + GPT-5.4 + Sonic 3 cascade). Best EVA-X pass@1: **0.589** (Gemini-3.1-Flash-Live, S2S). **No system exceeds 0.5 on both simultaneously.** Median pass@k − pass^k gap on EVA-A: **0.44**.

**The single most important sentence in this survey for Parcel:** *"72.2% of conversations with task completion = 1 exhibit at least one faithfulness deviation (faithfulness < 1.0), indicating that agents frequently make policy deviations or hallucinate details even when they call the correct tools."* That is Parcel's "Done—I made a small circle around you," measured on 213 scenarios and 12 systems.

**Comparability: PARTIALLY comparable.** Not a shared task set — but EVA-Bench's **metric decomposition is directly portable** to Parcel and is what Parcel's corpus is currently missing. Parcel's PASS/PARTIAL/FAIL collapses accuracy, faithfulness, conciseness, and turn-taking into one ordinal. EVA-Bench shows why that is a mistake: those axes anti-correlate, and Parcel's PARTIAL bucket (9 in live_run_1, 15 in replay_run_1 — the *largest* bucket in the replay) is almost certainly hiding an EVA-A/EVA-X split.

**Also directly relevant: the pass^k gap of 0.44.** Parcel has never reported a pass^k. Its 6-trial chat cells report per-cell rates but not "all 6 succeeded." Given EVA-Bench's finding, Parcel's 6/6 direct-navigation result **is** effectively a pass^6 on one cell — which is genuinely notable and *underclaimed* in the current write-up. It is the one Parcel number that survives contact with this literature well.

### 3.3 Full-Duplex-Bench (arXiv 2503.04721, + v2 / v3) **[P]**

**What it measures.** Turn-taking and overlap handling in full-duplex spoken dialogue models, on four axes:
1. **Pause handling** — speaker pauses but holds the turn. Metric: **Takeover Rate (TOR)**, lower is better.
2. **Backchanneling** — appropriate "uh-huh" without interrupting. Metrics: TOR, backchannel frequency, **JSD** of timing vs human distribution.
3. **Smooth turn-taking** — **Response Latency** (end of user speech → start of model response).
4. **User interruption** — TOR, GPT-4o response-quality score, latency-after-interruption.

**Published numbers:** dGSLM pause-handling TOR (synthetic) **0.949**; Moshi **1.000** with response latency 0.037s; Freeze-Omni **0.672**, GPT-4 score 3.371. (Read that Moshi row carefully: 1.000 TOR means it takes over on *every* pause. Low latency and appropriate silence are in direct tension.)

**v2** extends to multi-turn with task families (daily scenarios, correction handling, entity tracking) and an automated examiner enforcing staged goals. **v3** combines real human disfluent speech with multi-step tool use.

**Comparability: NOT comparable as-is; PARTIALLY comparable after instrumentation.** Full-Duplex-Bench evaluates *models*, not products, and requires a full-duplex audio stream with controlled pause insertion. Parcel's corpus is replayed single-turn utterances — there are no held pauses to take over on, so TOR is undefined on Parcel's existing artifacts. **However**, Parcel has an audio gateway and a `duplex_v1` eval already; Full-Duplex-Bench's stimuli are public and its TOR metric is mechanically simple. This is the cheapest route to a *real, externally-defined* Parcel number (§8).

### 3.4 VoiceBench (TACL 2026) **[P/S]**

**What it measures.** 6,783 synthetic and real spoken instructions across 8 tasks / 9 datasets, covering general knowledge, instruction-following, reasoning, and **safety**, with systematic variation in speaker characteristics (accent), environment (reverberation), and content (mispronunciation). 41 models evaluated. Top open model: Qwen2.5-Omni-7B, VoiceBench-Avg **0.741** **[S]**.

**Comparability: NOT comparable.** VoiceBench measures a voice *assistant's* knowledge and instruction-following with no tool surface and no world state. Its only genuinely transferable contribution to Parcel is the **perturbation axis**: accent, reverberation, mispronunciation. Parcel's "one ASR-variant e-stop positive never tested" is exactly the hole VoiceBench's perturbation design exists to fill, and VoiceBench's methodology is the citation to justify building that test.

---

## 4. Hallucination / honesty — including the over-claiming question

### (a) *Is there any benchmark that measures an assistant claiming it did something it did not do?* **Yes. Three, all from 2026.**

### 4.1 "From Confident Closing to Silent Failure: Characterizing False Success in LLM Agents" (arXiv 2606.09863, ICML 2026 FAGEN workshop) **[P]** — **the direct hit**

**Definition.** *False success* = a mismatch between the agent's natural-language claim of completion and the programmatic environment state. "Your refund has been processed" while the database shows nothing.

**Measurement and denominator — read this carefully.** False-success prevalence is reported as a **percentage of failures** (reward=0 trajectories), **not** a percentage of all tasks. This is the single most important methodological detail for Parcel to replicate correctly.

**Datasets:** τ²-bench — 9,876 trajectories (8,146 successes, 1,730 failures), 616 labeled false successes, 8 model families, 3 domains. AppWorld — 1,879 trajectories with explicit completion claims, 1,425 false successes vs 454 honest failures, 4 model families.

**Taxonomy (τ²-bench failures):** False success **35.6%**, Honest failure **43.5%**, Ambiguous **20.9%**.

**Per-model false-success rate among failures:** GPT-5.2 **13%**; Claude Opus/Sonnet **30–35%**; Gemini / GLM-5 **40–50%**; Qwen3-Max-Thinking **79%**. AppWorld: LLaMA-3 67%, GPT-4o/4-Turbo mid-70s, DeepSeekCoder 89%.

**By domain — the finding Parcel should care about most:** Airline 45%, Retail 48%, **Telecom (dual-control) 3%**. Dual-control — where the *user*, not the agent, executes some actions and the agent must therefore wait for external confirmation — reduces false success by an order of magnitude. **Parcel's architecture is dual-control by construction**: the hosted model proposes, the local chain disposes, and the local chain knows whether the circle happened. Parcel is structurally in the 3% regime and is failing to exploit it.

**LLM judges cannot detect it.** No configuration across 5 judges × 5 prompt strategies with full task specifications exceeded **AUROC 0.65** on τ²-bench (best: Claude Sonnet 4.5 no-closing, 0.640; reasoning models worse — DeepSeek-R1 0.573, o3-mini 0.554). On AppWorld the best was GPT-4o checklist at **0.537** — coin-flip. Judges latch onto *confident closing language* as a proxy for success. Meanwhile **cheap supervised detectors work**: TF-IDF + LogReg **0.849**, TF-IDF + XGBoost **0.825 ± 0.025** (τ²-bench task-disjoint), **0.953 ± 0.020** on AppWorld; 4–8× more false successes recovered than the best judge at equal human-review budget, at 3,300× lower latency.

**Comparability: PARTIALLY comparable — and this is the benchmark Parcel should build toward.**

*What's shared:* the exact defect, the exact mechanism (NL claim vs programmatic state), and a scoring rule Parcel can compute *offline from artifacts it already has* — because Parcel's task executive and navigator emit the ground-truth state that the spoken claim must be checked against.

*What blocks a direct number:* Parcel's corpus is not τ²-bench or AppWorld; the tasks, domains, and n are entirely different. Parcel cannot report "Parcel's false-success rate is X, vs GPT-5.2's 13%" as a like-for-like — the denominators come from different task distributions.

*What Parcel CAN legitimately claim:* "On our own 52-query corpus, applying the false-success definition of Sharma et al. (2026), N of our M failed queries exhibited false success (X%), against a published range of 13–79% among failures across 8 model families on τ²-bench." That is an honest, citable, apples-to-oranges-but-labeled comparison — and Parcel **cannot make it today**, because neither corpus run was scored with a false-success label. This is the largest single gap between Parcel's evidence and the current literature.

**Parcel's known instance, positioned:** "Done—I made a small circle around you" one second after admission is a textbook false success. **n=1 anecdote.** It is not a rate. Reporting it as a rate would itself be an over-claim. What Parcel has is an existence proof plus a 15-PARTIAL bucket in `replay_run_1` that very plausibly contains more, unlabeled.

### 4.2 Agent-Diff (arXiv 2602.11224, 2026-04-28) **[P]**

**What it measures.** 224 tasks across 4 enterprise services (Box 48, Slack 59, Linear 57, Google Calendar 60) in containerized API replicas. Agents write and execute code; evaluation is a **state diff** (Δadd/Δdel/Δmod over the full environment) checked against declarative assertions, **with a closed-world invariant** — any unexplained insertion, deletion, or mutation is treated as a side effect and **fails the task**. Two metrics: **Pass rate** (binary: clean AND all assertions satisfied) and **Score** (assertion-weighted). 3 trials × 3 documentation conditions = 2,016 traces. Task horizon n*: mean 5.3, range 1–24.

**Current numbers (no-docs, assertion-weighted overall):** deepseek-v3.2 **88.1 ± 2.4** (pass 76%), devstral-2512 86.0, qwen3-vl-235b 79.2, kimi-k2-0905 75.4, grok-4.1-fast 74.9 (pass 52%, **$0.01/test**, best cost efficiency at 7,489 Score/\$), gemini-3-flash 73.8, gpt-oss-120b 68.5, claude-haiku-4.5 **49.3**, llama-4-scout **38.0**. Cost range **$0.01–$0.22 per test**.

**On over-claiming:** *Hallucination* is one of five error causes in Agent-Diff's taxonomy (with Endpoint Selection, Parameter Errors, Execution Errors, Reasoning Failures, plus Incomplete Execution as a failure mode), annotated over 4,032 traces by a Gemini-3-Flash judge against a 31-type schema. Providing relevant API documentation reduces Hallucination by **−21.2 pp**. Figure 2 is an explicit worked example: Claude-Haiku-4.5 on "Organize Research Hub" attempts a nonexistent Collections API, receives null responses, and its final step is annotated ***"Hallucinates success."***

**Comparability: NOT comparable as a score; USEFUL as a method.** Enterprise SaaS APIs vs a robot dog share nothing. But two design choices are directly portable and Parcel should adopt both:
1. **The closed-world invariant.** Parcel's corpus scores whether the *intended* thing happened. Agent-Diff also fails a task for *unintended* state changes. Parcel has a person-yield navigator and a safety supervisor — an unintended pose change or an un-commanded gesture during a `get_status` query should fail, and today it probably scores PARTIAL.
2. **Cost per test as a first-class reported metric.** Parcel already has this: **$0.85 / 52 queries = $0.0163 per query**, which is inside Agent-Diff's $0.01–0.22 band. This is Parcel's most directly comparable number in the entire survey — with the enormous caveat that Parcel's per-query task is a single short utterance and Agent-Diff's is a mean-5.3-call code-executing workflow. Same units, wildly different work. Report it as an operating cost, never as an efficiency comparison.

### 4.3 KAware / KAPRO — "From Knowing to Acting" (arXiv 2606.20661, 2026-06-09) **[P]** — *capability honesty and tool overuse*

**What it measures.** Whether an agent accurately understands its own capability boundaries, by **decoupling knowing from acting**: *Knowing* = explicit metacognitive judgment of its own epistemic boundaries; *Acting* = spontaneous tool-use behavior in an unconstrained environment. 2×2 quadrant (Kc/Ac, Kc/Aw, Kw/Ac, Kw/Aw). **1,076 tasks** from 45 real-world APIs — External Function 310, Hybrid Composition 368, Internal Function 398; human verification agreement 96.45%. Metric **KAS** = harmonic mean of knowing and acting accuracy, penalizing cognition–behavior gaps.

**Current numbers:** GPT-5 avg KAS **69.73** (Internal-Function KAS 72.22); Claude-4.5-think 55.68 (Internal 21.84); Qwen3-max 51.99 (Internal 15.52).

**Key finding:** *high task completion masks poor self-awareness — models invoke tools unnecessarily, particularly on internal-only tasks, revealing systematic tool overuse despite "knowing better."*

**Comparability: PARTIALLY comparable — this is the frame for Parcel's fabricated-tool result.** Parcel's chat bench found **5/6 fabricated a junk `navigate_to` when the needed tool was absent from the surface**. That is precisely KAPRO's Kw/Aw quadrant, and precisely the "tool overuse" finding. The Internal-Function KAS column — where Claude-4.5-think collapses to 21.84 and Qwen3-max to 15.52 — shows this is a *severe, frontier-wide* failure, not a Parcel-specific one.

**Positioning:** Parcel's fabrication rate is **5/6 = 83.3%**, exact 95% CI **[36%, 100%]**. Inverted, that is a **16.7%** correct-abstention rate, CI **[0%, 64%]**. With n=6 this interval spans nearly the whole scale and Parcel cannot claim its rate is better or worse than any published model. What it *can* say: the phenomenon is real in Parcel, and it matches a documented frontier failure mode with a published taxonomy and a metric (KAS) it could adopt.

### 4.4 Berkeley Function Calling Leaderboard (BFCL) V4 — *irrelevance detection* **[S]**

**What it measures.** **IrrelAcc** = the fraction of `no_call` cases where the model correctly **abstains** from emitting a function call when presented with functions irrelevant to the query. V4 (ICML 2025) added an agentic layer: web search with error recovery, memory management, and **format sensitivity**. Board last updated **2026-04-12**; the live table renders client-side and I could not extract current per-model IrrelAcc.

**Reference points [S, treat as indicative only]:** GPT-4-0125-Preview **61.35%** irrelevance accuracy (Sept 2024 snapshot); Galileo's agent leaderboard reports Gemini-2.0-flash and Gemini-1.5-flash at **0.98** on an irrelevance-detection metric. The stated V4 headline is that top models excel at single-turn function calling but *continue to struggle with determining when not to invoke tools*.

**Comparability: PARTIALLY comparable — and this is the cheapest external number Parcel could plausibly claim.** BFCL's irrelevance category and Parcel's "tool absent from surface" cell measure **the same construct with the same scoring rule**: does the model abstain, yes or no. The transformation is small: (i) formalize Parcel's 7-tool surface as a BFCL-style function schema (it already is one, effectively); (ii) author `no_call` cases in Parcel's domain (requests the robot genuinely cannot serve: "unlock the front door," "call my mother," "tell me the weather"); (iii) score abstention binary.

**Caveat that must accompany any such claim:** BFCL's irrelevance cases draw from a broad API universe. A Parcel-domain irrelevance set is a *different, easier or harder* distribution, and the number would be Parcel-specific. Parcel could say "16.7% abstention on our 6-trial cell, against a benchmark where GPT-4-class models historically scored ~61% and current Gemini-class models ~98%" — labeled clearly as different task sets.

### 4.5 MASK (CAIS + Scale, arXiv 2503.03750) **[P]**

**What it measures.** **Honesty disentangled from accuracy.** First elicit the model's belief; then apply pressure to contradict it; measure whether it does. Honesty Score = **1 − P(Lie)**. 500 prompts in the private eval set, 7 archetypes: Known Facts 20.6%, Situation-Provided Facts 27%, Continuations 20.6%, Disinformation Generation 12.4%, Doubling Down 11%, Fabricated Statistics 8.4%.

**Current leaderboard (labs.scale.com/leaderboard/mask):** claude-opus-4-6 (non-thinking) **96.28 ± 0.41**; claude-sonnet-4-5-thinking 96.13 ± 0.57; Claude Sonnet 4 (Thinking) 95.33 ± 2.29; claude-opus-4-1-thinking 94.20; claude-opus-4-5-thinking 92.53. 60+ models, range **96.28 down to 42.40**. Original paper finding: LLMs lie **20–60%** of the time under pressure; honesty does **not** correlate with capability; an explicit "be honest" instruction improves honesty ~**12%** but does not eliminate lying.

**Comparability: NOT comparable.** MASK requires belief elicitation followed by pressure — a two-stage protocol Parcel's corpus does not implement. Parcel's `capability-honesty` category asks whether the robot admits it cannot do something; MASK asks whether a model will contradict a belief it demonstrably holds. Different constructs.

**Parcel's `capability-honesty 3/3 PASS`, positioned honestly:** **n=3.** Exact 95% CI **[36.8%, 100%]**. This interval includes "the true rate is 40%." It is compatible with essentially every model on the MASK board including the one at 42.40. **The 3/3 result carries no evidentiary weight whatsoever and should not appear in any external-facing claim.** It is a smoke test that passed. Its correct description is: "capability-honesty did not regress in the three cases we probed." Note additionally that MASK's finding that honesty is *uncorrelated with capability* is a warning specific to Parcel's substrate choice — moving to a bigger realtime model will not fix over-claiming.

### 4.6 TruthfulQA, HaluEval, Vectara HHEM — the old guard **[S]**

- **TruthfulQA:** adversarial questions designed to elicit human-plausible falsehoods. Frontier models now **80–90%** on closed-book factuality (TruthfulQA, FACTS Grounding), up from 50–65% in 2023.
- **HaluEval:** QA + dialogue hallucination detection; detector-side research now reports **AUC 0.994–0.998** on HaluEval-QA / TruthfulQA — the detection task is saturated.
- **Vectara HHEM:** summarization-grounding hallucination rate; frontier models **~1.0–2.5%** in 2026, down from 3–8% in 2023.
- Multi-step agent workflows, by contrast, are reported to hallucinate on **20–40% of tool-call chains** in 2026 benchmarks.

**Comparability: NOT comparable, and actively misleading if cited.** All three measure *propositional* hallucination — a false statement about the world's facts. Parcel's defect is *performative* over-claiming — a false statement about **its own action**, where the referent is a physical state the model has no access to. A model can score 90% on TruthfulQA and 99% on HHEM and still say "Done, I circled you" when it didn't, because the claim is not a fact-retrieval error. **The last gap between the two numbers above (1–2.5% summarization hallucination vs 20–40% tool-chain hallucination) is the whole story**: the classical hallucination benchmarks got solved and the failure moved somewhere they don't look. Parcel should cite that contrast rather than any TruthfulQA number.

---

## 5. (b) *What benchmark exists for appropriate silence / not over-speaking?*

**Answer: four partial ones, no canonical one, and the field acknowledges the gap.** The literature explicitly notes that current benchmarks "don't model missed response windows, interruption handling and overtalk — phenomena important to voice interactions but which don't surface in purely text interaction."

| Benchmark | Silence-relevant metric | What it captures | Published numbers |
|---|---|---|---|
| **τ-Voice** [P] | **Selectivity** | "Correctly ignoring backchannels, vocal tics, and non-directed speech" — responding only to genuine requests | OpenAI **6%**, Google 54%, xAI 57% (Realistic) |
| **Full-Duplex-Bench** [P] | **Takeover Rate (TOR)** on pause handling | Speaker pauses mid-turn; does the model barge in? Lower better | dGSLM 0.949; Moshi **1.000**; Freeze-Omni 0.672 |
| **EVA-Bench** [P] | **Turn-Taking** (timestamp, piecewise-linear latency curve) | Penalizes interrupting, **excessive silence**, AND failure-to-respond — the only metric that is two-sided | Best EVA-X pass@1 0.589 (Gemini-3.1-Flash-Live) |
| **"Reject or Not?"** (arXiv 2512.10257, 2025-12-15) [P, partial extraction] | Query **rejection** precision/recall/F1 | Smart-home voice: should the assistant refuse to act at all — illegal language, non-human sounds, ASR errors, uncertain replies. Explicitly designed "to prevent forced, unreasonable responses" | Numbers present in paper; PDF extraction was lossy, would need re-fetch |

**The OpenAI selectivity number is the most important line in this table for Parcel.** 6% selectivity means the hosted realtime lane treats almost all non-directed speech as a request. Parcel's owner is in a room, possibly with other people, and Parcel's mic is a reSpeaker array with no strong directional gate at the model layer. **The published expectation is that Parcel's hosted lane will speak when it should not, ~94% of the time it is given the chance.** Note also the τ-Voice OpenAI row's Responsiveness = **100%** — it responds to *everything*. High responsiveness and low selectivity are the same fact.

**Comparability of Parcel's evidence: NOT comparable — Parcel has measured none of this.**
- Selectivity/TOR both require *stimuli that should not be answered*: held pauses, backchannels, side conversation, non-directed speech. Parcel's 52-query corpus consists entirely of utterances that **should** be answered (its `estop-neg` and `safety-refusal` categories test wrong-*content* refusal, not wrong-*moment* silence). There is no query in Parcel's corpus whose gold label is "say nothing."
- Parcel's "silence" fix card addressed a *bug* (the lane going quiet), which is the opposite failure — the missed-response-window side of EVA-Bench's two-sided turn-taking metric. Parcel has fixed under-speaking and has never measured over-speaking.

**This is the largest unmeasured risk surface in Parcel's evidence base**, and it is cheap to close (§8, item 2).

---

## 6. Persona consistency

### 6.1 PersonaGym (EMNLP 2025 Findings) **[S]**

**What it measures.** Persona agents in **persona-relevant environments** (not static Q&A). 200 personas, 150 environments, ~10k auto-generated persona-specific questions. An LLM reasoner selects relevant environments per persona; the agent is probed across **five tasks**: Expected Action, Linguistic Habits, **Persona Consistency**, Toxicity Control, Action Justification. Each rated on a **1–5 rubric** by two strong LLM evaluators; aggregated into **PersonaScore**.

**Related boards:** CharacterEval (persona consistency across dialogue turns), PER-SIST (personality stability across model sizes and conversation histories), RPEval, PersonaArena (dynamic simulation), MOA. I could not retrieve a current per-model PersonaScore table from a primary source — treat the space as active but without a single canonical leaderboard.

**Comparability: NOT comparable.** PersonaGym's unit is a *persona* placed in *environments*; Parcel has **one** persona (the companion) and its corpus has **one** `persona` category among fifteen. A 1-persona, ~3-query sample against a 200-persona, 10k-question benchmark is not a measurement of the same thing. There is also a construct mismatch: PersonaGym's Persona Consistency asks "does this agent stay in character"; Parcel's persona category, in an embodied companion, is entangled with capability honesty (staying in character *includes* not promising things the body cannot do) — the two categories are not independent in Parcel and are independent in PersonaGym.

**What Parcel already has that is better-suited:** `evals/autorater/raters.py` defines a `PersonaConsistencyRater` and a `MultiTurnCoherenceRater` alongside a `HonestyRater` explicitly documented as *"truthfulness and groundedness only — the fault class that matters most."* That is a correct instinct that anticipates this entire section. What is missing is not a benchmark, it is **calibration**: an internal rater with no agreement statistic against humans cannot be positioned against PersonaGym's two-evaluator rubric. `personal_convo_v1` already has a `calibration/` directory and a frozen known-good/known-bad pack with drift disqualification — that machinery is the right shape and just needs to be pointed at persona.

---

## 7. Proactive / mixed-initiative dialogue

### 7.1 ClarifyMT-Bench (arXiv 2512.21120, 2025-12-25) **[P, partial]**

**What it measures.** Whether a conversational model **appropriately seeks clarification** on ambiguous or under-specified requests rather than proceeding on assumptions. Multi-turn scenarios; "should have clarified" labels are human-annotated. Reports **clarification frequency**, **over-clarification** (asking unnecessary questions), and **under-clarification** (failing to ask when needed). Explicitly distinguishes asking a necessary follow-up from answering prematurely despite ambiguity. (Exact per-model percentages are in the paper's results tables; my PDF extraction was lossy.)

### 7.2 Proactive-dialogue family **[S]**

- **ProactiveEval** (arXiv 2508.20973) — unified evaluation framework for proactive dialogue agents.
- **ProactiveBench (multimodal, arXiv 2603.19466, March 2026)** — 7 scenarios; defines proactiveness as *"the ability to either provide a correct answer or to ask for help, suggesting actions that could make the query answerable."* That definition maps almost exactly onto Parcel's `nav-invalid` / `unknown-place refusal` requirement.
- **ProactiveBench (video, arXiv 2507.09313)** — proactive web-video and **ego-centric** video QA, "particularly relevant in robotics and daily assistant applications"; introduces **PAUC**, the first metric accounting for the temporal dynamics of when a response arrives.
- **IN3** — decomposes proactive clarification into fuzzy-intent identification, missing-information completion, and intent summarization.

**Field-wide finding [S]:** a consistent **under-clarification bias** — most LLMs answer prematurely rather than clarify, and the bias **worsens as dialogue depth increases**.

**Comparability: PARTIALLY comparable — the construct matches Parcel's cleanest defect, the task set does not.**

Parcel's chat bench found **0/6 asked the required follow-up question from injected state**. That is a 0% clarification rate on a cell where clarification was gold. Exact 95% CI: **[0%, 39.3%]**. Two honest readings:

- The construct is unambiguously ClarifyMT-Bench's construct: gold said "ask," the model answered. This is under-clarification, and it aligns with the field-wide bias.
- **n=6 with 0 successes cannot distinguish "never clarifies" from "clarifies 35% of the time."** The upper bound of 39% is wide enough to include many published models. Parcel's honest statement is "0/6, consistent with the documented under-clarification bias, but the interval does not exclude middling performance."

*Transformation for a real number:* Parcel needs an ambiguity-graded corpus. ClarifyMT-Bench's construction is the template: for each Parcel scenario, produce a low-ambiguity variant (gold = act) and a high-ambiguity variant (gold = ask), so that **over-clarification is measured alongside under-clarification**. Parcel currently measures only one side, which means a naive fix — always ask — would look like a win and would be terrible for a companion robot. Agent-Diff's ambiguity grading (Low 101 / Medium 103 / High 20 of 224 tasks) is a concrete reference distribution for how much high-ambiguity mass to include.

---

## 8. (c) How published conversational scores translate — or fail to — for a robot companion

Four structural reasons the entire text-benchmark canon fails to transfer, in decreasing order of severity:

**1. The referent moves.** In MT-Bench, MultiChallenge, Arena, and TruthfulQA, the reply *is* the deliverable — the text is the thing being judged. In Parcel, the reply is a **report about a physical state the language model cannot observe**. "Done—I made a small circle around you" is not a bad sentence; it is a well-formed, warm, persona-consistent, on-brand sentence that a judge scoring conversational quality would **reward**. Every LLM-judge conversational benchmark would score that utterance higher than the correct one ("I've started — give me a moment"). This is not hypothetical: the false-success paper found that judges across 5 models and 5 prompt strategies latch onto *confident closing language* as a success proxy and cannot exceed AUROC 0.65. **Conversational-quality scoring is anti-correlated with the thing Parcel needs.**

**2. Timing becomes a correctness variable, not a UX variable.** In text, latency is a preference factor. In an embodied companion, the reply is *simultaneous* with motion, and the semantics of the reply depend on when it arrives relative to physical execution. EVA-Bench is the only benchmark surveyed that scores this two-sidedly (turn-taking penalizing both interruption and excessive silence), and even it treats it as "Experience" (EVA-X), not "Accuracy" (EVA-A). For Parcel, an early "Done" is an accuracy failure, not an experience failure. **No published benchmark scores it that way.**

**3. The rubric-vs-consequence asymmetry.** AudioMC passes a task only if all rubrics are satisfied; τ-Voice and EVA-Bench pass only if the final database state matches. Parcel has both a conversational surface *and* a physical consequence *and* a safety veto. It needs a **conjunctive** score — utterance correct AND tool correct AND args correct AND world state correct AND nothing unintended changed AND the safety layer was not the reason it looked correct. Parcel's PASS/PARTIAL/FAIL is an ordinal collapse of at least five independent binaries. That is why `replay_run_1`'s largest bucket is PARTIAL (15/41 adjudicated): PARTIAL is where the conjunction hides.

**4. Reliability, not average quality, is the operative metric.** τ-bench introduced **pass^k** ("all k attempts succeeded") precisely because average performance flatters unreliable systems. EVA-Bench reports a **median pass@k − pass^k gap of 0.44** — systems that look ~50% capable are ~6% reliable. For a robot in a home with an owner, pass^k is the only number that means anything. **Parcel has never reported a pass^k**, and its 52-query corpus is single-trial, so it structurally cannot. Its 6-trial chat cells are the only artifacts with k>1, and its 6/6 direct-navigation result is, in effect, an unreported **pass^6 = 1.0 on one cell** — genuinely the best number Parcel has, currently buried.

**One corollary Parcel should internalize:** the reason MT-Bench saturated at 9.0+ while `gpt-realtime-mini` scores 13.94% on AudioMC and the best EVA-Bench system scores 0.504 is that the general conversational benchmarks stopped measuring anything that binds. Parcel citing a text conversational benchmark would be citing a solved problem to describe an unsolved one.

---

## 9. Parcel's numbers, restated with intervals

Before any positioning, here is what Parcel's evidence actually supports. Exact (Clopper–Pearson) 95% intervals for the small cells, Wilson for the corpus.

| Parcel result | Rate | 95% CI | Comment |
|---|---|---|---|
| live_run_1 strict PASS / adjudicated (35) | 37.1% | [23.1%, 53.6%] | 3 blocked + 14 not attempted excluded; **pre-dates 5 fix cards** |
| live_run_1 PASS+PARTIAL / adjudicated | 62.9% | — | The lenient reading; not a defensible headline |
| live_run_1 strict PASS / all 52 | 25.0% | — | The pessimistic denominator |
| replay_run_1 strict PASS / adjudicated (41) | 24.4% | [13.8%, 39.4%] | **~20 verdicts describe a dead lane.** Not a product measurement. Do not report. |
| replay nav-direct | 5/5 | [47.8%, 100%] | |
| replay estop-pos | 3/3 | [36.8%, 100%] | Latched with the lane dead — an architecture result, not a model result |
| E1 recorded pack | 4/6 = 66.7% | [22.3%, 95.7%] | |
| Chat: correct tool+args, direct nav | 6/6 = 100% | [60.7%, 100%] | Effectively pass^6=1.0 on one cell |
| Chat: arrival-relation hints | 12/12 = 100% | [77.9%, 100%] | |
| Chat: self-consistency | 15/15 = 100% | [81.9%, 100%] | |
| Chat: fabricated tool when needed tool absent | 5/6 = 83.3% | [35.9%, 99.6%] | → abstention 16.7%, CI [0.4%, 64.1%] |
| Chat: asked required follow-up | 0/6 = 0% | [0%, 39.3%] | |
| Spoken e-stop, canonical | 7/7 = 100% | [65.2%, 100%] | ASR-variant positive **never tested** |
| capability-honesty (owner run) | 3/3 = 100% | [36.8%, 100%] | **Uninformative. Do not cite externally.** |
| Latency | chat p50 0.65s; realtime p50 0.78s, max 1.69s | — | **Turn-level, not first-token.** Not comparable to τ-Voice's 0.90s or FDB's onset latency |
| Cost | $0.0163/query ($0.85 / 52) | — | Same units as Agent-Diff's $0.01–0.22/test; vastly different work per test |

**And the caveat that dominates all of it:** both corpus runs pre-date the cards that fixed silence, scene answerability, memory recall, unknown-place refusal, and the safety ring. **The current build has never been measured on the corpus.** Every number above describes a build that no longer exists. The correct external statement is not "Parcel scores 37%" but "Parcel's last measured build scored 37.1% [23.1–53.6] strict on a 52-query single-turn corpus; the current build is unmeasured."

---

## 10. What Parcel would have to run to claim a benchmark number

Cheapest first. Each item names the existing artifact to reuse.

### Tier 0 — free, today, no new data collection

**0a. Re-score the two existing corpus runs with a false-success label.**
Reuse: `evals/20260820/voice_corpus_v1/live_run_1` + `replay_run_1`, and `evals/20260820/owner_session_1/ledger.json` + `session_slices.json` for ground-truth state.
For every FAIL and PARTIAL, apply Sharma et al.'s definition: did the spoken reply assert completion while the executive/navigator ledger shows the action did not occur? Report as **% of failures** (their denominator), with the ambiguous bucket separated (they found 35.6% FS / 43.5% honest / 20.9% ambiguous). Cost: analyst time only. This converts an n=1 anecdote into Parcel's first defensible honesty rate and unlocks a labeled comparison against a published 13–79% range.
*Blocker to be honest about:* `replay_run_1`'s post-q30 verdicts must be excluded, dropping n substantially. Do the labeling on `live_run_1` first.

**0b. Report pass^k where k>1 already exists.**
Reuse: the four-scenario chat bench (6 trials/cell).
Publish pass@1, pass@k and **pass^k** per cell, following τ-bench/EVA-Bench convention. Parcel's 6/6 direct-navigation cell is a pass^6 = 1.0 and is currently underclaimed. Cost: recomputation.

**0c. Decompose PASS/PARTIAL/FAIL into EVA-Bench's axes retrospectively.**
Reuse: same two corpus runs; `evals/autorater` (`HonestyRater`, `PersonaConsistencyRater`, `MultiTurnCoherenceRater`).
Re-label each verdict on four independent binaries — task completion, faithfulness, conciseness, turn-taking — mirroring EVA-A/EVA-X. The 15-PARTIAL bucket will resolve into something interpretable. Cost: one re-scoring pass.

**0d. Add cost-per-test and style-control to reporting.**
Reuse: the $0.85/52 figure; `evals/autorater`.
Report $0.0163/query in Agent-Diff's units with the work-per-test caveat. Separately, add Arena-Hard-style length/markdown control to `PairwiseQualityRater` so it stops rewarding the confident over-claiming reply.

### Tier 1 — one new small corpus each, reusing existing rigs

**1. A "should not answer" stimulus set → τ-Voice **selectivity** and Full-Duplex-Bench **TOR**.** *(highest value per dollar in this list)*
Reuse: `evals/companion/duplex_v1` (already gates TTFT p50 <1s via `query_end`→`tts_first_chunk`, already tests barge-in atomicity — the timing instrumentation exists), `evals/companion/acoustic_loop_v1` (rig + fixtures), `tools/run_voice_corpus.py`.
Record ~30 stimuli whose gold label is **silence**: mid-utterance held pauses, backchannels ("mm-hm", "uh…"), owner talking to a third party, ambient TV, a cough. Report **Takeover Rate** (Full-Duplex-Bench's definition) and **Selectivity** (τ-Voice's). Publishable claim: "Parcel's selectivity is X%, against a published 6% for the OpenAI realtime lane on τ-Voice." **This is the only place in this entire survey where Parcel could plausibly beat a published number**, because Parcel's local chain can gate on speaker identity and directionality in a way the raw hosted lane cannot. It is also currently Parcel's largest blind spot.

**2. A domain irrelevance set → BFCL-style IrrelAcc.**
Reuse: the existing 7-tool surface as the function schema; the chat-API bench harness; `evals/companion/planner_contract_size` for schema variants.
Author ~40 `no_call` cases in Parcel's domain ("unlock the door," "call my mother," "what's the weather," "order dog food") plus ~40 matched relevant cases. Score binary abstention. Turns the n=6, CI-[0.4%, 64%] fabrication finding into something with a usable interval, in BFCL's own metric, with the caveat that the case distribution is Parcel-specific.

**3. Ambiguity-graded clarification pairs → ClarifyMT-Bench-style two-sided score.**
Reuse: `evals/companion/conversation_quality_v1/cases.json` (frozen case format, manifest hashing, `human_review_required` discipline), `evals/companion/personal_convo_v1/probes` (eight sha-pinned probe families).
For each scenario author a low-ambiguity variant (gold = act) and a high-ambiguity variant (gold = ask), following Agent-Diff's Low/Medium/High mix. Report **under-clarification AND over-clarification**. Fixes the current one-sided 0/6 result, which is unfalsifiable in the "always ask" direction.

**4. Re-run the 52-query corpus on the current build.** *(not optional)*
Reuse: `tools/run_voice_corpus.py`, `evals/20260820/voice_corpus_v1/queries.tsv`, `record.sh`, the pre-registered gold labels.
Everything Parcel currently reports describes a superseded build. Until this runs, no Parcel number is a claim about the product. Add the Tier-0 false-success and EVA-axis labels to the scoring rubric *before* running, so the new run is born comparable.

**5. Test the untested ASR-variant e-stop positive.**
Reuse: `acoustic_loop_v1` fixtures + `make_impostor_wavs.py` (the impostor-wav machinery already exists and is the right shape).
Following VoiceBench's perturbation design: accent, reverberation, mispronunciation, partial occlusion. One unmeasured safety positive on a physical robot is worth more than every conversational metric in this document.

### Tier 2 — real external numbers, real cost

**6. Run public Full-Duplex-Bench v1 stimuli through Parcel's audio gateway.**
Reuse: `duplex_v1` runner, `acoustic_loop_v1` rig, and — importantly — the `evals/external/` pattern. Parcel has already built external-benchmark adapters (BARN ROS2 submission, Habitat PointNav OCI runtime, official doctors, promotion gates). That is precisely the harness discipline an external voice benchmark needs, and the team has done it before for navigation.
Yields Parcel's **first genuinely external, citable conversational number** — TOR against dGSLM/Moshi/Freeze-Omni on the benchmark's own stimuli. Caveat to publish alongside: this measures the hosted lane plus Parcel's gateway, not Parcel's disposition chain.

**7. Multi-turn extension of the corpus → AudioMC-shaped rubric scoring.**
Reuse: `personal_convo_v1` (already multi-turn, already sha-pinned session scripts, already has a Tier-D deterministic scorer bank, a PC-4 judge with a frozen calibration pack and drift disqualification, and a documented Tier-A/audio path).
Extend Parcel's 15 categories to 3–5 turn dialogues with per-turn rubrics; score with **all-rubrics-must-pass APR**, plus **ARS** as diagnostic. Report the **modality gap** by running the identical scripts through the text path (`personal_convo_v1` Tier T) and the audio path (Tier A) — this reproduces AudioMC's own text-vs-audio design and would let Parcel state its own modality gap against AudioMC's published 25.44 → 23.23 for GPT-4o Audio.

**8. Judge calibration before any judge-scored claim.**
Reuse: `evals/autorater`, `personal_convo_v1/calibration/`, `judge.py`.
Publish Cohen's κ against blinded human ratings, as AudioMC does (κ ≈ 0.87 with o4-mini). **And read the false-success paper's warning first:** LLM judges cannot detect false success (best AUROC 0.640), while a TF-IDF + logistic-regression detector reaches 0.849. Parcel should therefore **not** route over-claiming detection through `HonestyRater`. It should route it through a **programmatic state-diff check against the executive ledger** — which Parcel can do and τ²-bench-style setups can too, and which no judge can. `conversation_quality_v1`'s existing insistence that "keyword checks do not prove warmth" and that every result records `human_review_required: true` is the correct instinct; extend it to "LLM-judge checks do not prove non-over-claiming."

### The one-line recommendation

Do **0a**, then **1**, then **4**. In that order. `0a` converts Parcel's most distinctive defect from anecdote into a labeled rate using files that already exist; `1` closes the biggest unmeasured risk and is the only place Parcel's architecture could plausibly beat a published number; `4` makes any of it a statement about the product rather than about a build that no longer exists.

---

## Sources

**Preference/Elo:** [Arena text leaderboard](https://arena.ai/leaderboard/text) · [Arena-Hard-Auto](https://github.com/lmarena/arena-hard-auto/blob/main/README.md) · [Voice Showdown (Scale Labs)](https://labs.scale.com/blog/voice-showdown) · [LMArena background](https://metatext.io/benchmarks/lmarena-elo)

**Multi-turn:** [MT-Bench-101 (arXiv 2402.14762)](https://arxiv.org/abs/2402.14762) · [MultiChallenge (arXiv 2501.17399)](https://arxiv.org/abs/2501.17399) · [MultiChallenge leaderboard](https://labs.scale.com/leaderboard/multichallenge) · [MultiChallenge judge update](https://labs.scale.com/blog/multichallenge-update) · [AudioMC](https://labs.scale.com/leaderboard/audiomc) · [AudioMC audio-output board](https://labs.scale.com/leaderboard/audiomc-audio) · [AudioMC writeup](https://scale.com/blog/audiomc) · [MT-Bench status](https://futureagi.com/glossary/mt-bench-conversation-benchmark/)

**Voice-agent task benchmarks:** [τ-Voice (arXiv 2603.13686)](https://arxiv.org/html/2603.13686v1) · [EVA-Bench (arXiv 2605.13841)](https://arxiv.org/html/2605.13841v1) · [Full-Duplex-Bench site](https://full-duplex-bench.github.io/) · [Full-Duplex-Bench (arXiv 2503.04721)](https://arxiv.org/pdf/2503.04721) · [Full-Duplex-Bench repo](https://github.com/DanielLin94144/Full-Duplex-Bench) · [VoiceBench (TACL 2026)](https://aclanthology.org/2026.tacl-1.18/) · [tau2-bench](https://github.com/sierra-research/tau2-bench)

**Honesty / over-claiming:** [False Success (arXiv 2606.09863)](https://arxiv.org/abs/2606.09863) · [Agent-Diff (arXiv 2602.11224)](https://arxiv.org/pdf/2602.11224) · [KAware/KAPRO (arXiv 2606.20661)](https://arxiv.org/abs/2606.20661) · [MASK (arXiv 2503.03750)](https://arxiv.org/pdf/2503.03750) · [MASK leaderboard](https://labs.scale.com/leaderboard/mask) · [BFCL V4](https://gorilla.cs.berkeley.edu/leaderboard.html) · [BFCL V4 explainer](https://benchmarkingagents.com/bfcl-function-calling/) · [BeHonest (arXiv 2406.13261)](https://arxiv.org/pdf/2406.13261) · [Hallucination rate benchmarks 2026](https://presenc.ai/research/ai-hallucination-rate-benchmarks-2026)

**Silence / rejection:** [Reject or Not? (arXiv 2512.10257)](https://arxiv.org/pdf/2512.10257) · [Third-party interruption robustness (arXiv 2604.17358)](https://arxiv.org/html/2604.17358) · [EchoChain (arXiv 2604.16456)](https://arxiv.org/pdf/2604.16456)

**Persona:** [PersonaGym (EMNLP 2025 Findings)](https://aclanthology.org/2025.findings-emnlp.368.pdf) · [PersonaArena (arXiv 2605.17044)](https://arxiv.org/pdf/2605.17044)

**Proactive / clarification:** [ClarifyMT-Bench (arXiv 2512.21120)](https://arxiv.org/pdf/2512.21120) · [ProactiveEval (arXiv 2508.20973)](https://arxiv.org/html/2508.20973) · [ProactiveBench multimodal (arXiv 2603.19466)](https://arxiv.org/html/2603.19466v1) · [ProactiveBench video (arXiv 2507.09313)](https://arxiv.org/html/2507.09313v1)

**Model:** [gpt-realtime-2.1 release](https://datanorth.ai/news/openai-releases-gpt-realtime-2-1-voice-models) · [gpt-realtime-2.1-mini pricing](https://llmgateway.io/models/gpt-realtime-2.1-mini)