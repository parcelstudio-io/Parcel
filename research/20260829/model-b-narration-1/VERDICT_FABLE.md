# MB-1 — VERDICT (Fable, the wave's designated verifier)

Verifier: Fable (parcel-0e), 2026-08-29 20:0x EDT. Design frozen 15:3x;
pre-run amendments M1–M9 at 15:41/15:53/15:45 (appendix). Executor: Opus,
killed by the spend limit after RESULTS §0–§3 were written and the hosted
D arm had been truncated by the provider's daily request quota (2/120
scenarios); the executor's `RECOVERY.md` reconstructs 119 Q sessions from
the ledger and the isolated research database (its recovered rows carry
`UNMEASURED_NOT_RECOVERED` latency). A foreign `VERDICT.md` (Sol, 18:38)
exists here; I concur with its table and add three readings. Evidence
tiers: `replay` (scripted responder; local Qwen2.5-7B Q4 on CPU — the
vendored llama.cpp has no CUDA backend, deviation recorded), `hosted-live`
(gpt-realtime-2.1-mini, text mode, via `submit_realtime_text` under the ear
governor; 550 ledger rows, **$1.33** for the full Q run; wave ledger
**$2.21** of the $5 cap; the owner's ledger untouched).

## Verdicts

| | bar (DESIGN + M8) | scripted responder | local Qwen-7B (CPU) | hosted gpt-realtime-mini Q (n = 120 scenarios / 164 turns) | verdict |
|---|---|---|---|---|---|
| **H-MB1a** grounding | Q ≥ 0.9 and lower-CI(Q − D) > 0 | Q 1.000 / D 0.885 | Q 0.964 / D 0.900 | Q **0.61–0.73** (D truncated 2/120) | **REFUTED** for the hosted model; the Q − D contrast is UNMEASURED |
| coverage (M8) | Q ≥ D | 0.969 / 0.769 | 0.52 / 0.23 | 0.23–0.29 | Q ≥ D holds everywhere, at a low absolute level on real models |
| **H-MB1b** timing | ack ≥ 0.9, completion ≥ 0.9, resume ≥ 0.8, premature ≤ 0.05 | 1.00 / 1.00 / 1.00 / 0.000 | 0.24 / 0.93 / 0.20 / — | 0.44 / 0.07–0.16 / 0.33–0.37 / 0.03–0.08 | **REFUTED** |
| **H-MB1c** invented actions | 0 | 0 | 6 (all perception claims) | 45 flags in 39 turns; blind local judge confirms **4**, rejects 41 | **REFUTED** on the bar; the deterministic matcher is over-broad (91 % disagreement) and must be recalibrated against human labels before its raw count means anything |
| **H-MB1d** local | ≥ 0.8 × hosted grounding at ≤ 400 ms TTFT | — | grounding **exceeds** hosted (0.964 vs ≤ 0.73); TTFT p50 633 ms on CPU | grounding half **CONFIRMED**, latency half **REFUTED** (a CPU number; GPU unmeasured) |
| keys-turn behaviour (M8 fourth bar) | inability stated, no perception claim | 15/15 | 0/15 | 1/25 | **REFUTED** on real models |

## Three readings Sol's verdict does not state

1. **The scorer works; the models don't follow the whisper.** The scripted
   responder scores 1.000 on the same instrument the hosted model scores
   0.61–0.73 on, so the gap is model behaviour, not harness gameability
   (M8's coverage term prevents the "say less" exploit; Q's coverage was
   0.23–0.29 on the hosted model — it *did* say less).
2. **A local 7B paraphraser grounded better than the hosted mini** (0.964
   vs 0.61–0.73; 6 vs 45 flags) — on CPU. With the GPU backend it would meet
   the latency bar by every published number. This is the strongest
   argument for Sol's "deterministic utterance contract + local paraphraser
   + templates until the ≥ 0.9 bars are met" recommendation, which I adopt.
3. **Two product facts** verified at HEAD by the executor and re-read by
   parcel-6c: the whisperer has **no class for a plan acceptance** (a
   `nav_goal` change produces nothing; `nav_state` → `nav_tick`, NEVER band)
   and **`KIND_REROUTE` is dead code** — so today's product voice cannot
   acknowledge a new goal or a mid-trip revision from receipts at all. Arm
   D's 50/75 acks on the scripted responder are arrivals' `critical_bypass`
   forwards standing in for acknowledgements. parcel-6c verified both at
   HEAD (`_diff` :1009 has no `nav_goal` branch; `KIND_REROUTE` :123/:322/
   :381/:2454 never constructed; the only other reroute is
   `SocialProgressStateV1.REROUTE`, unmapped) and adds the caveat that
   `KIND_REROUTE` is in `CRITICAL_KINDS` — its first constructor would
   bypass the spend ceiling, so its band is a decision, not a default.

## What it does NOT prove
Scripted receipts, no audio, one provider date; the hosted D arm is
unmeasured; the local row is a CPU upper bound; the matcher's raw counts
are not promotion metrics.
