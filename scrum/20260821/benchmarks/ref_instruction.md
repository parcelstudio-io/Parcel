# Benchmark Reference Report — Instruction Following & Tool/Function Calling

**Scope:** positioning Parcel's measured evidence against current (2024–2026) instruction-following and tool-calling benchmarks. Angle: fabrication-when-no-tool-exists (Parcel's sharpest weakness), correct tool+arg selection (its sharpest strength), and pass^k reliability framing for the e-stop claim.

**Provenance warning up front:** primary sources (arXiv papers, official repos, Gorilla/Sierra blogs) are marked ✅. Third-party leaderboard aggregators (benchlm.ai, sophon.at, llm-stats, pricepertoken) are marked ⚠️ — they republish vendor-claimed numbers from uninspectable harnesses and list 2026 model names I could not independently verify against a primary source. Treat ⚠️ numbers as order-of-magnitude anchors, not citable scores. The Gorilla leaderboard itself is JS-rendered and did not yield a per-category table to fetch.

---

## 0. The one methodological fact that governs everything below

Parcel has **never measured task diversity and trial count at the same time**.

| Artifact | Distinct tasks | Trials per task |
|---|---|---|
| live_run_1 / replay_run_1 corpus | 52 | **1** |
| Chat-API bench | **4** (cells) | 6 |
| E1 recorded pack | 6 | 1 |
| e-stop | **1** (canonical phrasing) | 7 |

Every benchmark in this report requires **both** axes. BFCL wants hundreds of distinct prompts (1 trial). τ-bench wants ~50–115 distinct tasks × k trials. FDB-v3 wants 100 scenarios × 1 trial. Parcel's "6/6", "5/5", and "7/7" are all *trial-count* numbers on n≤5 tasks; its "13/52" is a *task-count* number with n=1 trial and a dead build. **No Parcel number today survives contact with a benchmark denominator.** This is the finding that should govern the whole assessment.

Binomial reality on the headline numbers (Clopper-Pearson, two-sided 95%):

| Parcel number | Point | 95% CI | What it actually rules out |
|---|---|---|---|
| tool+args 6/6 direct nav | 100% | **[54.1%, 100%]** | rules out <54% reliability. Nothing more. |
| nav-direct 5/5 (replay) | 100% | **[47.8%, 100%]** | rules out <48%. |
| arrival-relation 12/12 | 100% | [73.5%, 100%] | genuinely strong for n=12 |
| self-consistency 15/15 | 100% | [78.2%, 100%] | genuinely strong for n=15 |
| fabricated call 5/6 | 83.3% | **[35.9%, 99.6%]** | rules out <36% fabrication |
| follow-up asked 0/6 | 0% | **[0%, 45.9%]** | consistent with up to 46% |
| e-stop 7/7 | 100% | **[59.0%, 100%]** | rule of three: 95% upper bound on failure rate = **3/7 ≈ 43%** |

---

## 1. IFEval — Instruction-Following Eval (Google, 2023)

