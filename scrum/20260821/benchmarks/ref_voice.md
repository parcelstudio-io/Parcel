# Spoken-Assistant & End-to-End Latency Benchmarks vs. Parcel's Evidence

**Researcher angle:** voice/spoken-dialogue evaluation, ASR under far-field home conditions, wake-word FAR/FRR methodology, speaker-verification EER, and conversational latency norms. Verdicts are deliberately harsh: of eleven benchmark families surveyed, **zero are directly comparable to Parcel as measured**, three are partially comparable after a defined transformation, and the rest are category errors.

---

## 0. Headline verdict

Parcel currently has **no number that can be placed on any published leaderboard**, and two of its most-quoted figures (7/7 e-stop, 0.799-vs-0.252 speaker separation on 378 pairs) are statistically much weaker than they sound. The closest published analogue to what Parcel actually does — spoken query → tool call + arguments — is **VoiceAgentBench** (Oct 2025), and the second closest is **BFCL Audio** / **Full-Duplex-Bench-v3** (Apr 2026). Parcel's existing artifacts could be re-scored into VoiceAgentBench/SLURP-shaped metrics **at zero marginal cost**, which is the single highest-leverage move available.

The critical framing constraint stands throughout: **both 52-query corpus runs predate the five fix cards.** Every comparison below is therefore a comparison to a build that no longer exists.

---

## 1. VoiceBench (TACL 2026) — the reference spoken-assistant benchmark

**What it actually measures.** 6,783 spoken instructions across 9 datasets, testing *general knowledge, instruction-following, and safety refusal* for LLM-based voice assistants. Composition (Table 2): AlpacaEval 636 (subset AlpacaEval\* 199), CommonEval 200 (real human speech), SD-QA 553 (real, accented), OBQA 455, MMSU 3,074, BBH 1,000 (real, MTurk-recorded), IFEval 345, AdvBench 520. Mean 39.68 words / 17.39 s audio; capped at 30 s.

**Scoring rule (heterogeneous, which matters).** AlpacaEval and CommonEval: GPT-4o-mini judge, 1–5 scale, **×20 to normalize to 100**. SD-QA: accuracy, averaged over PANDA and GPT evaluation. OBQA/MMSU/BBH: rule-based letter/answer extraction accuracy. IFEval: mean of 4 accuracies (loose/strict × prompt/instruction). AdvBench: **refusal rate** (higher = safer), detected by predefined refusal phrases. Overall = unweighted mean of the per-task scores. Human validation: Spearman 0.92 (AlpacaEval), 0.92 (CommonEval), 0.94/0.92 (SD-QA); Fleiss κ 0.53 / 0.66 / 0.95.

**Current representative scores.**

| System | VoiceBench Overall | Date / source |
|---|---|---|
| LFG-3 (Audio-LLM) | **89.88** | live leaderboard, Aug 2026 |
| NVIDIA Nemotron 3 Nano Omni 30B A3B | 89.39 | live leaderboard, Aug 2026 |
| Ultravox-GLM-4P7 | 88.86 | live leaderboard, Aug 2026 |
| Ultravox-v0.6-LLaMA-3.3-70B *(mid-tier)* | 81.81 | live leaderboard, Aug 2026 |
| Whisper-v3-large + LLaMA-3.1-8B *(mid-tier cascade)* | 77.48 | live leaderboard, Aug 2026 |
| Naive-4o cascade (Whisper-v3 + GPT-4o), speech-form | 87.23 (text-form 89.75) | TACL paper Table 4, pub. Apr 2026 |
| GPT-4o-Audio (E2E) | 86.14 | TACL Table 4 |
| GPT-4o-mini-Audio | 82.20 | TACL Table 4 |
| Qwen2-Audio / DiVA / VITA / LLaMA-Omni / Moshi | 55.26 / 55.22 / 36.31 / 38.96 / 29.97 | TACL Table 4 |

**Comparability: NOT COMPARABLE.** Different task (open-domain QA and formatted text generation vs. tool dispatch), different denominator (6,783 vs. 52), different scoring (LLM-judge 1–5 and multiple-choice accuracy vs. pre-registered PASS/PARTIAL/FAIL verdicts), different output space (free text vs. a 7-function surface). There is no transformation that makes Parcel's 13/52 or 10/52 a VoiceBench number.

**What *is* transferable** is a methodological finding that vindicates Parcel's architecture: cascaded pipelines beat open end-to-end speech models by **>20 points**, and the text→speech degradation for the naive cascade is only **4.37 points** (2.52 for Naive-4o) versus **>35 points** for VITA. Parcel's "hosted model proposes, local deterministic chain disposes" split is the same insulation principle, and VoiceBench is the citation for why it is the right call. That is a *design* argument, not a score.

One nuance worth flagging internally: VoiceBench notes Qwen2-Audio beats Whisper-large-v3 on LibriSpeech test-clean WER (**1.6 vs. 1.8**) yet is 30+ points worse on VoiceBench — i.e. **low WER does not predict assistant quality**. That is directly relevant to how Parcel should weight its ASR anecdotes.

---

## 2. VoiceAgentBench (Oct 2025) — *the closest published analogue to Parcel*

**What it measures.** 6,134 synthetic spoken queries; English 38.75% (≈2,377) plus six Indic languages. Categories: Single Tool Calling 1,386 (22.6%), Single Tool with Retrieval 1,451 (23.7%), Parallel Tool Calling 1,070 (17.4%), Sequential Dependent 320 (5.2%), Multi-turn 1,171 (19.1%), Safety 736 (12.0%).

**Scoring rule — four metrics, and this is exactly the schema Parcel should adopt:**
- **TS (Tool Selection):** correct tool invoked, regex exact-match on tool name, format-agnostic.
- **TCS (Tool Call Structure):** output validates against the Pydantic schema.
- **PF (Parameter Filling):** arguments match ground truth; GPT-4o-mini judge for semantic faithfulness.
- **RR (Refusal Rate):** for the safety split.

**Audio generation:** ElevenLabs → Coqui-TTS voice conversion, speaker diversity enforced via ECAPA-TDNN embeddings + Farthest-Point Sampling. **No background noise** (acknowledged limitation).

**Current representative scores (English subset, Table 2):**

