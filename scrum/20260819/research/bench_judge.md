# Significance-Judge Bench — Final Report

## Methodology

**Gold set** (authored BEFORE any model call, committed to `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/csbench/fable-sigjudge/gold_set.jsonl`): 44 state-delta cases, each = context (mission, owner situation, seconds-since-companion-last-spoke) + 1-3 buffered deltas, labeled forward/suppress by me with a one-line rationale. Provenance: vocabulary and scenarios drawn verbatim from the real runtime snapshot (`owner_state.json`: battery/follow/mic_arming/dialogue_state/duplex fields, real ped ids) and the real mission timeline (`proof_final.txt`: `grid_track`, `planned|person_stop`, `planned|obstacle_stop`, "releasing that approach", "Obstacle clearance restored", `navigation_disabled`, lane-stall reconnects), plus the owner's four verbatim design cases (door-ask, run-with-me pace ask, desk-orbit refusal). Composition: **26 clear judge-band** (12 forward / 14 suppress), **8 borderline** (marked, my label; 7 suppress / 1 forward), **5 always-band sanity** (safety stop, 2 terminals, refusal, manual stop — all forward), **5 never-band sanity** (per-tick telemetry — all suppress). Judge prompt encodes the drafted policy (score 0-1 + one-line reason, JSON only, threshold 0.5); identical prompt for every backend, temperature 0 (locals), single attempt per case. Composition set (8 tasks, 3 deltas each, required-fact checklists) also authored before runs: `compose_set.jsonl`. Harness: `judge_bench.py`; raw results in `results_*.jsonl` in the same dir.

**Backends:** the stack's actual Gemma-4-26B-A4B QAT Q4 at `:8080` (llama.cpp CPU, `--reasoning auto`, healthy — no restart needed); Ministral-3-8B-Instruct-2512 Q4_K_M served by me on `:8081` with the same llama.cpp binary; OpenAI `gpt-5-nano` at two reasoning efforts as the frontier reference; `gpt-5-mini` (low effort) as composition grader.

## 1. Judge agreement with gold (n=44 per model, single pass)

| model | all | clear judge (26) | borderline (8) | always (5) | never (5) | malformed | missed forwards | false forwards | lat p50 | lat p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| **Gemma-4-26B (local)** | **41/44** | 24/26* | 7/8* | 5/5 | 5/5 | **3** | 0 | 0 | 22.7s | 45.7s |
| **Ministral-3-8B (local)** | **40/44** | 24/26 | 6/8 | 5/5 | 5/5 | 0 | 1 | 3 | **2.8s** | **4.8s** |
| gpt-5-nano low (API) | 39/44 | 24/26 | 5/8 | 5/5 | 5/5 | 1 | 0 | 4 | 1.7s | 2.5s |
| gpt-5-nano minimal (API) | 30/44 | 17/26 | 3/8 | 5/5 | 5/5 | 0 | 0 | **14** | 0.7s | 0.9s |

\* Gemma's only "misses" are the 3 malformed rows (F02, F11, B05) — **on every case that parsed, Gemma matched gold 41/41 (100%)**, including all 7 parsed borderlines. Retried at max_tokens=1536, all three parsed and matched gold (F02 forward 0.8, F11 forward 0.65, B05 suppress 0.2) — i.e. **budget-fixed Gemma = 44/44**.

**Agreement gap vs frontier: there is none — the locals win.** Gemma (41-44/44) and Ministral (40/44) both beat the cheap frontier reference (39/43 at low effort). gpt-5-nano at minimal effort is unusable: 14/26 false forwards, rationalizing everything as "plan/expectation change" (verbatim on routine progress ticks: `"plan/expectation change: ETA progress; near sidewalk target with stable progress"` → 0.65 forward).

## 2. Failure modes, verbatim