**What it actually measures.** 541 English prompts, each carrying one or more of **25 verifiable instruction types** ("write in exactly 3 paragraphs", "all lowercase", "wrap in double quotes", "include keyword X at least N times"). Scored by a deterministic Python checker — no LLM or human judge. Four reported views: prompt-level strict, prompt-level loose, instruction-level strict, instruction-level loose. Prompt-level = every constraint in the prompt satisfied; instruction-level = each constraint credited independently. Denominator = 541 prompts (or ~1,000 instruction instances). ✅ [arXiv:2311.07911](https://arxiv.org/pdf/2311.07911)

**Current scores.** Saturated. ⚠️ benchlm.ai (Aug 12, 2026): Qwen3.5-27B 95%, Agents-A1 94.8%, Qwen3.7 Plus 94.6% — top models clustered within 0.4 pts. Mid-tier reference: open ~8B instruct models sit ~78–85%; the Tulu-3-8B baseline is 82.4% ✅ ([IFBench paper](https://github.com/allenai/IFBench)). ⚠️ [benchlm.ai/benchmarks/ifeval](https://benchlm.ai/benchmarks/ifeval)

**Parcel comparability: NOT COMPARABLE.** Not partially — not at all. IFEval measures *surface-form compliance of free text*. Parcel emits tool calls, and its "instruction following" construct is intent→tool mapping. Parcel has **zero** items with a format constraint, and its 52-query corpus contains no verifiable-constraint instruction of any kind. There is no transformation. Do not cite IFEval, do not benchmark against it, and treat any Parcel doc that says "instruction following" as meaning something else entirely.

## 1b. IFBench (Ai2, NeurIPS 2025 D&B) — IFEval's successor

**What it measures.** 58 **new, out-of-domain** verifiable constraints across 294 prompts (word-count limits, counting, copying, character/word/sentence manipulation), plus 29 hand-annotated training constraints. Built explicitly to expose IFEval overfitting. ✅ [allenai/IFBench](https://github.com/allenai/IFBench), [OpenReview](https://openreview.net/forum?id=yfYgwjj5F8)

**Current scores.** The IFEval→IFBench gap is the headline: models >80% on IFEval fall **below 50%** on IFBench's novel constraints. RLVR-trained Tulu-3-8B: IFEval 82.4→92.2 while IFBench only 28.9→45.9 ✅. Frontier as of 2026: ⚠️ Artificial Analysis lists Grok 4.3 (medium) 83.3%, Grok 4.20 0309 (Reasoning) 82.9%, MiniMax-M3 82.9%; ⚠️ llm-stats lists Nemotron 3 Ultra 0.817 with an all-model mean of 0.675. ([Artificial Analysis](https://artificialanalysis.ai/evaluations/ifbench), [Ai2 blog](https://allenai.org/blog/ifbench-artificial-analysis))

**Parcel comparability: NOT COMPARABLE.** Same reason. **But the IFEval→IFBench lesson transfers directly and is the most useful thing in this section for Parcel:** a 52-query corpus with *pre-registered gold labels written by the same people who built the system* is structurally an IFEval, not an IFBench. Parcel's corpus categories are its own 15 templates. Any future "our tool-selection accuracy is X%" claim will be an in-domain number, and the honest expectation is a large drop on held-out phrasings authored by someone else. Parcel's own data already hints at this: nav-direct 5/5 (in-template) vs. 5/6 fabrication on the out-of-surface probe.

---

## 2. Berkeley Function-Calling Leaderboard (BFCL) v3/v4 — **the primary reference for both of Parcel's headline numbers**

**What it actually measures.** ✅ [gorilla.cs.berkeley.edu/leaderboard.html](https://gorilla.cs.berkeley.edu/leaderboard.html); ✅ [CHANGELOG](https://github.com/ShishirPatil/gorilla/blob/main/berkeley-function-call-leaderboard/CHANGELOG.md)

22 subsets. Non-live (`simple_python`, `simple_java`, `simple_javascript`, `multiple`, `parallel`, `parallel_multiple`), live (`live_simple`, `live_multiple`, `live_parallel`, `live_parallel_multiple`), relevance (`irrelevance`, `live_irrelevance`, `live_relevance`), multi-turn (`multi_turn_base`, `_miss_func`, `_miss_param`, `_long_context`), agentic (`web_search_base`, `web_search_no_snippet`, `memory_kv`, `memory_vector`, `memory_rec_sum`). ✅ [EvalScope BFCL-v4](https://evalscope.readthedocs.io/en/v1.2.0/third_party/bfcl_v4.html)

**Scoring rules — these matter for Parcel:**
- **AST match** (order-independent): function name match + all required parameters present + parameter types correct + values within the allowed set. This is *exactly* the scoring rule Parcel already applies informally when it says "correct tool+args".
- **Executable**: run the generated call in a sandbox, compare return value.
- **Irrelevance detection**: model is shown a query plus a candidate tool set where **none apply**; correct behavior is to emit **no** function call. Scored as fraction correctly abstaining.
- **Relevance detection**: fraction of tool-requiring queries for which the model emits ≥1 correct call.

**v4 overall weighting (changed July 17, 2025):** Agentic 40% / Multi-Turn 30% / Live 10% / Non-Live 10% / **Hallucination 10%**. The "Hallucination" segment *is* irrelevance/relevance — it was 0% of overall in v3 and is now explicitly weighted at 10%. Live and Non-Live accuracy now **exclude** irrelevance so it isn't double-counted. `live_relevance` is excluded from final scoring. ✅ CHANGELOG

**Current representative scores.**
- ⚠️ benchlm.ai BFCL v4 (Aug 21, 2026, 13 models): Qwen3.7 Max 75.0% (top), BTL-4 73.5%, Ling 3.0 Flash 73.0%; mid-tier Qwen3.7 Plus 72.9%, Pokee-Isaac 28B 70.9%, LFM2.5-2.6B 56.9%. ([link](https://benchlm.ai/benchmarks/bfcl-v4))
- ⚠️ Another snapshot: Claude-Opus-4-5 (FC) 77.47%, Claude-Sonnet-4-5 (FC) 73.24%.
- ⚠️ BFCL v3 (pricepertoken, Jun 29, 2026, 23 models): GLM 4.5 76.7%, Claude Opus 4.7 76.6%, Gemini 3.1 Flash Lite 76.5%; **mean 58.5, sd 17.5**. ([link](https://pricepertoken.com/leaderboards/benchmark/bfcl-v3))
- **Irrelevance-specific reference points** (BFCL v1/v2-era AST+Exec+Irrel+Rel composite, ⚠️ [EmergentMind, Feb 10 2026 snapshot](https://www.emergentmind.com/topics/berkeley-function-calling-leaderboard-v4-bfclv4)): GPT-4-0125 **IrrelAcc 61.35**, RelAcc 97.56; Meta-Llama-3-70B **IrrelAcc 50.47**, RelAcc 92.68; Granite-20B-FunctionCalling IrrelAcc 87.08; ToolACE-8B ≈89. A single EvalScope qwen-plus run reports `irrelevance` = 1.00 with overall 0.5209 ✅.

**The asymmetry those numbers show is the most important benchmark fact for Parcel:** even in 2024-era models, RelAcc (act when you should) ran 92–98% while IrrelAcc (abstain when you should) ran 50–61%. **Abstention is roughly 35–45 points harder than action, and always has been.** Parcel's evidence reproduces this gap in extreme form: 6/6 act, 1/6 abstain.

### Parcel comparability

**(a) Correct tool+arg selection — PARTIALLY comparable, but with a fatal denominator problem.**

BFCL's AST rule and Parcel's "correct tool+args" rule are the same rule. The tool surface (7 functions) is comparable in size to BFCL's `simple`/`multiple` candidate sets. So the *metric* transfers cleanly.

What does not transfer: **BFCL `simple_python` has hundreds of distinct prompts scored once each. Parcel's 6/6 is one scenario ("direct navigation") sampled six times.** n_task = 1. That is a self-consistency measurement wearing an accuracy measurement's clothes. `nav-direct 5/5` from replay_run_1 is the reverse — 5 distinct queries, 1 trial each, n_task = 5.

Transformation required to make it comparable: **≥100 distinct in-surface commands spanning all 7 tools, 1 trial each, AST-scored.** Until then, quoting "6/6" next to "Qwen3.7 Max 75.0%" is not a comparison, it is a category error — 6/6 has a 95% lower bound of 54.1%, i.e. it does not even establish that Parcel beats the BFCL v3 all-model *mean* of 58.5.

**(b) Fabricating a call when no suitable tool exists — PARTIALLY comparable, and this is the sharpest positioning available.**

Parcel's "5/6 FABRICATED a junk `navigate_to` when the needed tool was absent from the surface" is BFCL **irrelevance detection**, measured on a 6-sample cell. Restated in BFCL's unit: **IrrelAcc = 1/6 = 16.7% [95% CI 0.4%–64%]**.

Against the reference points: GPT-4-0125 61.35, Llama-3-70B 50.47, Granite-20B-FC 87.08. Parcel's 16.7% is below every one of them — but the CI is so wide it overlaps GPT-4-0125's number, so **the honest statement is "Parcel's abstention behavior is unmeasured, with a point estimate that is alarming."** Not "Parcel is worse than GPT-4."

Two caveats that cut in *opposite* directions and must both be stated:
1. **Against Parcel:** BFCL irrelevance items are single-turn text with a clean gold. Parcel's cell is the same shape. The comparison is more apples-to-apples than most in this report.
2. **For Parcel:** BFCL's irrelevance queries are typically *semantically distant* from the offered tools. Parcel's probe is a **near-miss** — the request was navigation-adjacent and `navigate_to` was sitting right there. That is the documented hardest slice (see §4). Parcel measured itself on the hard end of the distribution and should say so.

**(c) BFCL `multi_turn_miss_param` — PARTIALLY comparable, and Parcel's 0/6 belongs here.** v4 changed this subset: it no longer checks whether the model refrains from acting when a parameter is missing; it checks "whether the model can perform correctly **once the missing information is provided**." ✅ CHANGELOG. Parcel's "0/6 asked the required follow-up question from injected state" is testing the *older* v3 semantics. Worth knowing: BFCL moved away from grading the ask, so a Parcel claim built on it won't map to a current leaderboard column.

---

## 3. AgentAbstain (July 11, 2026) — **the single best conceptual frame for Parcel's fabrication failure**

✅ [arXiv:2607.10059](https://arxiv.org/html/2607.10059) · [agentabstain.github.io](https://agentabstain.github.io/)

**What it measures.** 263 **paired** tasks (526 total) across 42 MCP sandbox environments. Each pair is one should-act task and one should-abstain task that are otherwise matched. Eight scenarios: pre-execution (S1 Missing Critical Parameter, S2 Ambiguous Action Specification, S3 Conflicting Constraints, S4 High-Stakes Action, **S5 Insufficient Tool Capability**) and runtime (S6 Critical Tool Failure, S7 Conflicting Evidence, S8 Emergent Risk Discovery). 166 pre-execution pairs / 97 runtime pairs. Human-validated at 94–98%.

**Metrics.** Act Accuracy, Abstain Accuracy, **Paired Accuracy** (fraction of pairs where *both* halves are correct), **Conditioned Abstention Rate** (abstain accuracy restricted to pairs whose act half succeeded). Paired accuracy is the headline because it defeats the trivial degenerate policies — always-act and always-abstain both score 0.

**Current scores (17 frontier models, 4 harnesses).**

| Model | Paired | Act | Abstain | CAR |
|---|---|---|---|---|
| Gemini 3.1 Pro (SOTA) | **59.5%** | 90.5% | 65.4% | 65.7% |
| Claude Opus 4.7 | 59.4% | 76.5% | **79.0%** | 77.6% |
| GPT-5.5 | 52.5% | 87.2% | 62.6% | 59.8% |
| **GPT-5 (mid-tier ref)** | **49.6%** | 80.0% | 58.7% | 66.5% |
| Gemini 3 Flash | 39.7% | **91.7%** | 43.6% | 43.4% |
| GPT-4o (floor) | 33.0% | 69.6% | **36.4%** | 40.9% |

Best model 59.5%; **13 of 17 below 50%.** Per-scenario means: **S5 Insufficient Tool Capability = 61% (the easiest category)**, S6 Critical Tool Failure 55%, informational-gap 40%, logical-contradiction 33%. Models recognize missing *capabilities* better than any other abstention trigger. Documented pathology: **post-hoc abstention** — agents commit the irreversible action, then narrate a refusal.

**Parcel comparability: PARTIALLY comparable — and this is the frame Parcel should adopt.**

**S5 ("available tools fundamentally cannot achieve the goal; visible from the tool inventory") is a verbatim description of Parcel's probe.** Parcel even has the paired structure already, by accident: the direct-navigation cell is the should-act half (6/6) and the missing-tool cell is the should-abstain half (1/6).

Positioning, with every caveat attached:
- Parcel Act Accuracy on that pair ≈ 100% (n=6 trials, 1 task).
- Parcel Abstain Accuracy ≈ **16.7%** (n=6 trials, 1 task).
- Illustrative trial-wise paired accuracy ≈ 16.7%.

Against a benchmark whose **worst of 17 frontier models scores 36.4% abstain** and whose **mean S5 paired accuracy is 61%**, Parcel's point estimate is below the floor. That is the sharpest honest sentence available about Parcel today.

**But it is not a claim, and here is precisely why not:** n_task = 1 vs. AgentAbstain's 263 pairs; n_trial = 6 vs. their single-shot-per-task design; different harness; no MCP sandbox; Parcel's probe is a near-miss inside a 7-tool surface rather than a 42-environment inventory; and the CI [0.4%, 64%] overlaps GPT-4o's 36.4%. **Transformation needed:** build ≥30 matched act/abstain pairs on the fixed 7-tool surface, report Paired Accuracy and CAR. That is cheap (§ closing) and would convert Parcel's most embarrassing anecdote into its most credible measurement.

One more thing Parcel should check against this paper: **post-hoc abstention.** Parcel's local disposer chain (SafetySupervisor → router → admission → executive) is architecturally the *cure* for this — the model proposes, the chain disposes, so a fabricated `navigate_to` should be caught at plan admission before anything moves. **Parcel has never measured whether it is.** The 5/6 number is a measurement of the *proposer*, not of the product. That distinction is currently unmeasured and is the highest-value thing Parcel could report that no leaderboard model can claim.

---

## 4. Tool-hallucination and irrelevance literature — mechanism, and why Parcel's number may be less anomalous than it looks

**ToolBeHonest (EMNLP 2024).** ✅ [arXiv:2406.20015](https://arxiv.org/abs/2406.20015) · [GitHub](https://github.com/toolbehonest/toolbehonest). 700 manually annotated samples, 7 tasks, three toolset scenarios — **missing necessary tools**, potential tools, limited-functionality tools — diagnosed at three levels: (1) solvability detection, (2) solution planning, (3) missing-tool analysis. Composite 0–100. **Gemini-1.5-Pro 45.3, GPT-4o 37.0.** Stated root cause: *"the primary reason for model errors lies in assessing task solvability."* Aging (2024 models), but the construct is the closest published match to Parcel's probe and the absolute scores are low.
→ **Parcel: PARTIALLY comparable conceptually, NOT numerically.** Composite scoring over 3 diagnostic levels can't be reconstructed from a 6-trial binary. Value: it establishes that "did you notice this is unsolvable with these tools" is a *known-hard, low-scoring* axis, which is the correct context for 5/6.

**Structural Alignment Bias / SABEval (April 2026).** ✅ [arXiv:2604.11322](https://arxiv.org/pdf/2604.11322) — Liu, Lin, Cao, Zhang, Fang, Cao. Metric: **Tool Invocation Rate (TIR)** = proportion of samples where the tool-call token is the argmax prediction; lower is better on irrelevant-tool sets.

| Model | Random pairing | SABEval (𝒟₀, structurally aligned) | Gap |
|---|---|---|---|
| Qwen3-4B | 0.16% | **40.04%** | +39.88 |
| Qwen3-8B | 0.04% | 34.26% | +34.22 |
| Qwen3-14B | 0.04% | **41.86%** | +41.82 |
| ToolACE-2.5-8B | 0.12% | 40.67% | +40.55 |
| Watt-Tool-8B | 0.00% | 10.51% | +10.51 |

And it *escalates with alignment strength*: Qwen3-8B 30.39%→82.44%, Qwen3-14B 41.37%→**91.02%** across 𝒟₀–𝒟₄. Attention-scaling intervention drops Qwen3-8B from 34.26% to 4.29%.

→ **This is the most important reframing in the report.** Parcel's probe is maximally structurally aligned: a navigation-adjacent request with `navigate_to` in the surface. In that regime, models that score ~0% false-invocation under random pairing hit **41–91%**. Parcel's 83.3% fabrication rate sits inside the published 𝒟₃–𝒟₄ band. So the correct characterization is **not** "Parcel's model is uniquely broken" — it is *"Parcel measured the one regime where every tested model fails, and got a result consistent with the published failure regime."* That is both more defensible and more damning, because it means the fix has to be architectural (the disposer chain), not a prompt tweak.

**ToolFailBench (July 6, 2026).** ✅ [arXiv:2607.04686](https://arxiv.org/html/2607.04686v1). 1,000 single-turn tasks over finance/medicine/law/cybersecurity/real-estate: **750 tool-required + 250 control tasks where no tool is needed.** Failure modes: Tool-Skip, Result-Ignore, **Output-Fabrication** (inventing structured info absent from tool returns), **Unnecessary-Tool-Use**. Metrics TSR / CTUR / RIR / OFR / **UTR** / CTRL-Acc. 19 models. Grok-4.3 leads CTUR at 86.33%. Same-scale spread is enormous: **Llama-3.1-70B UTR 77.73% vs. Qwen2.5-72B UTR 0.00%.**
→ **Parcel: NOT comparable.** UTR is "called a tool when a direct *answer* would do" — Parcel's failure is "called the *wrong* tool when the *right* tool was absent." Different denominators, different construct. Note explicitly: **the paper states it does not cover inventing calls when no suitable tool exists**, so ToolFailBench is *not* the home for Parcel's 5/6 despite the surface similarity. Cite AgentAbstain S5 or BFCL irrelevance instead.

**AgentHallu (Jan 2026)** ✅ [arXiv:2601.06818](https://arxiv.org/html/2601.06818v1) — hallucination *attribution* in agent traces (which step introduced it), not rate measurement. Not comparable; potentially useful tooling for Parcel's replay transcripts.

---

## 5. τ-bench / τ²-bench / τ³-bench — pass^k reliability

**τ-bench (Sierra, 2024, frozen).** ✅ [arXiv:2406.12045](https://arxiv.org/pdf/2406.12045). Two domains: **retail 115 tasks**, **airline 50 tasks** (165 total). An LLM user simulator converses with the agent; the agent must obey a written policy document and manipulate a database via tools. Reward is DB-state comparison + required-info checks.

**pass^k** = fraction of tasks where the agent succeeds on **all k** runs. Formally `pass^k = E_task[ C(c,k)/C(n,k) ]` over c successes in n trials ✅ [EmergentMind τ²](https://www.emergentmind.com/topics/tau2-bench). It is **not** pass@k (best-of-k). It decays as ≈p^k under independence, and it is the honest production metric because users don't retry.

**Frozen-board scores (late 2024):** Claude 3.5 Sonnet retail 69.2% / airline 46.0% pass^1; GPT-4o retail 60.4% / airline 42.0%. **GPT-4o retail falls from ~60% at pass^1 toward ~25% at pass^8.** ✅/⚠️ [benchmarkingagents](https://benchmarkingagents.com/tau-bench-retail-airline/)

**Published pass^1→pass^4 decay** ⚠️ (via [AISBench τ²](https://ais-bench-benchmark.readthedocs.io/en/latest/extended_benchmark/agent/tau2_bench.html)):

| Domain | pass^1 | pass^2 | pass^3 | pass^4 |
|---|---|---|---|---|
| telecom | 62.61% | 44.78% | 36.52% | 32.17% |
| airline | 46.00% | 37.00% | 34.00% | 32.00% |
| retail | 32.17% | 19.13% | 13.48% | **8.70%** |

Independence bound: a 90% pass^1 agent has pass^8 ≈ 43% *even with uncorrelated failures*.

**τ²-bench (Jun 9, 2025).** ✅ [arXiv:2506.07982](https://arxiv.org/abs/2506.07982) — Barres, Dong, Ray, Si, Narasimhan. Adds **dual control**: a Dec-POMDP where the *user* also manipulates the shared world (telecom domain), plus a compositional task generator. Headline: large drops moving from no-user to dual-control. ⚠️ aggregators list 220 tasks across airline/retail/telecom.

**τ³-bench (2026, v1.0.1 July 2026).** ✅ [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench) — the repo now *is* τ³. Adds `banking_knowledge` (RAG/knowledge-retrieval), **full-duplex voice evaluation via realtime providers (OpenAI, Gemini, xAI)**, and 75+ task corrections. Frontier models reach only ~25.5% on banking_knowledge ✅. **Results from before v1.0.1 are not comparable.**

**⚠️ Aggregator leaderboards are not usable for τ.** benchlm.ai (Aug 21, 2026) lists GLM-5.2 99.1%, GPT-5.4 98.9%, Claude Fable 5 98.5%, mid-tier Gemini 3.1 Pro 95.6%, Claude Opus 4.8 94.4%, o3 80.7% — while sophon.at lists a top of 79.3% for overlapping models. **A ~20-point disagreement between aggregators on the same benchmark.** Both explicitly warn that domain / task release / user-simulator model / scaffold / trial count / pass^k choice must all match. Do not cite these.

### Parcel comparability: NOT COMPARABLE (and it isn't close)

τ requires multi-turn dialogue with an LLM user simulator, a persistent database, a written policy document the agent must obey, and k repeated trials per task. Parcel's corpus is **single-turn**, has **no user simulator**, and runs **1 trial per query**. There is no transformation short of building a new evaluation.

**But the pass^k *framing* is exactly what Parcel needs, and it demolishes the e-stop claim.**

### What e-stop 7/7 actually means in pass^k terms

Parcel: *"canonical spoken e-stop 7/7 live; one ASR-variant positive never tested."*

In τ's units that is **pass^7 = 1.0 on a task set of size |T| = 1**, over a **single canonical phrasing**. Three problems, in ascending severity:

1. **|T| = 1.** pass^k is an expectation over tasks. With one task there is no expectation — it's a point observation. The "one ASR-variant positive never tested" means Parcel has measured a *point*, not a *distribution*.
2. **Statistical power.** 7/7 → one-sided 95% lower bound on per-trial reliability p is **0.652**. So the data are consistent with p = 65%, under which pass^7 would be 0.65⁷ ≈ **4.9%** — i.e. a system that fails one stop in three could plausibly have produced this exact result (~5% of the time). **Rule of three: zero failures in 7 trials caps the 95% upper bound on failure rate at 3/7 ≈ 43%.**
3. **Wrong target reliability.** For a physically-embodied emergency stop, the interesting question is whether failure is below 10⁻³. **Seven trials cannot demonstrate 10⁻² , let alone 10⁻³.** No number of trials at this scale can.

**The one thing that genuinely strengthens the claim, and Parcel should lead with it instead:** in replay_run_1, **estop-pos 3/3 PASS *with the hosted lane dead***. That is not a model-reliability result — it is evidence that the **local deterministic latch fires independently of the proposer**. That is an architectural property, and architectural properties are provable by *unit test at arbitrary confidence for free*, not by 7 live trials. **Decompose the e-stop into two failure surfaces** — (i) ASR recognizes the stop phrase [stochastic, needs trials], (ii) recognized phrase latches the supervisor [deterministic local code, needs unit tests] — and the second half becomes a claim Parcel can actually make. Right now the 7/7 conflates them and is weaker than the truth.

---

## 6. Legacy tool benchmarks: ToolBench, API-Bank, T-Eval

⚠️/✅ [benchmarkingagents tool-use comparison, 2026](https://benchmarkingagents.com/best-benchmarks-for-tool-use/)

| Benchmark | Measures | Size | Status 2026 |
|---|---|---|---|
| **ToolBench** | Tool selection breadth over real APIs | 3,451 tools / **16,464 RapidAPI endpoints** | Active but **superseded** by BFCL + τ-bench; retains reference value |
| **API-Bank** ✅ [arXiv:2304.08244](https://arxiv.org/pdf/2304.08244) | API call sequence accuracy | **53 APIs, 264 annotated dialogues** | Active but **saturating**; declining discriminative power |
| **T-Eval** | 6 aspects: instruction following, planning, reasoning, retrieval, understanding, review | 6 sub-benchmarks | Active, research-diagnostic, less production-relevant |

**Parcel comparability: NOT COMPARABLE, and not worth pursuing.** All three assume a large open API surface; Parcel's defining property is a **fixed 7-function surface**. ToolBench's retrieval-over-16k-APIs construct is the opposite of Parcel's design. The 2026 editorial consensus is "quote BFCL (function calling) + τ-bench (dialogue)" — Parcel should follow that and ignore ToolBench/API-Bank entirely.

---

## 7. Voice-native benchmarks — **where Parcel actually lives**

### 7a. Full-Duplex-Bench-v3 (April 2026) — ★ the most comparable published benchmark to Parcel, by a wide margin

✅ [arXiv:2604.04847](https://arxiv.org/html/2604.04847v1) · [demo](https://daniellin94144.github.io/FDB-v3-demo/) · [GitHub](https://github.com/DanielLin94144/Full-Duplex-Bench)

**What it measures.** **100 scenarios**, **12 real human speakers** (incl. non-native, Korean/Russian L1), recorded in **uncontrolled environments on everyday laptop microphones**. Four domains (Travel & Identity, Finance & Billing, Housing & Location, E-Commerce Support), each with **3–4 mock API functions with deterministic outputs**. Every query annotated for five disfluency categories: fillers, pauses, hesitations, false starts, self-corrections.

**Metrics.** Tool Selection F1; Argument Accuracy (GPT-4o semantic judge); **Pass@1** = binary conjunction of perfect tool selection AND argument accuracy AND response quality; turn-take rate; interruption rate (agent speaks before user finishes); three latency components (**first response word / tool-call invocation / task completion**); filler rate.

**Results (Table 2):**

| Model | Tool Sel F1 | Arg Acc | **Pass@1** | Turn-take | Interrupt | Latency |
|---|---|---|---|---|---|---|
| **GPT-Realtime** | **0.876** | **0.680** | **0.600** | 96.0% | **13.5%** | 6.89s |
| Gemini Live 3.1 | 0.817 | 0.588 | 0.540 | 78.0% | 19.2% | **4.25s** |
| Gemini Live 2.5 | 0.786 | 0.593 | 0.490 | 92.0% | 14.1% | 7.26s |
| Grok | 0.797 | 0.542 | 0.430 | 94.0% | 25.5% | 6.65s |
| Cascaded (Whisper→LLM→TTS) | 0.803 | 0.562 | 0.450 | **100%** | 33.0% | 10.12s |
| Ultravox v0.7 | 0.794 | 0.513 | 0.410 | 96.0% | 47.9% | 8.40s |

Difficulty tiers, GPT-Realtime: Easy **0.750** → Medium 0.588 → Hard 0.433. Disfluency, GPT-Realtime: hesitations 0.700, false starts 0.667, fillers 0.621, pauses 0.556, **self-corrections 0.588**. Cascaded collapses to **0.176** on self-corrections because Whisper finalizes the transcript before the correction arrives.

**Two documented pathologies that are Parcel's own bug list:**
- **Gemini Live 3.1 "Silent Worker": in 22% of scenarios it executed correct tool calls but produced no speech — 86% of those had perfect tool selection and arg accuracy, and scored Pass@1 = 0 anyway.** This is *exactly* the silence bug one of Parcel's five fix cards addressed. It is a published, named, quantified failure mode with a frontier model exhibiting it.
- **Ultravox interrupts 47.9% of turns** via premature filler speech (88% filler rate).

**Parcel comparability: PARTIALLY comparable — the closest available, and the target Parcel should aim at.**

Aligned: real human voice, uncontrolled room, commodity mic, small fixed deterministic tool surface (3–4 vs. Parcel's 7), spoken single-request scenarios, and **GPT-Realtime is on the board** — the same model family Parcel embeds.

Not aligned, and these block a direct claim:
- Parcel's scoring is **PASS / PARTIAL / FAIL / needs-review / blocked / not-attempted**. FDB-v3's Pass@1 is **binary**. Parcel's PARTIAL bucket (9 in live_run_1, **15** in replay_run_1) has no analogue and would have to be adjudicated to pass or fail. Where those 15 land swings the headline by ~29 points.
- Parcel's 52-query corpus contains **adversarial categories FDB-v3 does not have at all** — nav-invalid, estop-neg, safety-refusal, capability-honesty, ambiguous. FDB-v3 has no should-abstain items. So Parcel's corpus is *harder in composition*, and a raw Pass-rate comparison is unfair to Parcel in a way that must be disclosed.
- Both Parcel corpus runs **predate the five fix cards**. replay_run_1 had a **dead hosted lane from q30**, so ~20 of its 52 verdicts describe a corpse.

**Positioning anyway, fully caveated:**

| | Denominator | PASS | Rate |
|---|---|---|---|
| live_run_1 (all 52, not-attempted = fail) | 52 | 13 | **25.0%** [14.0–38.8%] |
| live_run_1 (attempted only) | 35 | 13 | 37.1% |
| replay_run_1 (all 52) | 52 | 10 | 19.2% |
| GPT-Realtime, FDB-v3 | 100 | — | **60.0%** |

**This comparison should be labeled invalid and shown anyway**, because the direction is unambiguous even after every correction: 25.0% vs 60.0% is a 35-point gap that PARTIAL-adjudication (max +17 pts if all 9 PARTIALs became PASS) and adversarial-composition adjustment cannot close. The honest sentence: *"On a shape-similar but non-identical spoken tool-use task, a pre-fix Parcel build passed 25% of 52 queries where GPT-Realtime alone passes 60% of 100 FDB-v3 scenarios. Parcel's corpus is harder in composition and its build was five fix-cards stale, so the gap is an upper bound on the deficit, not an estimate of it — and the current build is unmeasured."*

Meanwhile **nav-direct 5/5 vs. GPT-Realtime's Easy-tier 0.750**: 5/5 has a 95% lower bound of 47.8%. It does **not** establish parity, let alone superiority.

**Latency: NOT comparable as currently reported.** Parcel's realtime p50 0.78s / max 1.69s is explicitly **turn-level, not first-token**, on single-step requests. FDB-v3's 6.89s for GPT-Realtime is **task-completion latency over chained multi-step API calls**. Parcel's number is nearer FDB-v3's *first-response-word* component, which the retrieved table does not break out per model. **Quoting 0.78s against 6.89s would be a 9× flattering error.** Parcel must split its latency into FDB-v3's three components before any latency claim.

### 7b. VoiceAgentBench (Feb 13, 2026) — closest in *shape* to Parcel's corpus

✅ [arXiv:2510.07978](https://arxiv.org/abs/2510.07978)

**5,500+ synthetic spoken queries**, English + 6 Indic languages, ~30% Indian-context. Six categories: Single Tool Calling (142–710), Single Tool with Retrieval (179–895), Parallel Multi-Tool (125–625), Sequential Dependent Tools (40–200), Multi-turn Dialogue (398), **Safety Evaluations (80–400)**. Voice diversity via speaker-embedding-driven TTS voice conversion.

**Metrics — four separate numbers, not one fused verdict:** **TS** (tool selection, exact regex name match), **TCS** (tool call structure, Pydantic schema compliance), **PF** (parameter filling, GPT-4o-mini semantic judge), **RR** (refusal rate on adversarial/harmful requests).

**Results.** ASR→LLM pipelines beat end-to-end SpeechLMs: **up to 60.6% average parameter-filling accuracy on English**. Best SpeechLM KimiAudio 7B **53.97% PF English**, dropping to **~25% Indic average**. **Sequential dependent tool calling: best model 14.8%.** Safety: KimiAudio 7B refusal rate **51.25% English → 2.94% Indic**.

**Parcel comparability: PARTIALLY comparable — best available *unit* for a refusal-rate claim.**

Parcel's corpus is structurally a VoiceAgentBench: spoken query → gold tool label → verdict, with a safety split. Three transformations needed:
1. **Decompose the fused verdict into TS / TCS / PF.** Parcel reports PASS/PARTIAL/FAIL; VAB reports three orthogonal binaries. Most of Parcel's PARTIAL bucket is probably "TS correct, PF wrong" — which VAB scores as TS=1, PF=0, a *legible* result rather than a mushy one. **This alone is worth doing and costs only a rescoring pass.**
2. **Map Parcel's 15 categories onto VAB's 6.** nav-direct/gesture/status/set_pose → Single Tool Calling; compound → Parallel or Sequential; safety-refusal + capability-honesty + nav-invalid + estop-neg → the Safety/RR split; memory/scene → retrieval.
3. **Fix n.** Parcel's safety-adjacent categories have ~3–5 items each. VAB's safety split has 80–400.

Reference for a Parcel RR claim: **51.25% English refusal rate for the best-tested SpeechLM** — i.e. refusal is *not* solved in voice, and a modest Parcel number would still be respectable. Note also that VAB found **ASR→LLM cascades beat end-to-end SpeechLMs**, which is architecturally relevant to Parcel's hosted-realtime choice.

### 7c. gpt-realtime vendor numbers — ceiling reference for Parcel's own model class

⚠️ (OpenAI's blog returned 403; numbers via secondary reporting of [openai.com/index/introducing-gpt-realtime](https://openai.com/index/introducing-gpt-realtime/), Aug 2025): **ComplexFuncBench (audio) 66.5%** for gpt-realtime vs 49.7% for the Dec-2024 preview; **MultiChallenge (audio) 30.5%** vs 20.6%; improved Big Bench Audio. ComplexFuncBench itself ✅ [arXiv:2501.10132](https://arxiv.org/html/2501.10132v1) — multi-step, constrained, long-context function calling.

**Parcel comparability: NOT comparable** (ComplexFuncBench is long-context multi-step over large API surfaces; Parcel is single-step over 7 tools). **Value as a ceiling:** Parcel runs **gpt-realtime-2.1-mini** — a *mini*, whose function-calling and multi-turn numbers are unpublished and should be assumed materially below the flagship's 66.5% / 30.5%. Also: **MultiChallenge-audio at 30.5% for the best hosted realtime model** is the right context for Parcel's "0/6 asked the required follow-up question from injected state" — multi-turn instruction retention in voice is at ~30% for the frontier. Parcel's 0/6 [CI 0–45.9%] is *consistent with* the frontier rate, not clearly below it. That is a legitimate defense and Parcel should use it rather than treating 0/6 as a scandal.

### 7d. Also on the map, not fetched in depth
EVA-Bench ([arXiv:2605.13841](https://arxiv.org/pdf/2605.13841)), EchoChain (full-duplex state-update under interruptions, [arXiv:2604.16456](https://arxiv.org/pdf/2604.16456)), IHBench (post-interruption recovery in structured workflows, [arXiv:2606.19595](https://arxiv.org/pdf/2606.19595)), VoiceBench ✅ [TACL 2026](https://aclanthology.org/2026.tacl-1.18/) (6,783 spoken instructions; general knowledge / instruction-following / safety). VoiceBench is the closest thing to "IFEval for voice" and is the right place to look if Parcel ever wants a *spoken instruction-following* number as distinct from a tool-calling one.

---

## 8. SafeAgentBench — embodied hazardous-instruction refusal

✅ [arXiv:2412.13178](https://arxiv.org/html/2412.13178v1) · [safeagentbench.github.io](https://safeagentbench.github.io/)

**750 tasks: 450 hazardous + 300 safe controls.** 600 detailed (300 hazardous + 300 matched safe), 100 abstract hazardous, 50 long-horizon. 10 hazard categories, 3 task types. Runs in SafeAgentEnv with a low-level controller. Metrics: **rejection rate**, success rate (goal-condition), success rate (LLM-judged), execution rate.

**Headline:** across 8 GPT-4-powered embodied baselines, **the highest rejection rate was 10%, and half the agents rejected nothing.** MLDT: 69% success on hazardous detailed tasks at a **5% rejection rate.** Most baselines exceeded 30% success on hazardous tasks.

**Parcel comparability: PARTIALLY comparable, and there is a construct error to avoid.**

**Parcel's `estop-pos` is NOT a SafeAgentBench item.** An e-stop is a *commanded* stop — a **should-act** task where the correct behavior is to comply promptly. SafeAgentBench measures **should-abstain**: refusing a dangerous instruction the user actually wants executed. Parcel's true analogues are `safety-refusal`, `nav-invalid`, and `estop-neg` (correctly *not* latching on a false-positive) — and those categories are the ones whose results are **not cleanly reported** in either corpus run.

If Parcel does report them: the bar is astonishingly low — **10% is state of the art among embodied GPT-4 baselines.** Parcel's architecture (a local SafetySupervisor that validates before the executive acts) should beat that trivially, and this is the one place where Parcel's design difference is likely to produce a *favorable* comparison against published numbers. Caveats: SafeAgentBench is AI2-THOR household manipulation, Parcel is quadruped navigation; hazard taxonomies don't overlap; n=450 vs Parcel's ~3–5 items per relevant category.

---

## Summary comparability table

| Benchmark | Date | Parcel status | If partial, what transformation |
|---|---|---|---|
| IFEval | 2023 | **NOT** | none possible — wrong construct |
| IFBench | 2025 | **NOT** | none possible; but its OOD lesson applies to Parcel's self-authored corpus |
| BFCL v4 — AST/simple/multiple | 2025–26 | **PARTIAL** | need ≥100 distinct in-surface commands × 1 trial; today n_task=1 |
| **BFCL v4 — irrelevance ("Hallucination", 10% of overall)** | 2025–26 | **PARTIAL ★** | need ≥30–50 out-of-surface prompts; 5/6 → IrrelAcc 16.7% [0.4–64%] |
| BFCL v4 — multi_turn_miss_param | 2025 | NOT (v4 changed semantics) | Parcel's 0/6 tests the retired v3 rule |
| **AgentAbstain** | Jul 2026 | **PARTIAL ★** | need ≥30 matched act/abstain pairs → Paired Accuracy + CAR |
| ToolBeHonest | 2024 | PARTIAL (conceptual only) | composite 3-level score not reconstructible from 6 trials |
| SABEval / structural alignment | Apr 2026 | PARTIAL (mechanism) | reframes 83.3% as in-regime, not anomalous |
| ToolFailBench | Jul 2026 | **NOT** | paper explicitly excludes Parcel's failure mode |
| τ-bench / τ² / τ³ | 2024–26 | **NOT** | needs user simulator + DB + policy doc + k trials |
| **τ pass^k *framing*** | — | **adopt it** | k=5 replay of the 52-corpus gives real pass^5 |
| ToolBench / API-Bank / T-Eval | 2023–24 | **NOT** | large-API-surface construct; skip |
| **Full-Duplex-Bench-v3** | Apr 2026 | **PARTIAL ★★★** | adjudicate PARTIAL→binary; adopt TS-F1/ArgAcc/Pass@1/turn-take/3-part latency |
| VoiceAgentBench | Feb 2026 | **PARTIAL ★★** | split verdict into TS/TCS/PF/RR; map 15 cats → 6 |
| SafeAgentBench | 2024 | PARTIAL | report safety-refusal/nav-invalid/estop-neg, not estop-pos |
| ComplexFuncBench / MultiChallenge audio | 2025 | NOT (ceiling ref) | useful context for the 0/6 follow-up result |

---

# What Parcel would have to run to claim a benchmark number

Cheapest first. Costs assume the observed ~$0.85 per 52-query replay and ~$0.002–0.006 per short response.

### Tier 0 — free, today, pure re-scoring of artifacts that already exist

**0.1 — Re-score existing replay transcripts into FDB-v3's metric set.** *Cost: $0. Reuses: replay_run_1 + live_run_1 transcripts, pre-registered gold labels.*
Stop reporting PASS/PARTIAL/FAIL. Emit **Tool Selection F1**, **Argument Accuracy**, **Pass@1 (binary conjunction)**, **turn-take rate**, and **interruption rate** — the exact columns of FDB-v3 Table 2. The 15 PARTIALs in replay_run_1 almost certainly decompose into "TS=1, ArgAcc=0", which is a *legible* result. This single pass makes every future Parcel number sit next to a published table (GPT-Realtime 0.876 / 0.680 / 0.600) instead of floating free. **Highest value-per-dollar item in this list.**

**0.2 — Recompute the pre-fix runs with explicit denominators and CIs.** *Cost: $0.*
State live_run_1 as 13/52 = 25.0% [14.0–38.8%] with the not-attempted policy declared, and stop quoting bare fractions. Attach Clopper-Pearson intervals to 6/6, 5/5, 7/7, 5/6, 0/6 as in §0. Half of Parcel's credibility problem is missing intervals, and it costs nothing to fix.

**0.3 — Unit-test the e-stop latch to arbitrary confidence.** *Cost: $0 (local, deterministic). Reuses: SafetySupervisor + task executive.*
Split the e-stop into (i) ASR recognizes the phrase [stochastic] and (ii) recognized phrase latches [deterministic local code]. Half (ii) is unit-testable at 10⁻⁶ for free. The strongest existing evidence — **estop-pos 3/3 with the hosted lane dead** — is evidence about (ii), and unit tests turn it into a real guarantee. This converts the weakest safety claim into the strongest one without a single live trial.

### Tier 1 — under $10 and under a day

**1.1 — Re-run the 52-query corpus on the current build.** *Cost: ~$0.85 + operator time. Reuses: replay corpus, gold labels, replay harness.* **Mandatory prerequisite to every external claim.** Both existing runs predate the five fix cards (silence, scene answerability, memory recall, unknown-place refusal, safety ring) and replay_run_1's hosted lane died at q30. Until this exists, Parcel's honest headline is *"the current build has never been measured."* Report the delta vs. live_run_1 as an internal regression, explicitly not a benchmark.

**1.2 — k=5 replay of all 52 → real pass^1 and pass^5.** *Cost: ~$4.25 (5 × $0.85). Reuses: same harness, no new code.* **The highest-leverage cheap upgrade in this document.** It closes the diversity×trials gap from §0 on the corpus axis and yields per-category pass^5 in τ-bench's semantics — the metric agent-eval reviewers actually respect. Parcel could then write *"pass^5 = X on our 52-task suite"*, a self-defined benchmark with borrowed, well-understood reliability semantics. Expect a large drop: the published telecom decay is 62.61% → 32.17% by pass^4, and Parcel's per-query variance is likely higher.

**1.3 — Expand the irrelevance / abstention cell into a real measurement.** *Cost: ~$2–5. Reuses: the chat-API bench harness (it already manipulates the tool surface and runs 6 trials/cell).*
Build **30–50 out-of-surface prompts** against the fixed 7-tool surface ("fetch me a beer", "take a photo", "open the door", "call my mom", "pick that up"), deliberately spanning near-miss (navigation-adjacent, where `navigate_to` is structurally aligned) and far-miss. Score binary: *any* tool call emitted = fail. **Also build the matched should-act half** so you can report **AgentAbstain Paired Accuracy and CAR**, not just abstain rate.
Reference points to publish against: AgentAbstain best abstain 79.0% / worst 36.4%, S5 mean paired 61%; BFCL IrrelAcc GPT-4-0125 61.35 / Llama-3-70B 50.47; SABEval 41–91% false-invocation under structural alignment. **This converts Parcel's most embarrassing anecdote (5/6, CI 36–99.6%) into its most credible measurement, for under $5.**

**1.4 — Measure the *disposer chain*, not just the proposer, on 1.3.** *Cost: marginal on top of 1.3.* Run every fabricated `navigate_to` from 1.3 through SafetySupervisor → intent router → **plan admission**. Report **two** numbers: proposer irrelevance accuracy (comparable to BFCL/AgentAbstain) and **end-to-end system irrelevance accuracy after local disposal**. If the chain catches the fabrications, Parcel can claim something **no leaderboard model can**: architectural abstention that doesn't depend on the LLM noticing. AgentAbstain explicitly documents *post-hoc abstention* (act first, refuse afterward) as a frontier pathology — Parcel's architecture is the named cure and it has never been measured as such. **This is Parcel's single best story and it is currently untold.**

**1.5 — Power the e-stop ASR half.** *Cost: operator time, ~1–2 sessions. Reuses: live capture rig, reSpeaker, the untested ASR-variant list.*
7/7 caps failure at 43%. **60 consecutive successes → 95% upper bound of 5%. ~300 → 1%.** Stratify across ≥6 phrasings × ≥3 noise/distance conditions rather than repeating the canonical utterance, so |T| > 1 and pass^k is actually defined. Also test **estop-neg** (false-positive latching) at comparable n — a stop that fires on "don't stop" is a product failure that current evidence cannot rule out.

### Tier 2 — a few days, real external comparability

**2.1 — Run BFCL v4's `irrelevance` + `live_irrelevance` subsets.** *Cost: ~half a day of adapter work + small inference spend. `--partial-eval` (added Sep 27, 2025) makes subset-only runs cheap.* Gives a genuinely leaderboard-comparable number. Caveat that must ship with it: BFCL's tools are not Parcel's, so this measures **the hosted model + Parcel's system prompt + SafetySupervisor policy**, not the robot. Phrase it exactly that way.

**2.2 — Adopt VoiceAgentBench's metric decomposition on Parcel's corpus.** *Cost: rescoring + category mapping.* Report TS / TCS / PF / RR separately. Reference: best English PF 60.6% (ASR-LLM), KimiAudio 7B 53.97%; refusal rate 51.25% English. Gets Parcel a **refusal-rate number in a published unit** — the thing it most lacks.

**2.3 — Split latency into FDB-v3's three components.** *Cost: one instrumented capture session, or free if existing audio is timestamped.* Report **first-response-word / tool-call-invocation / task-completion** latency plus **filler rate** and **interruption rate**. Today's "realtime p50 0.78s" is turn-level on single-step requests and would be a ~9× flattering error next to FDB-v3's 6.89s task-completion figure. Fix before anyone quotes it.

**2.4 — Run FDB-v3 proper.** *Cost: 1–2 days.* Public: [arXiv:2604.04847](https://arxiv.org/abs/2604.04847), [GitHub](https://github.com/DanielLin94144/Full-Duplex-Bench). Point Parcel's **audio gateway + hosted lane** at FDB-v3's four domains, swapping in their 3–4 deterministic mock APIs. Yields a **directly comparable Pass@1** against GPT-Realtime 0.600 / Gemini Live 3.1 0.540 / Cascaded 0.450. Caveat: it benchmarks Parcel's *voice stack*, not its robot policy, since the tool surface is theirs. Bonus: the disfluency and self-correction splits (GPT-Realtime 0.588 on self-corrections) directly stress the barge-in and re-planning paths, and the "Silent Worker" metric is the published version of the bug Parcel already fixed.

### Explicitly not worth doing
- **IFEval / IFBench** — wrong construct, no transformation exists.
- **τ²/τ³ text domains** — needs an LLM user simulator, DB, and policy documents; high cost, and aggregator leaderboards disagree by ~20 points so the number wouldn't even be legible.
- **ToolBench / API-Bank** — stale and saturating; built for large open API surfaces, the opposite of Parcel's fixed 7-tool design.
- *Watch, don't run:* **τ³-bench's full-duplex voice mode** (v1.0.1, July 2026) explicitly targets OpenAI/Gemini/xAI realtime providers. If it accumulates a public voice leaderboard, it becomes the second serious external target after FDB-v3.

### The one-line claim Parcel can honestly make after Tier 0 + Tier 1 (~$10, ~2 days)
> *"On a 52-task spoken corpus with pre-registered gold labels, the current Parcel build achieves pass^1 = X and pass^5 = Y (FDB-v3 metric decomposition). On n=40 out-of-surface requests, the hosted proposer abstains A% of the time — comparable to the 36–79% range across 17 frontier models on AgentAbstain — while Parcel's local disposal chain raises end-to-end abstention to B%. E-stop: 0 failures in 60 stratified live trials (95% upper bound on failure rate: 5%), with the latch path unit-verified independently of the hosted lane."*

Everything in that sentence is reachable for under $10 and two days of operator time. **Nothing in it is claimable today.**

---

## Sources

Primary ✅: [IFEval (arXiv:2311.07911)](https://arxiv.org/pdf/2311.07911) · [IFBench](https://github.com/allenai/IFBench), [OpenReview](https://openreview.net/forum?id=yfYgwjj5F8), [Ai2 blog](https://allenai.org/blog/ifbench-artificial-analysis) · [BFCL leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html), [CHANGELOG](https://github.com/ShishirPatil/gorilla/blob/main/berkeley-function-call-leaderboard/CHANGELOG.md), [BFCL v1 blog](https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html), [v4 memory](https://gorilla.cs.berkeley.edu/blogs/16_bfcl_v4_memory.html), [v4 web search](https://gorilla.cs.berkeley.edu/blogs/15_bfcl_v4_web_search.html), [v4 format sensitivity](https://gorilla.cs.berkeley.edu/blogs/17_bfcl_v4_prompt_variation.html), [EvalScope BFCL-v4](https://evalscope.readthedocs.io/en/v1.2.0/third_party/bfcl_v4.html) · [AgentAbstain (arXiv:2607.10059)](https://arxiv.org/html/2607.10059), [site](https://agentabstain.github.io/) · [ToolBeHonest (arXiv:2406.20015)](https://arxiv.org/abs/2406.20015), [GitHub](https://github.com/toolbehonest/toolbehonest) · [Structural Alignment Bias (arXiv:2604.11322)](https://arxiv.org/pdf/2604.11322) · [ToolFailBench (arXiv:2607.04686)](https://arxiv.org/html/2607.04686v1) · [AgentHallu (arXiv:2601.06818)](https://arxiv.org/html/2601.06818v1) · [τ-bench (arXiv:2406.12045)](https://arxiv.org/pdf/2406.12045), [Sierra blog](https://sierra.ai/uk/blog/tau-bench-shaping-development-evaluation-agents), [τ²-bench (arXiv:2506.07982)](https://arxiv.org/abs/2506.07982), [sierra-research/tau2-bench → τ³](https://github.com/sierra-research/tau2-bench), [leaderboard submission](https://github.com/sierra-research/tau2-bench/blob/main/docs/leaderboard-submission.md) · [Full-Duplex-Bench-v3 (arXiv:2604.04847)](https://arxiv.org/html/2604.04847v1), [demo](https://daniellin94144.github.io/FDB-v3-demo/), [GitHub](https://github.com/DanielLin94144/Full-Duplex-Bench) · [VoiceAgentBench (arXiv:2510.07978)](https://arxiv.org/abs/2510.07978) · [VoiceBench (TACL 2026)](https://aclanthology.org/2026.tacl-1.18/) · [SafeAgentBench (arXiv:2412.13178)](https://arxiv.org/html/2412.13178v1), [site](https://safeagentbench.github.io/) · [ComplexFuncBench (arXiv:2501.10132)](https://arxiv.org/html/2501.10132v1) · [API-Bank (arXiv:2304.08244)](https://arxiv.org/pdf/2304.08244) · [EVA-Bench](https://arxiv.org/pdf/2605.13841), [EchoChain](https://arxiv.org/pdf/2604.16456), [IHBench](https://arxiv.org/pdf/2606.19595)

Secondary/aggregator ⚠️: [benchlm.ai BFCL v4](https://benchlm.ai/benchmarks/bfcl-v4), [benchlm.ai τ²](https://benchlm.ai/benchmarks/tau2-bench), [benchlm.ai IFEval](https://benchlm.ai/benchmarks/ifeval) · [sophon.at τ²](https://sophon.at/evals/tau2-bench) · [Artificial Analysis IFBench](https://artificialanalysis.ai/evaluations/ifbench) · [llm-stats IFBench](https://llm-stats.com/benchmarks/ifbench) · [pricepertoken BFCL v3](https://pricepertoken.com/leaderboards/benchmark/bfcl-v3) · [benchmarkingagents: BFCL](https://benchmarkingagents.com/bfcl-function-calling/), [τ-bench](https://benchmarkingagents.com/tau-bench-retail-airline/), [τ³-bench](https://benchmarkingagents.com/tau3-bench/), [tool-use comparison](https://benchmarkingagents.com/best-benchmarks-for-tool-use/) · [EmergentMind BFCL v4](https://www.emergentmind.com/topics/berkeley-function-calling-leaderboard-v4-bfclv4), [EmergentMind τ²](https://www.emergentmind.com/topics/tau2-bench) · [AISBench τ²](https://ais-bench-benchmark.readthedocs.io/en/latest/extended_benchmark/agent/tau2_bench.html) · [Inspect Evals BFCL](https://ukgovernmentbeis.github.io/inspect_evals/evals/assistants/bfcl/index.html) · [OpenAI gpt-realtime](https://openai.com/index/introducing-gpt-realtime/) (403 on fetch; numbers via secondary reporting)