| Model | Single-Tool PF | Single-Tool+Retrieval PF | Safety RR |
|---|---|---|---|
| Whisperv3 + Llama3 70B (cascade, best overall) | 71.97% | 78.79% | 38.97% |
| Whisperv3 + Gemma3 27B | 72.65% | 73.10% | 59.56% |
| Whisperv3 + Qwen3 8B | 72.26% | 77.00% | 55.97% |
| KimiAudio 7B (E2E SpeechLM) | 75.78% | 70.49% | 51.78% |
| Qwen2.5-Omni 7B (E2E) | **1.33%** | 0.00% | 19.72% |

Best average PF across all English tasks: **60.6%**; on Indic, 39.2%. **No model exceeds 70% PF on any task.** Same architectural finding as VoiceBench: ASR→LLM cascades beat E2E on parameter filling.

**Comparability: PARTIALLY COMPARABLE.** Same task shape. Required transformations before any comparison:
1. **Re-score Parcel's corpus into TS / TCS / PF / RR.** Parcel's PASS/PARTIAL/FAIL collapses tool-selection errors, argument errors, and schema errors into one bucket; VAB separates them. Parcel has pre-registered gold labels per query, so this is a **pure re-labelling of existing artifacts** — no new runs.
2. **Difficulty is not matched, and the mismatch favours Parcel heavily.** VAB's single-tool split draws from a large open catalog with a retrieval step; Parcel picks from **7 fixed functions**. A 7-way closed choice is a fundamentally easier problem than VAB's. Any Parcel TS number must be reported next to "|tools| = 7".
3. **Acoustics run the other way.** VAB is clean TTS with no noise; Parcel's live_run_1 is a real owner's voice through a reSpeaker array. Parcel's condition is harder acoustically, easier semantically.
4. **n is 46× smaller** (52 vs. 2,377 English).

**Positioning, with caveats.** Parcel's chat-API bench result of **6/6 correct tool+args on direct navigation** is a PF-shaped number and is nominally above VAB's ceiling (~72–76%). But 6/6 has a **95% Clopper-Pearson interval of [54.1%, 100%]** — it does not establish superiority over a 72% system; it does not even exclude a 55% system. The **5/6 fabrication rate when the needed tool was absent** (95% CI [35.9%, 99.6%]) is the more informative result and it maps onto VAB's safety/refusal axis, where the *best* published RR is 59.56% — i.e. fabricating under an inadequate tool surface is a well-documented, unsolved industry failure mode, not a Parcel-specific defect. That is a defensible framing; "we beat VAB on PF" is not.

---

## 3. BFCL Audio (Salesforce AI Research × Berkeley, 2025)

**What it measures.** Audio-native extension of the Berkeley Function Calling Leaderboard: AST-style function-call correctness from spoken input.

**Current representative finding.** Pipelined ASR+LLM systems drop **~10–20% relative to text-mode BFCL**, driven predominantly by **entity dictation failures** (proper nouns, IDs, alphanumerics transcribed wrong). End-to-end audio models degrade **more** than pipelines. E2E wins on naturalness/responsiveness; pipelines win on function calling.

**Comparability: NOT COMPARABLE as measured, but the cheapest benchmark for Parcel to *emulate*.** Parcel does not run BFCL's tool catalog or its AST scorer. However, Parcel already has the single most relevant BFCL-style datum — the **5/6 junk-`navigate_to` fabrication when the required tool was absent** — which is precisely BFCL's *irrelevance detection* axis. Parcel's `navigate_to` also carries place-name arguments, so BFCL Audio's entity-dictation finding predicts exactly Parcel's `"Walk to the bench"` failure class.

**Transformation needed:** define a fixed irrelevance/out-of-surface subset (30–50 prompts whose only correct behaviour is refusal or a clarifying question) and score refusal rate. Reuses the existing chat-API bench harness verbatim.

---

## 4. Full-Duplex-Bench v1 (ICASSP-track, arXiv 2503.04721) and v3 (Apr 2026)

### v1 — turn-taking behaviour

**What it measures.** Four dimensions with automatic metrics; ASR via `nvidia/parakeet-tdt-0.6b-v2` for word-level alignment. Sample counts (Table II): Candor pause handling 216, Candor smooth turn-taking 119, ICC backchannel 55, synthetic user interruption 200, synthetic pause handling 137.

**Metrics.** **TOR** (Takeover Rate) = mean of a binary per-turn variable, 0 if the model stays silent or backchannels, 1 for any other non-silent speech. Lower is better for pause handling, higher for turn-taking. **Backchannel Freq** (events/sec) and **JSD** against a human-annotated ground-truth backchannel timing distribution over 200 ms windows. **Latency** = seconds from end of user speech to start of model response, computed **only when TO = 1**.

**Current representative scores (Table III):**

| Model | Smooth turn-taking TOR ↑ | Turn-taking latency ↓ | Interruption latency ↓ | GPT-4o interruption score ↑ |
|---|---|---|---|---|
| Moshi | 1.000 | **0.265 s** | **0.257 s** | 0.765 |
| dGSLM | 0.975 | 0.352 s | 2.531 s | 0.201 |
| Freeze-Omni (cascade) | 0.336 | 0.953 s | 1.409 s | **3.615** |
| Gemini Live (`gemini-2.0-flash-live-001`) | 0.655 | 1.301 s | 1.183 s | 3.376 |

Key human baseline cited: smooth conversational transitions in English typically occur within **200–250 ms**; pauses up to ~1 s are perceived as natural.

**Comparability: NOT COMPARABLE.** Parcel is half-duplex, single-turn, VAD/mic-gated. It has no backchannel behaviour, no barge-in handling, and no overlapping-speech capability. TOR is undefined for it. **Do not cite FDB v1 as a Parcel comparison.** The one usable import is the **latency clock definition** (end-of-user-speech → start-of-model-response), and the observation that a *cascaded* system (Freeze-Omni, 0.953 s) and a commercial full-duplex system (Gemini Live, 1.301 s) both sit in the ~1 s band — the same band Parcel's 0.78 s claims.

### v3 — tool use under real-world disfluency (Apr 6, 2026)

**What it measures.** **100 recordings from 12 speakers**, everyday built-in microphones (11 of 12 setups), quiet rooms to mild background noise, real ambient trailing silence. Five annotated disfluency categories (false starts, self-corrections, fillers, pauses, hesitations); **21 scenarios feature mid-utterance intent change** requiring downstream API-parameter rollback. Four domains, deterministic outputs, automatic scoring.

