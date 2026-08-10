# PERSONAL_CONVO_V1 text-tier result ledger

Immutable Tier-T results land here. Each is written once (`open("xb")`); never
edit a recorded result. A result carries its `pack_digest`, `case_verdicts`
(the determinism contract), `family_status`, and a mandatory `does_not_prove`.

| UTC | Run | Provider | Memory | Families pass | Recency-window blocked | Fail | Turns pass |
| --- | --- | --- | --- | --- | --- | ---: | ---: |
| 2026-08-09 | [`personal-convo-t-20260809-fixture-run01`](personal-convo-t-20260809-fixture-run01.json) | fixture-honest-companion-v1 | recency (baseline) | 7 (in_session_context, fact_tool_composition, persona_consistency, affect_handling, interactivity_clarification, adaptability_no_sycophancy, asr_robustness) | 1 (cross_session_memory) | 0 | 12/13 |
| 2026-08-09 | [`personal-convo-t-20260809-tiered-run02`](personal-convo-t-20260809-tiered-run02.json) | fixture-honest-companion-v1 | **tiered** | 8 (all families) | 0 | 0 | 13/13 |
| 2026-08-09 | [`personal-convo-t-20260809-live-summarizer-run03`](personal-convo-t-20260809-live-summarizer-run03.json) | live-llamacpp (gemma-4-26b-a4b) | **tiered + live summarizer** | 1 (asr_robustness) | 1 (adaptability_no_sycophancy) | 6 | 3/13 |

## Honest headline (run01, recency baseline)

Seven of eight probe families **pass deterministically** under the offline
reference companion. `cross_session_memory` is **recency_window_blocked**: the
frozen event graph pushes the "got the offer" evidence past `recent(8)`, so
today's `ConversationMemory` cannot surface it in a fresh later session. The
provider does not fabricate to compensate — it says it cannot recall — so every
truthfulness check still passes and the single failing check is fact recall.
That is a true finding that motivates the retrieval upgrade; it is recorded, not
tuned away. Reproducible any time with `--memory recency`.

## Flip (run02, tiered memory)

With the three-tier store wired (`--memory tiered`, now the default),
`cross_session_memory` **flips to PASS** — all eight families pass, 13/13 turns.
The aged-out "offer" fact is recalled from a **Tier-2 rolling summary**, not the
recency window: `evidence_within_recency_window` stays `False` (Tier 1 alone
still cannot surface it), so the flip is the tier mechanism, not a widened
window. **The frozen `pack_digest` is unchanged**
(`7e904d5335e049ac…`) — no locked file (scorers, fixture provider, probes, YAML)
was touched; only the runner's memory backend and this ledger changed.

Rows 01–02 were produced by the deterministic fixture provider, not a live model.
They executed no motion and no audio. Under the tiered backend the Tier-2
summarizer in run02 is a **deterministic fixture stand-in** (evidence-aware
compression), so run02 proves the retrieval *mechanism* — an aged fact survives
into a summary and is retrievable — not that a real LLM writes good summaries.

## Live summarizer quality (run03, PC-4 / M-A)

Provenanced `--provider live` on `gemma-4-26b-a4b` (`pack_digest`
`fc1af2f76f2b4914…` after PC-4 judge/calibration pins). PC-4 calibration
**qualified**. Live Tier-2 summary **contains `offer`**
(`summarizer_quality.contains_offer=true`; `durable_fact_coverage=0.25`;
`used_fallback=true` on at least one fold). Cross-session turn failed Tier-D on
**`word_budget` only** (reply recalled the offer from the live summary) — not a
fact-recall miss. Live companion Tier-D pass rate is low (3/13 turns); that is a
live-model quality finding, not a harness regression. Judge scores remain
report-only.