- **Gemma malformed = reasoning overrun, not JSON errors.** All 3 malformed rows show `completion_tokens=768` (exactly the cap) with ~2,850-char thinking and empty content. A "do NOT deliberate" instruction did not help (template still opens a think block; probe: `nothink_probe.out`, reasoning 861-1393 chars, same verdicts). Fix is server-side (reasoning budget cap / bigger max_tokens), not prompt-side. Also 0/41 strict JSON — every Gemma output arrived ```json-fenced (trivially strippable, but the parser must expect it).
- **Ministral's one real judge miss is a policy collision:** F08 (STT died mid-voice-session, mic disarmed) → `score=0.0 "infrastructure plumbing (STT unreachable)"`. My prompt lists "capability breaking such as the microphone" under forward AND "infrastructure plumbing" under suppress; the 8B picked the wrong rule. Gemma resolved it correctly (`0.9 "The STT/microphone capability has failed while the owner is actively using voice interaction."`). One dedup miss: S11 (plan admitted 1s after verbal ack) → forwarded 0.9.
- **gpt-5-nano low produced the only truly broken JSON of the day:** F07 raw output = `{"score": 0. Eighty?}`.
- **Borderline consensus check:** on B01 (second person-block 40s after narrating the first) and B04 (ETA 20s→33s) three of four models voted forward against my suppress labels — those two labels are genuinely contestable; treat those 2 "misses" as judgment calls, not errors. On B02/B03/B05/B06/B07/B08 the better models agreed with me.

## 3. Latency (judge call, one buffered batch)

- Gemma: contended slice (my Ministral server busy-spinning ~31 cores concurrently, n=9) p50 28.3s / max 53.2s; clean slice (n=35) **p50 18.0s / p95 37.9s / min 10.2s**. Caveat: box shared with another workflow (~4 cores) throughout; latencies were also non-stationary (10-16s when quiet, 22-47s under load).
- Ministral: p50 2.8s / p95 4.8s (n=44). gpt-5-nano: low 1.7/2.5s, minimal 0.7/0.9s (n=44 each).

## 4. Composition test (3 buffered deltas → one companion sentence; grader = gpt-5-mini)

| model | valid lines | faithful | invented facts | required facts covered | tone | latency |
|---|---|---|---|---|---|---|
| Gemma @768 tokens | **1/8** (7 reasoning overruns) | — | — | — | — | ~26s |
| Gemma @2048 tokens | 8/8 | 8/8 | 0 | 18/24 | 8/8 | p50 32.9s (23.9-51.0) |
| Ministral-3-8B | 8/8 | 6/8 | 2 | 17/24 | 8/8 | p50 1.5s (1.3-2.0) |

Verbatim failures: Ministral C1 addressed the owner as the obstacle — `"I've stopped to wait—you're too close to move safely, please step aside."` (the blocker is a stranger; owner is 2m behind); Ministral C7 asserted instead of asking — `"I'm slowing to match you—let's walk together now."` (robot is still in run gait; design requires the ASK; graded 0/3 facts). Gemma C7 nailed the design case: `"You've slowed to a walk, so should I slow my pace to match you?"`. Grader caveat: gpt-5-mini passed Gemma C3 `"I'm taking a longer route around you..."` as faithful, but "around you" is the same wrong-referent slip — human review still needed on referents; the mini grader is not airtight.

## 5. Mistral-7B status

Classic Mistral-7B-instruct GGUF: **NOT downloaded** — the repo already vendors the current Mistral-family small model (`models/reasoner/ministral-3-8b-instruct-2512/Ministral-3-8B-Instruct-2512-Q4_K_M.gguf`), which I served on the identical llama.cpp infra and tested fully as above. Pulling the 2023-era 7B would have been a strictly worse comparator for the same family; if the owner specifically wants v0.3 numbers, it is a ~4.4GB pull and a rerun of the same harness (`judge_bench.py judge --backend ministral`).

## 6. Spend

OpenAI total **$0.0176** of the $1.50 cap (gpt-5-nano: 90 calls, 46,390 in / 9,543 out = $0.0061; gpt-5-mini grader: 16 calls, 5,530 in / 5,061 out = $0.0115; prices confirmed against the live pricing page: nano $0.05/$0.40, mini $0.25/$2.00 per M). Local calls: ~120, free. Cleanup: my Ministral server is stopped; the pre-existing Gemma server on :8080 is untouched.

## What this means for the design

1. **The judge band is worth it, and it can be entirely local.** Both local models beat the cheap-frontier reference on this policy; deterministic-only would either forward B01/B04/F07-class noise or stay mute on F03/F05/F06/F12-class stalls that have no clean deterministic signature (progress-stall, pace-mismatch, social-situation cases are exactly where rules run out).
2. **But Gemma-as-configured is the wrong engine for a 0-1 whisper score.** ~18s p50 / ~38s p95 per verdict on the shared CPU means the buffer's contents are stale by the time the score lands, and `--reasoning auto` + finite max_tokens silently eats 7% of judge calls and 7/8 compose calls at 768 tokens. If Gemma stays, the lane needs: max_tokens ≥1536 (verdicts) / ≥2048 (composition), fence-tolerant JSON parsing, and a fail-closed timeout (treat no-verdict as suppress for judge band; the always-band never waits on the judge anyway — keep that).
3. **Ministral-3-8B is the practical judge.** 40/44 at 2.8s p50, zero malformed, and its 8s-class errors are prompt-fixable: the one dangerous miss (F08) is a documented rule collision — add one line to the whisperer prompt ("if the owner is directly affected — e.g. they can no longer be heard — it is never plumbing") and re-bench. A plausible production shape: Ministral scores every buffer flush (cheap, 3s), Gemma optionally re-checks only scores in a 0.35-0.65 uncertainty window.
4. **Composition should not be given to the small model unsupervised.** Ministral invents pragmatics (2/8 — wrongly casting the owner as the obstacle, asserting an action instead of asking). Gemma composes faithfully but at 33s p50. Given the hosted voice model already speaks well, the cheaper design is: judge locally, forward a *structured* system item (facts, not prose) through the existing floor-gated narration channel, and let gpt-realtime do the phrasing — composition quality was the frontier model's one unambiguous comparative strength here.
5. **Rate caps and dedup must stay outside the judge** — confirmed empirically: the models' worst shared instinct is re-forwarding repeats (S11, B01 forwarded by 2-3 of 4 models despite "seconds_since_companion_last_spoke" being right there in context).

All artifacts: `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/csbench/fable-sigjudge/` — `gold_set.jsonl`, `compose_set.jsonl`, `judge_bench.py`, `analyze.py`, `results_{gemma,ministral,openai_low,openai_minimal}.jsonl`, `results_gemma_retry.jsonl`, `nothink_probe.out`, `comps_{gemma,gemma_2048,ministral}.jsonl`, `graded_{gemma,ministral}.jsonl`, run logs.