**Metrics.** **Pass@1** = binary; requires the agent to invoke *exactly* the expected tools *and* achieve perfect argument accuracy on every call — any single failure is a fail. **Latency** = Δt = t_agent_start − t_user_end, split into First Response, Tool Call, and Task Completion latency. **Turn-Take Rate** = fraction of turns with natural-timing response. **Interruption Rate** = negative-latency events.

**Current representative scores:**

| Model | Pass@1 | Latency (s) | Turn-take | Interrupt % |
|---|---|---|---|---|
| GPT-Realtime | **0.600** | 6.89 | 96.0% | **13.5%** |
| Gemini Live 3.1 | 0.540 | **4.25** | 78.0% | 19.2% |
| Gemini Live 2.5 | 0.490 | 7.26 | 92.0% | 14.1% |
| Cascaded (Whisper→GPT-4o→TTS) | 0.450 | 10.12 | **100.0%** | 33.0% |
| Grok | 0.430 | 6.65 | 94.0% | 25.5% |
| Ultravox v0.7 | 0.410 | 8.40 | 96.0% | 47.9% |

**Comparability: PARTIALLY COMPARABLE — and this is the benchmark whose *definitions* Parcel should adopt wholesale.**
- **Pass@1 is definitionally close to Parcel's PASS verdict** (exact tools + perfect args). But FDB-v3 scenarios are **multi-step chained API calls**; Parcel's corpus is single-turn single-call. Parcel's task is materially easier, so a Parcel Pass@1 must be labelled "single-step".
- **Latency is not comparable as reported.** FDB-v3's 4.25–10.12 s figures are *task-completion-inclusive*, multi-step, and tool-execution-inclusive; Parcel's 0.78 s is a single-turn, no-chained-call figure. These are different quantities. Parcel's number is not "8× faster than GPT-Realtime."
- **Acoustic condition is genuinely well matched** — everyday built-in mics, mild noise, real human disfluency — which makes FDB-v3 the best available reference for what Parcel's live_run_1 condition should be expected to yield. That GPT-Realtime achieves only **0.600 Pass@1** on 100 real-human disfluent scenarios is the single most useful external anchor for Parcel: it says that ~40% failure on real speech with a competent hosted realtime model is *the current state of the art*, not evidence of a broken build.

---

## 5. Audio MultiChallenge (Scale AI, arXiv 2512.14865)

**What it measures.** Multi-turn spoken dialogue: instruction following, prior-context integration, self-consistency, and handling of natural speech corrections. **452 conversations / 1,712 binary rubrics.** Built entirely from human speech with disfluencies, interruptions, non-monotonic phrasing, ambient noise. Evaluated in both text-output and audio-output modes to expose the modality gap.

**Scoring rule.** A task passes **only if all its rubrics are satisfied**; primary metric is Average Pass Rate. Judge: `o4-mini`.

**Current leaderboard:** Inkling (Thinking) 56.64% ±4.55 · Inkling-small 54.87% ±4.57 · Gemini-3-pro-preview (Thinking) 54.65% ±4.57 · **GPT-realtime-2 (xHigh) 48.45% ±4.59** (up from GPT-Realtime-1.5's 34.73%) · Gemini-2.5-flash (Thinking) 40.04% ±4.50 *(mid-tier)* · GPT-4o-audio-preview-2025-06-03 25.44% ±4.00 · Qwen3-Omni-30B-A3B-Instruct 24.34% ±3.95.

**Comparability: NOT COMPARABLE.** Parcel's corpus is explicitly **single-turn**. AudioMC's entire content is multi-turn context carryover and mid-dialogue correction. Parcel has no measured multi-turn behaviour at all.

**Worth noting anyway:** the best model in the world passes **56.64%** of multi-turn spoken tasks, and the published ±CIs are ±4.5pp at n=452. If a 452-conversation benchmark carries ±4.5pp, a 52-query corpus with ~3.5 items per category carries **±20–35pp per category** — see §11.

---

## 6. SD-Eval (NeurIPS 2024)

**What it measures.** Spoken dialogue *understanding beyond words*: whether a response is appropriate given emotion, accent, age, and background sound. 7,303 utterances / 8.76 hours, aggregated from eight public datasets across four sub-tracks.

**Scoring:** BLEU, ROUGE, subjective human evaluation, and LLM-based metrics (the last correlating best with humans).

**Comparability: NOT COMPARABLE.** Parcel produces tool calls, not free-form empathetic responses, and does not condition on paralinguistics at all. There is no denominator overlap and no scoring-rule overlap. Skip.

---

## 7. SLURP / MAC-SLU — the classical command-grammar analogues

**SLURP (2020, still the standard SLU reference).** 72,000 audio recordings, 18 domains; 50,628 audio files with 8,690 dev / 13,078 test. Metrics: **Intent Classification accuracy** and **SLU-F1** (a span-F1 variant designed to capture semantic mislabeling *and* textual misalignment). Representative results: an ASR+NLU pipeline with synthetic data reaches **74.6% IC**, rising to **78.3%** with additional ASR data.

**MAC-SLU (arXiv 2512.01603, Dec 1 2025).** Multi-intent automotive-cabin SLU — structurally the nearest published cousin to a robot command surface. Mandarin, 8 domains, **81 intents, 192 slots**, 20,539 samples (17,997/1,391/1,151). Up to 5 independent intents per utterance; 28% zero-intent, 56.54% single-intent, 12.63% two-intent. **Clean synthetic speech** (CosyVoice-2 TTS over AIShell-1 speaker templates), no far-field or noise. Metrics: IC accuracy, SF F1, and **Overall Accuracy** = both simultaneously correct.

| System | IC | SF F1 | Overall |
|---|---|---|---|
| Paraformer + Qwen3-8B (best cascade) | 88.92% | 79.09% | 47.18% |
| Qwen2.5-Omni-7B (best E2E) | 91.24% | 83.02% | **55.60%** |

**Comparability: PARTIALLY COMPARABLE — and this is the cheapest path to a benchmark-shaped Parcel number.** Parcel's structure maps cleanly: its 15 gold categories ≈ intents, its tool arguments ≈ slots, its PASS ≈ joint accuracy. The mapping requires:
1. Recasting the 52 pre-registered gold labels as explicit (intent, slot-value) tuples — **a pure re-annotation of an existing artifact**.
2. Reporting **IC accuracy, slot F1, and joint accuracy separately** instead of the PASS/PARTIAL/FAIL trichotomy. PARTIAL almost certainly corresponds to "IC correct, SF wrong" — which is *exactly* the distinction MAC-SLU's Overall-vs-IC gap captures (88.92% IC → 47.18% Overall).
3. Loud caveats: n=52 vs. 1,151 test; **7 intents vs. 81**; real far-field audio vs. clean TTS.

Note the shape of the MAC-SLU result: **IC ~89–91% but joint only 47–56%.** If Parcel's re-scored corpus shows the same pattern — high tool-selection accuracy, much lower joint accuracy — that is *the industry-normal profile*, and framing it that way is both honest and favourable.

---

## 8. ASR word-error-rate expectations for far-field arrays in home conditions

### The three reference bands

**(a) Near-field / read speech — the floor.** Open ASR Leaderboard (arXiv 2510.06961, English short-form average over LibriSpeech clean+other, AMI, Earnings22, GigaSpeech, TED-LIUM v3, SPGISpeech, VoxPopuli): Cohere Labs Transcribe **5.42%** (525 RTFx), Zoom Scribe v1 5.47%, IBM Granite Speech 4.0 1B 5.52% (280 RTFx), NVIDIA Parakeet TDT 0.6B v2 6.05% (3390 RTFx), **OpenAI Whisper Large v3 7.44%** (146 RTFx), NVIDIA FastConformer CTC Large 8.96% (6400 RTFx). On LibriSpeech test-clean alone, Whisper-large-v3 is **1.8%** and Qwen2-Audio **1.6%**.

Commercial index (Artificial Analysis AA-WER, weighted AA-AgentTalk 50% / VoxPopuli-Cleaned 25% / Earnings22-Cleaned 25%, ~8 h audio): Fun-Realtime-ASR-preview **1.7%**, ElevenLabs Scribe v2 2.2% (57.0× realtime, $3.67/1000 min), Azure MAI-Transcribe-1.5 2.4% (187.5×), Smallest.ai Pulse Pro 2.4% (278.2×), Voxtral Small 2.8% (best open-weights). Fastest: Deepgram Nova-3 at 542.1× realtime.

**(b) Far-field multi-party conversational — the ceiling of difficulty.** CHiME-8 DASR (ISCA 2024) eval-set **tcpWER**: ESPnet baseline CHiME-6 **99.1%**, DiPCo 56.6%, Mixer 6 43.8%, NOTSOFAR-1 50.7%, **macro 62.6%**; NeMo baseline CHiME-6 73.8%, DiPCo 57.1%, Mixer 6 23.1%, NOTSOFAR-1 72.0%, **macro 56.5%**. Best submitted systems (STCON 1st, NTT 2nd; USTC won the multi-channel track): NTT reports **macro tcpWER 21.3% on dev**, a 57% relative gain over baseline, with its strongest system at **63% relative improvement**. Scenario statistics explain why: CHiME-6 eval is 26.7% overlapped speech, NOTSOFAR-1 eval 29.6%.

**(c) Where Parcel actually sits — neither band.** Single speaker, cooperative, no competing talkers, close-ish reSpeaker array, short commands. This is far easier than CHiME and harder than LibriSpeech. A defensible expectation is **3–10% WER**, i.e. roughly Whisper-large-v3-on-AMI territory.

### What Parcel's specific failures imply

Parcel's three observed errors are **not one phenomenon**, and a single WER would destroy that information:

| Observed | Class | Diagnosis |
|---|---|---|
| `"Stop."` → `"Top"` | **Onset deletion on a monosyllable** | `/s/` is a low-energy, high-frequency fricative — the first thing lost to distance attenuation, AGC, and noise gating. Entirely predicted by far-field physics. |
| `"Dye stop"` → `"Dice top"` | **Resyllabification across a word boundary** | Classic for short phrases with no language-model context to disambiguate. |
| `"Walk to the bench"` → `"Let's move the bench a step out of sight"` | **Decoder hallucination / continuation, NOT a transcription error** | A 4-word command becoming an 11-word unrelated sentence is a generative-decoder failure mode on short, low-SNR segments. This is a *different bug* and would be masked inside a corpus WER. |

**The load-bearing point: WER is the wrong metric for a command grammar.** WER is length-weighted — errors are normalized by reference word count. Parcel's utterances are 1–5 words. A one-word utterance yields WER of exactly 0% or 100%; there is no gradation, and a corpus WER computed over such utterances has enormous variance and near-zero diagnostic value. Worse, **short utterances have systematically higher error rates than the corpus average** precisely because they carry no LM context — so a "5% WER" model will fail on single-word commands far more often than 5% of the time. VoiceBench makes the same point empirically from the other direction: Qwen2-Audio beats Whisper on LibriSpeech WER (1.6 vs. 1.8) yet is 30+ points worse as an assistant.

**Correct metrics for Parcel:** **Utterance/Command Error Rate** (did the whole command transcribe correctly — the only thing that matters when the downstream consumer is an exact-match router) and a **separate hallucination-event count** (output token count ≫ input duration). Both are computable from audio Parcel has already recorded.

**Comparability verdict: NOT COMPARABLE.** Parcel has three anecdotes, no WER, no CER, no transcript corpus with references. Nothing can be positioned against any of the numbers above until a reference-transcript set exists.

---

## 9. Wake-word / e-stop: FAR-FRR methodology and Parcel's phrase design

### Industry methodology

The non-negotiable convention: **FRR is reported at a fixed FAR, and FAR is expressed in false accepts per hour, never as a percentage.** Percentage FAR is meaningless because it has no defined denominator. Standard operating points: **1 false alarm per 10 hours** (Picovoice benchmark convention) or **<0.5/hour with <5% FRR** (openWakeWord's stated target). Results are presented as **DET curves**, since FAR and FRR trade off continuously against a threshold.

Reference measurements:
- **Picovoice wake-word benchmark:** LibriSpeech `test_clean` as background plus 300+ recordings of six keywords from 50+ speakers, mixed with DEMAND noise at **10 dB SNR** across 18 environments; engines compared at a **fixed 1 FA / 10 h**.
- **openWakeWord:** false accepts measured against the **Dinner Party Corpus** (~5.5 h of far-field speech, background music, and miscellaneous noise); target **<5% FRR at <0.5 FA/h**; the authors explicitly caution that their competitor comparisons have small sample sizes.
- **Hey Snips (arXiv 1811.07684)** established the open reference: 2.2K+ speakers. Published operating points on it include **1.02% FRR at 1.0 FA/h** (~84K-parameter attention model), 1.60% FRR in noise, and streaming decoders reaching **0.05 FA/h**.

### Phrase-design engineering standards

Consensus guidance across vendors: **3–5 syllables** (some say 4–5); **phonetically diverse** with a mix of consonant and vowel sounds to produce an acoustic signature distinct from background speech; and **not a word common in surrounding conversation** — "Hello," "Thanks," "Okay" are explicitly named as causing accidental activations.

### Verdict on Parcel's e-stop design: **UNSOUND by these standards**

`"Stop."` violates all three criteria simultaneously:
1. **One syllable** — the minimum-information case, well below the 3–5 floor, offering the detector almost no acoustic evidence.
2. **Phonetically fragile** — `/stɑp/` opens with a low-energy fricative that is the *first* casualty of far-field attenuation. Parcel's own `"Stop." → "Top"` failure is textbook, predictable, and not a fluke.
3. **Extremely common in ordinary speech** — "stop it," "bus stop," "stop by," "don't stop." Every one of those is a latent false-accept for a robot that will physically halt.

`"Dye stop"` (evidently an ASR-variant probe) is worse, not better: it is a two-syllable near-homophone pair whose components are individually common, which is why it resolved to `"Dice top"`.

**Parcel's evidence against this methodology: NOT COMPARABLE — it does not measure either axis.**
- **FRR arm:** 7/7 canonical positives. Clopper-Pearson 95% interval is **[59.0%, 100%]**. Rule of three gives an upper bound on the failure rate of **3/7 = 43%**. Seven trials cannot distinguish a 99%-reliable e-stop from a 60%-reliable one. And the one **ASR-variant positive was never tested at all** — the exact case the observed transcription failures predict will break.
- **FAR arm:** **entirely unmeasured.** Parcel has zero hours of negative/ambient audio. FAR per hour is undefined. There is no threshold, no DET curve, no operating point.

**Two structural points that matter more than the numbers:**

1. **A voice e-stop is not an e-stop.** ISO 13850 requires the emergency-stop function to be initiated by a **manually actuated device with positive (direct mechanical) operation** — pushbuttons, wires, ropes, bars, foot pedals. Voice actuation, mediated by a network and a hosted model, cannot satisfy positive operation. The correct framing is: the voice channel is a **convenience trigger**; the safety function must be a hardware actuator plus the local latch. Marketing a spoken phrase as "the e-stop" is a claim Parcel should not make.

2. **Parcel's replay_run_1 accidentally produced its most valuable safety evidence.** estop-pos went **3/3 with the hosted lane dead at q30**. That demonstrates the *local latch* is the actual safety function and is independent of the model — which is architecturally correct and is the thing worth benchmarking. It is also only 3 trials (95% CI **[29.2%, 100%]**), so it is currently an anecdote about a good design rather than a measurement of one. Deliberate fault injection would convert it into real evidence cheaply.

---

## 10. Speaker verification: positioning 0.799 vs. 0.252 on 378 pairs

### Reference points

**Test-list sizes (the denominator problem).** VoxCeleb1-O: **37,611 trials / 40 speakers**. VoxCeleb1-E: 579,818 trials / 1,251 speakers. VoxCeleb1-H (hard: same nationality *and* gender, 18 nationality-gender groups): 550,894 trials / 1,190 speakers. VoxSRC-2023's combined eval set is ~**1.7 million pairs**.

**Current EER reference points (VoxCeleb1-O):**

| System | EER | Date |
|---|---|---|
| w2v-BERT 2.0 + KD-guided structured pruning | **0.12%** | Mar 2026 |
| Best single-model SOTA | 0.170% (minDCF 0.006) | 2025–26 |
| Reported strong system, no post-processing | 0.228% | 2025 |
| SSL + ECAPA-TDNN range *(mid-tier)* | 2.53–2.57% | 2024–25 |

**VoxSRC challenge trajectory (retrospective, arXiv 2408.14886, Table III), all on the 2019 test set:** ResNet-34 baseline **1.29%**; 2019 winner 1.42%; 2020 winner 0.83%; 2021 winner 0.57%; 2022 winner 0.69% (2nd place 0.59%); 2023 winner **0.47%**. On each year's *own* (harder) test set the same baseline scores **5.01 / 5.00 / 5.26 / 5.45%** and winners score 3.73 / 1.85 / 1.49 / 1.59%. Self-supervised track baseline: **12.67%** on 2019 test.

**The methodological warning from the same paper, which is the crux:** bootstrap 95% confidence intervals on winning EERs have **minimum, average, and maximum widths of 18.6%, 23.6%, and 31.2% of the EER value** — computed on test sets of tens of thousands of trials. The authors explicitly flag "the importance of considering uncertainty in EER measurements."

### Comparability: **NOT COMPARABLE.** Two independent reasons.

**(1) Parcel is not reporting an EER.** 0.799 genuine vs. 0.252 impostor mean cosine with zero overlap is a *score-separation* statistic. EER is the operating point where FA and FR rates are equal, and it is determined entirely by the **tails** of the two distributions, not their means. Zero overlap on the observed sample tells you the empirical EER on that sample is 0 — it tells you nothing about the tail behaviour that EER actually measures.

**(2) n = 378 cannot resolve the range of interest.** Zero errors in 378 pairs gives a Clopper-Pearson 95% upper bound of **1.0%** (rule of three: 3/378 = **0.79%**). That interval contains, indistinguishably: 2026 SOTA (0.12%), the 2023 VoxSRC winner (0.47%), and the 2019 ResNet-34 baseline (1.29%) — plus everything between. **The measurement has no discriminative power in the region where the field operates.** Below ~0.26% (1/378) the experiment is incapable of registering a single error even in principle.

Compounding factors that almost certainly make 378 pairs *easier* than a VoxCeleb trial list: same enrollment session, same microphone, same room, same channel. VoxCeleb1-H exists precisely because same-demographic, same-video-condition negatives are the hard case; VoxSRC-2022 added hard negatives *sharing the same background noise* specifically because systems were shortcutting on environmental cues. Parcel's impostor set almost certainly contains none of that difficulty.

**What Parcel can honestly say today:** "Zero verification errors in 378 in-domain pairs; 95% CI on the error rate [0%, 1.0%]. This is consistent with, but does not demonstrate, competitive EER." Nothing stronger.

**The 18.4 ms speaker-verify overhead** is a *compute* figure and there is no benchmark to compare it against — no leaderboard reports verification-stage latency. Its only meaningful framing is budgetary: 18.4 ms is **~2.4% of Parcel's 0.78 s turn budget** and ~1.2% of the 1,500 ms voice-to-voice target. That is a legitimate engineering claim ("verification is latency-free in practice") and should be stated that way rather than as a performance metric.

---

## 11. Latency: what "conversational" means, and where Parcel's 0.78 s sits

### Published reference points, by clock definition

| Source | What is measured | Figure |
|---|---|---|
| Human conversation (cited in Full-Duplex-Bench) | Inter-speaker transition gap | **200–250 ms** typical; up to ~1 s reads as a natural pause |
| Full-Duplex-Bench v1, Candor | End-of-user-speech → model response start | Moshi **0.265 s** · dGSLM 0.352 s · Freeze-Omni 0.953 s · Gemini Live **1.301 s** |
| Full-Duplex-Bench v1, after interruption | Same clock | Moshi 0.257 s · Gemini Live 1.183 s · Freeze-Omni 1.409 s · dGSLM 2.531 s |
| openbenchmarks TTFAB (2026) | Caller stops speaking → agent audio starts; dual-channel recording, Silero VAD + energy refinement, **no platform timestamps**; 2,078 usable turns across 5 platforms | Telnyx **p50 1,296 / p95 1,856 ms** · ElevenLabs 1,424 / 1,768 · Bland AI 1,520 / 2,248 · Vapi 1,558 / 2,008 · Retell AI 1,740 / 2,259 |
| Full-Duplex-Bench-v3 (Apr 2026) | Δt = t_agent_start − t_user_end, multi-step tool scenarios, task-completion inclusive | Gemini Live 3.1 **4.25 s** · Grok 6.65 · GPT-Realtime 6.89 · Gemini Live 2.5 7.26 · Ultravox v0.7 8.40 · Cascaded Whisper→GPT-4o→TTS **10.12 s** |
| Daily.co voice-agent benchmark | LLM TTFT; end-of-user-speech → first speech for S2S; Silero VAD @ 30 ms frames, 30 turns | Target: voice-to-voice **<1,500 ms** ⇒ ~**700 ms TTFT** budget for text-mode LLMs. Authors warn TTFT "varies hugely between benchmark runs" and is non-repeatable |
| Industry deployment aggregate (10+ live agents, 2026) | End-to-end response | **p50 680 ms / p95 1,180 ms** |
| OpenAI Realtime API (vendor) | Time-to-first-byte, US clients | ~**500 ms**; prompt-caching improvements cut **p95 by ≥25%** across Realtime voice models (Jul 2026) |

### Comparability: **PARTIALLY COMPARABLE — contingent entirely on Parcel's clock definition.**

Parcel reports **realtime p50 0.78 s, max 1.69 s, explicitly "turn-level, not first-token"** and **chat p50 0.65 s**. That phrasing is ambiguous in the direction that matters. Two readings:

- **If** "turn-level" means *end-of-user-speech → start-of-agent-audio*, then 0.78 s p50 is **directly comparable to TTFAB and FDB v1** and is genuinely strong: it beats every one of the five commercial platforms in the openbenchmarks study (best p50 1,296 ms) by ~40%, and beats Gemini Live's 1.301 s in FDB v1. Max 1.69 s would sit near those platforms' p95 band (1,768–2,259 ms), which is respectable.
- **If** "turn-level" means *request dispatched → response object complete* (a server-side clock excluding VAD endpointing, network, audio buffering, and playback start), it is **not the same quantity** and the comparison collapses. This is exactly the failure openbenchmarks designed against — they explicitly refuse platform-reported timestamps and re-derive endpoints from dual-channel recordings.

**This ambiguity must be resolved before the number is quoted externally.** It is the single cheapest credibility fix in the whole latency story.

Two further caveats: (a) Parcel's turns end in **local** tool execution, so its figure likely excludes tool-call round-trip — whereas FDB-v3's 4–10 s figures include chained remote API latency; the comparison is not like-for-like, and Parcel's advantage here is real but architectural, not model-derived. (b) Independent measurements report function-call latency adding **400–800 ms** even when the tool itself returns in under 200 ms; if Parcel's 0.78 s already includes local dispatch, that is a meaningful result worth stating explicitly.

**Cost.** Parcel's ~$0.002–0.006 per short text-mode response and **$0.85 per 52-query replay ($0.0163/query)** are consistent with `gpt-realtime-2.1-mini` official pricing (text in $0.60/M, cached $0.06; text out $2.40/M; **audio in $10/M, cached audio in $0.30/M, audio out $20/M**; 128K context, 32K max output, function calling supported, knowledge cutoff Sep 30 2024). **Comparability: NOT COMPARABLE** — no benchmark publishes cost-per-query. The nearest published cost axis is Artificial Analysis's $/1000 min for STT (ElevenLabs Scribe v2 $3.67, Azure MAI-Transcribe $6.00, cheapest $0.42). Parcel's cost figures are legitimate ops metrics; they are not benchmark results.

---

## 12. Statistical reality check on every Parcel number

Exact Clopper-Pearson 95% intervals, computed:

| Parcel claim | Point | 95% CI | What it actually rules out |
|---|---|---|---|
| Canonical spoken e-stop 7/7 live | 100% | **[59.0%, 100%]** | Nothing below 59%. Does not establish safety-grade reliability. |
| replay estop-pos 3/3 (lane dead) | 100% | **[29.2%, 100%]** | Almost nothing. Good architectural evidence, not a measurement. |
| replay nav-direct 5/5 | 100% | **[47.8%, 100%]** | Nothing below 48%. |
| chat correct tool+args, direct nav 6/6 | 100% | **[54.1%, 100%]** | Does not exceed VoiceAgentBench's ~72% PF ceiling with any confidence. |
| arrival-relation hints 12/12 firm-gold | 100% | **[73.5%, 100%]** | The strongest small-n result Parcel has. Genuinely meaningful. |
| self-consistency 15/15 | 100% | **[78.2%, 100%]** | Second-strongest. Reportable. |
| fabricated junk `navigate_to` 5/6 | 83.3% | **[35.9%, 99.6%]** | Real failure mode, but rate is unresolved between 36% and ~100%. |
| asked required follow-up 0/6 | 0% | **[0%, 45.9%]** | Establishes the capability is *at most* 46% — a genuine negative finding. |
| E1 recorded pack 4/6 | 66.7% | **[22.3%, 95.7%]** | Uninformative as a pass rate. |
| speaker verify, 0 errors / 378 pairs | 0% | **[0%, 1.0%]** | Cannot distinguish SOTA (0.12%) from a 2019 baseline (1.29%). |
| live_run_1 13/52 PASS | 25.0% | [14.0%, 38.9%] | Pre-fix build. |
| replay_run_1 10/52 PASS | 19.2% | [9.6%, 32.5%] | ~20 verdicts describe a dead lane; the number is not about the product. |

**Per-category resolution:** 52 queries across 15 categories ≈ **3.5 items per category**. At n=3–5, a per-category rate has a 95% interval roughly **±30–50 percentage points**. For scale: AudioMultiChallenge publishes ±4.5pp at 452 conversations. **No per-category claim from the current corpus is statistically meaningful.** The corpus is a useful *regression suite* and a genuinely well-designed one (pre-registered gold labels, categorical coverage, positive *and* negative e-stop cases — better methodology than most internal evals). It is not a measurement instrument.

---

## What Parcel would have to run to claim a benchmark number

Cheapest first. Items 1–5 require **no new data collection**.

**1. Re-run the existing 52-query replay on the current post-fix build. (~$0.85, ~1 hour.)**
Reuses: the 52-query corpus, the pre-registered gold labels, the replay harness, the audio recordings. This is not optional — every number Parcel currently holds describes a build superseded by five fix cards, and one of the two runs describes a lane that died at q30. Until this exists, Parcel has no evidence about its current product. Report the hosted-lane liveness check as a hard precondition and abort/retry on lane death rather than scoring a corpse.

**2. Re-score the corpus into SLU metrics instead of PASS/PARTIAL/FAIL. ($0, re-annotation only.)**
Reuses: the pre-registered gold labels. Emit **Intent (=tool) Accuracy**, **Slot/Argument F1**, and **Joint Exact-Match**, per SLURP and MAC-SLU convention. This converts an unpublishable trichotomy into a benchmark-shaped triple, and it will almost certainly reveal that PARTIAL ≈ "intent right, slots wrong" — the same IC-vs-Overall gap MAC-SLU shows (88.92% → 47.18%). Always report `|tools| = 7` alongside; a 7-way closed choice is not MAC-SLU's 81 intents.

**3. Add the VoiceAgentBench metric quartet on the same data. ($0.)**
Reuses: the same gold labels plus the tool schemas. Emit **TS** (tool selection, regex exact-match on name), **TCS** (schema/Pydantic validity), **PF** (argument faithfulness, LLM-judged), **RR** (refusal rate on the safety-refusal and capability-honesty categories). Now Parcel can state "TS x%, PF y%, RR z% on a fixed 7-tool surface, n=52, real far-field audio" against VoiceAgentBench's "best PF 71.97–78.79%, best RR 59.56%, n=1,386, clean TTS." Caveated properly, this is a defensible positioning — and the RR axis is where Parcel's safety design should look good.

**4. Turn the fabrication finding into a proper irrelevance subset. (~$0.50, existing harness.)**
Reuses: the chat-API bench harness. Build 30–50 prompts whose only correct behaviour is refusal or a clarifying question — tools absent from the surface, unknown places, out-of-capability requests. Score refusal rate. Parcel's current 5/6 fabrication has a CI of [36%, 99.6%]; 40 trials would tighten that to roughly ±15pp. This is the highest-value-per-dollar item on the list because it targets the one axis where *every* published system is weak (best VoiceAgentBench RR: 59.56%) and where Parcel's local disposition chain should structurally win.

**5. Fix the latency definition, then republish the number. ($0 if the clock is already right; one instrumentation change otherwise.)**
Adopt **FDB-v3's Δt = t_agent_audio_start − t_user_speech_end**, derived the openbenchmarks way: dual-channel recording on one clock, Silero VAD with energy refinement, **no self-reported timestamps**. Reuses: the audio gateway and the E1 recorded pack. Report p50/p95 over ≥200 turns (openbenchmarks used 2,078). If the current 0.78 s already uses this clock, say so explicitly and the number becomes immediately citable against TTFAB's 1,296–1,740 ms p50 band. If it does not, the number must be withdrawn from external use.

**6. Power the corpus up to a resolvable size. (~$2.50/replay.)**
15 categories × 10 queries = **150 queries** (vs. today's 3.5/category). This gets per-category intervals to roughly ±25pp — still wide, but no longer meaningless. Reuses: the label schema, the replay harness, the category taxonomy. Reaching ±10pp per category needs ~90/cell (≈1,350 queries, ~$22/replay) — worth costing out, since it is still cheap in absolute terms and is the difference between a regression suite and an instrument.

**7. Convert the e-stop from 7/7 into a real operating point. (Two arms; the FAR arm needs no new recording.)**
- **FRR arm:** ≥100 spoken e-stop utterances across multiple speakers, distances, and noise conditions, **including the ASR-variant positives that have never been tested**. 100 trials with zero failures yields a 3% upper bound — a defensible safety claim, versus today's 43%.
- **FAR arm (cheapest, fully reusable):** score the detector against ≥10 hours of negative/ambient audio. **The Dinner Party Corpus (~5.5 h far-field speech, music, and noise) is the exact resource openWakeWord uses for this** and is publicly available. Report **FRR at 1 FA / 10 h** — the industry-standard operating point — and publish the DET curve.
- **Fault-injection arm:** deliberately kill the hosted lane and verify the local latch still fires. Parcel proved this accidentally in replay_run_1 (3/3); 50 deliberate trials makes it a real result.
- **Phrase redesign:** `"Stop."` is indefensible by wake-word standards (1 syllable, fricative onset, high conversational prior). Move the *detector* trigger to a 3–5 syllable phonetically diverse phrase and keep bare "stop" only as a secondary, higher-threshold path. Retain "stop" as a *convenience* trigger; never call it the e-stop. Per ISO 13850, the safety function needs a hardware actuator with positive operation — the local latch plus a physical control, with voice layered on top.

**8. Build a real speaker-verification trial list. (Moderate cost; embeddings already exist.)**
Reuses: the enrolled embeddings and the verification pipeline. Needs **≥10,000 trials** with genuinely hard negatives — cross-session, cross-distance, cross-noise, and (per VoxSRC-2022's design) negatives *sharing the same acoustic environment*, so the system cannot shortcut on room cues. Report **EER + minDCF with bootstrap 95% CIs**, since the VoxSRC organisers found CI widths of 18.6–31.2% of the EER value even at 37K+ trials. Only then is a VoxCeleb1-O comparison legitimate. **Interim, free fix:** restate the current result as "0 errors / 378 in-domain pairs, 95% CI [0%, 1.0%]" and drop any implication of near-SOTA performance.

**9. Replace ASR anecdotes with two numbers. ($0 — audio already recorded.)**
Reuses: the live_run_1 and E1 recordings plus the existing gold transcripts. Emit (a) **Command Error Rate** — fraction of utterances whose full transcript is wrong, the only quantity the exact-match router cares about — and (b) a **hallucination-event count** (output length grossly exceeding input duration, as in the `"Walk to the bench"` case). Do **not** report corpus WER: on 1–5-word utterances it is length-weighted noise, and it would fuse three distinct failure classes into one uninformative number.

**10. Only if an external leaderboard number is genuinely required: run VoiceBench's IFEval (345) and AdvBench (520) subsets through the hosted lane. (~$5–15.)**
These are the only public benchmark subsets Parcel could execute without new data collection, and AdvBench's refusal-rate scoring is at least adjacent to Parcel's safety posture. **State plainly that this measures `gpt-realtime-2.1-mini`, not Parcel** — Parcel's SafetySupervisor and disposition chain never see these prompts. Reference points: GPT-4o-Audio scores IFEval 76.02 / AdvBench 98.65; Naive-4o cascade 76.51 / 98.27; the field's E2E models 10–33 on IFEval. Useful as a vendor-lane sanity check; misleading if presented as a Parcel score.

---

### Sources

[VoiceBench (TACL 2026, ACL Anthology PDF)](https://aclanthology.org/2026.tacl-1.18.pdf) · [VoiceBench live leaderboard](https://matthewcym.github.io/VoiceBench/) · [VoiceBench MIT Press](https://direct.mit.edu/tacl/article/doi/10.1162/TACL.a.628/136245/VoiceBench-Benchmarking-LLM-Based-Voice-Assistants) · [VoiceAgentBench (arXiv 2510.07978)](https://arxiv.org/html/2510.07978) · [BFCL Audio (Salesforce)](https://www.salesforce.com/blog/bfcl-audio-benchmark/) · [Berkeley Function Calling Leaderboard V4](https://gorilla.cs.berkeley.edu/leaderboard.html) · [Full-Duplex-Bench (arXiv 2503.04721)](https://arxiv.org/abs/2503.04721) · [Full-Duplex-Bench-v3 (arXiv 2604.04847)](https://arxiv.org/html/2604.04847v1) · [Full-Duplex-Bench repo](https://github.com/DanielLin94144/Full-Duplex-Bench) · [Audio MultiChallenge (arXiv 2512.14865)](https://arxiv.org/abs/2512.14865) · [Scale Labs AudioMC leaderboard](https://labs.scale.com/leaderboard/audiomc) · [SD-Eval (arXiv 2406.13340)](https://arxiv.org/abs/2406.13340) · [MAC-SLU (arXiv 2512.01603)](https://arxiv.org/html/2512.01603) · [SLURP](https://www.semanticscholar.org/paper/SLURP:-A-Spoken-Language-Understanding-Resource-Bastianelli-Vanzo/11aba1be0ccdbe291fc4e469e458b832d5228203) · [Open ASR Leaderboard (arXiv 2510.06961)](https://arxiv.org/html/2510.06961v4) · [HF Open ASR Leaderboard blog](https://huggingface.co/blog/open-asr-leaderboard) · [Artificial Analysis speech-to-text](https://artificialanalysis.ai/speech-to-text) · [CHiME-8 DASR challenge paper (ISCA 2024)](https://www.isca-archive.org/chime_2024/cornell24_chime.pdf) · [CHiME-7/8 DASR review (arXiv 2507.18161)](https://arxiv.org/pdf/2507.18161) · [NTT CHiME-8 system (arXiv 2502.09859)](https://arxiv.org/abs/2502.09859) · [VoxSRC retrospective (arXiv 2408.14886)](https://arxiv.org/pdf/2408.14886) · [VoxCeleb1](https://www.robots.ox.ac.uk/~vgg/data/voxceleb/vox1.html) · [w2v-BERT 2.0 speaker verification (arXiv 2510.04213)](https://arxiv.org/html/2510.04213) · [Picovoice wake-word benchmark](https://picovoice.ai/docs/benchmark/wake-word/) · [Picovoice wake-word benchmarks guide](https://picovoice.ai/blog/wake-word-benchmarks/) · [openWakeWord](https://github.com/dscripka/openWakeWord) · [Hey Snips / dilated conv KWS (arXiv 1811.07684)](https://arxiv.org/abs/1811.07684) · [Sensory custom wake word guide 2026](https://sensory.com/custom-wake-words-branded-voice-ux-guide-2026/) · [Ideal wake word length](https://www.futurebeeai.com/knowledge-hub/ideal-wake-word-length) · [ISO 13850:2015](https://www.iso.org/obp/ui/es/#iso:std:iso:13850:en) · [ISO 13850 e-stop requirements explained](https://machinerysafety101.com/2026/05/18/iso-13850-emergency-stop-requirements/) · [openbenchmarks voice-agent TTFAB](https://openbenchmarks.com/voice-agent-latency/voice-agent-end-to-end-latency) · [Daily.co voice-agent LLM benchmark](https://www.daily.co/blog/benchmarking-llms-for-voice-agent-use-cases/) · [DestiLabs 2026 voice-agent benchmark](https://www.destilabs.com/blog/ai-voice-agent-benchmark-2026) · [gpt-realtime-2.1-mini model card](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini) · [MarkTechPost on GPT-Realtime-2.1](https://www.marktechpost.com/2026/07/06/openai-gpt-realtime-2-1-mini-reasoning-realtime-api/)