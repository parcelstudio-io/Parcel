# MB-2 — VERDICT (verifier: Fable / parcel-0e, 2026-08-29 20:5x EDT)

Executor: Opus (bounded, ≤ 1.5 h; 62 tool calls; $0.00, 0 hosted calls).
Design frozen 20:13; prompts frozen 20:21 (file mtimes); results 20:35.
Status: **VERIFIED — H-MB2a MET; H-MB2b fact gates MET (tautological by
construction), fallback gate MET, coverage on the point estimate only,
naturalness UNMEASURED (position-biased judge, §6); H-MB2c MET.**

## 1. What I checked myself

| check | how | result |
|---|---|---|
| Arm T reproduces | copied the folder to `~/.cache/parcel-0e/mb2/verify/` at mirrored depth (mb1.py resolves MB-1 by relative path), `run.py --arm T --seed 20260829 --no-judge` | grounding 1.0000, coverage 0.9688, claims/turn 1.444, invented 0, zero-claim turns 5, 180 turns, **bars dict identical** |
| The checker is MB-1's scorer, not a friendlier one | `contract.py:37-62` imports `ev, sc` via `mb1.py`; `contract.py:394` calls `sc.extract_claims`, `:401-415` `find_invented_actions` from the scorer "unchanged, on a turn built exactly as it scores"; licensing table `LICENSED_CLAIMS` `:284-298` maps acts → scorer claim classes | the extractor is shared; the checker ADDS act-licensing and inability/offer requirements on top of it |
| WHEN-to-speak is MB-1's | `arms.py:5-8, :38, :256-290` — trigger table + band ledger from `mb1.nr`, `max_updates_per_minute`/`min_gap_s` from the published bands, `IMMEDIATE_RECEIPT_S = 0.6` mirrored | the T arm changes only WHAT is said |
| Numbers in the report match results.json | dumped `arm_T`, `arm_T+P`, `arm_P-raw_shadow`, `checker`, `latency_contract`, `host_at_run` | all headline numbers match (fallback 32/180 = 0.1778; reasons 15/8/6/4/2/1/1; TTFT p50 152.83 / total p50 716.8 / p95 1094.1; load 52.04) |
| The keys-turn deletion is real | `transcripts/P-raw.jsonl` clean-01 turn 7: "I'm here at the bench. What would you like me to do next?" vs `T+P.jsonl` turn 7: "… I have no camera, so I can't look for things …" | confirmed; shadow arm b5 0/15, gated 15/15 |
| No hosted calls, server dead | `hosted_calls: 0`, `cost_usd: 0.0`; `ss -ltn` :8093 free; no llama-server process | confirmed |
| Foreign folders untouched | mtimes in `model-b-narration-1/` and the other folders precede 20:13 | confirmed |

## 2. Reading of the pre-registered criteria

**H-MB2a (templates) — MET on all five gates.** Coverage 0.9688 is capped by
the same inherited trigger-table decision that capped MB-1's scripted arm at
the identical 0.9688: the `running "the way is clear again"` receipt in the five
`blocked` scenarios is routed to the context band, so it is never spoken. This
is a *trigger-table* fact, not a contract fact — and it is the first time the
cap has been named as such.

**H-MB2b (template + local paraphrase, gated) — MET on 5/6.** Grounding 1.0
and invented 0 after the checker are **tautological** (the gate is built from
the scorer) and I do not credit them as evidence. The evidence rows are:
- **fallback 0.1778 (≤ 0.3)** — honest range 0.150–0.178: five of the 32
  rejections are the regex vocabulary being narrower than English (`shall we`,
  a leading "Okay," on a cancellation), reported by the executor against its
  own interest; I agree with that reading;
- **coverage 0.9113 [0.8613, 0.9575] (bar ≥ 0.90)** — the point estimate
  clears, the interval does not; the post-hoc sensitivity run shows the gap is
  matcher vocabulary ("I'm on the sidewalk now", "someone was blocking the
  way"), not lost content — so this is a *scorer* limit, and it also means
  MB-1's hosted coverage rows (0.228–0.288) are lower bounds;
- **the ungated shadow arm**: 6 invented gestures ("I'll go sit on the bench
  with you") and **15/15 capability refusals deleted** — with MB-1's grounding
  metric scoring those raw turns 1.0000. This is the probe's real finding:
  **grounding is blind to omission; a paraphraser's dominant failure is
  deleting the sentence the turn exists to say, and only a post-condition
  checker with required-statement rules catches it.**
- naturalness 23/40 = 0.575 [0.422, 0.715] < 0.6 — report-only, unresolved
  against both 0.5 and 0.6; the paraphrase is not shown to be preferred.

**H-MB2c — MET.** T render + full check p50 0.389 ms; paraphrase TTFT p50
153 ms / total p50 717 ms / p95 1.09 s on CPU at load 52 (the foreign 26B
server on :8080 shared the host; the vendored llama.cpp has no CUDA backend).
On the Orin these numbers do not transfer; what transfers is that the contract
itself is free and the paraphrase is a sub-second, interruptible add-on.

## 3. What it establishes for the research question

1. A receipt-typed speech-act contract (9 acts, slots, one template each)
   passes every fact gate MB-1's hosted model failed (grounding 0.61–0.73,
   45 flags), at 0.4 ms and no network — **the facts belong in the contract,
   not in the voice**.
2. A local 7B paraphraser makes the contract sound less templated at ~0.7 s,
   but *must* sit behind a checker that enforces required statements (the
   inability sentence, the goal name, the offer) and the invented-action
   matcher, or it silently drops the refusal 100 % of the time.
3. The 0.6 naturalness bar was not met; the paraphrase is a nice-to-have,
   not a demonstrated win. Ship T first.
4. The matcher vocabulary (offer regex, cancellation acceptance, coverage
   phrasings) is now the limiting instrument; widening it (and re-scoring
   MB-1's hosted arm with the wider one) is the next instrument step.

## 4. Not proven / caveats carried

- Harness-only: nothing is wired to `TaskExecutive`; no `SpeechAct` on the
  runtime; no flag. Promotion = a leaf module behind a default-OFF flag.
- Corpus authored by MB-1's executor; templates authored by this executor
  against the same scorer. Coverage of "the receipt shapes MB-1 imagined".
- Single model, single seed, one paraphrase per turn, 40 scenarios.
- The blind-flag audit's 6/6 `FALSE_POSITIVE` from the frozen judge is
  reported and not believed (sitting is a gesture by the judge's own prompt).
- `lexical_flags_triage_only` being empty for T is a wording coincidence with
  QEV-1's arrival regex (`we're here` vs `I'm at {goal}`), not a safety result.

## 5. Independent line-level lens (parcel-6c, read-only, 20:5x)

parcel-6c's note (`~/.cache/parcel-verify/mb2-lens/NOTE.md`) confirms both
questions I asked, by module reference rather than by reading:
- **Checker = scorer, unchanged.** `mb1.py:12-27` puts MB-1 on `sys.path` and
  `import scorer as sc`; `contract.py:36` binds the same module object; the
  checker (`contract.py:362-415`) calls `sc.normalise` (:379),
  `sc.extract_claims` (:394), builds an `sc.Turn` (:402-410) and calls
  `sc.score_turn` (:411); ONE registry (`run.py:534 sc.default_registry()`)
  feeds both the walk and the scoring pass. The checker is strictly stronger,
  never friendlier — so the gated arm's 0 invented is tautological by
  construction, and the honest rows are the fallback rate, the reasons and the
  P-raw shadow (as §2 reads them).
- **T rides MB-1's trigger table.** `arms.py` instantiates
  `nr.PlanQueueWhisperer` (`narrate.py:302`) over `TRIGGER_TABLE`
  (`narrate.py:118`) with the published bands {2, 15.0}; robot turns are
  emitted only on `pq.decide`; T, T+P and P-raw come from ONE walk.
- **Action taken on their recommendation:** MB-1's `scorer.py`/`narrate.py`
  are untracked (the whole 20260829 tree is; commit is the owner's) and
  `results.json` pins only `scorer_id = "mb1-scorer-v1"`. The sha256 pins of
  the four MB-1 modules and MB-2's own code/prompts are now in
  `mb1_pins.sha256` and below, so "same matcher" stays verifiable after commit:

```
4b1c16624b5d93e98fdf5502ea0016f8186c50f9d02e79963f7d41b3078b7c21  events.py
4aae890099772a38eb983f39aeb238f48144f971911175b3be1d67719414f70c  narrate.py
e5044a900bdb8ebb2aac2b41c6232294537c5d062e0681ef438d406b9749bab5  scorer.py
d760d7df2814232f5fc60745cdf6887b8428efab607ff5af215c274731a3abf2  steer.py
941ad54ba105664400aad5f44571364d474aaa19cc3ca8ad9762bff155ca5d23  contract.py
440d236d5a7a7570f181d7390172c4987d73321ddd4ac009cc4455a9542d5b01  arms.py
99d78a0852ac8d7f841d4157c397342a529a6a05f88f2fd1ca44ce51040e273f  mb1.py
c6aab378394eaf0b7836fe3308d0e1441a12e1f7f1ed0590bb7e84603853e7cc  run.py
c2956244963b71aa4f79b5c0e0992d2c08a01bc9b28b81a5938c0dbc02ef97e0  prompts/naturalness_judge_v1.txt
f62cda64c2a49a73e97af0c53a28d5e26b4d4b9d3ad5f57d2cb92f9291cb4feb  prompts/paraphrase_v1.txt
```

## 6. Adversarial panel (6 refuters + 1 critic, read-only, 21:0x)

Six claims sent to independent skeptics with the instruction to refute:
**none refuted** (confidence 0.85–0.97), each with a live re-score or
regenerated decision trace rather than a reading. What the panel adds to
§1–§5, and what I change because of it:

1. **The naturalness number is position noise, not a preference.** The judge
   picked the first-shown option 30/40 times (p = 0.002); T+P's win rate is
   0.84 when shown first and 0.33 when shown second; the position-balanced mean
   is 0.588. `run.py:385` draws one order per pair (no swapped re-judging),
   and the judge is the paraphraser model itself. → I downgrade the
   naturalness row from "not met" to **UNMEASURED**: the instrument cannot
   resolve 0.5 from 0.6 and is position-biased. Any future preference test
   needs both orders per pair and a different judge (or humans).
2. **Provenance wrinkle, disclosed:** `run.py`/`arms.py`/`mb1.py`/`sensitivity.py`
   carry mtime 20:35:48, later than `results/TP.json` (20:35:09); an arm-T-only
   re-run at 20:35:48 refreshed `arm_T`/`host_at_start` in `results.json`
   (its T latency row 0.119 / 0.236 ms supersedes the RESULTS.md §1 figure
   0.081 / 0.161 ms; no bar affected), and the llama-server log under
   `~/.cache/parcel-0e/mb2/` was overwritten by a 2-scenario smoke run, so
   **no server log of the 180-turn run survives**. My scratch reproduction of
   arm T with the 20:35:48 code matches `arm_T` exactly, so the code that
   exists produced the T rows; for T+P the panel re-scored the persisted
   transcripts with MB-1's scorer and got the published grounding, keys-bar
   and invented counts (0 / 0 / 6). I accept T+P as *scored-as-published*,
   not as *re-run*.
3. **The checker is stronger than the pre-registered wording** (DESIGN §
   "must pass the post-condition checker … else fall back": claim-mapping
   only). `contract.py:419-446` adds slot fidelity, required statements
   (inability, offer, goal), unlicensed numbers and a word cap — all
   pre-run, all declared, but unregistered; and one rule (the
   `position_report` inability post-condition) was added after the template
   failed its own self-check. The fallback rate is therefore the rate of a
   checker designed in the same session as the templates. The critic's
   fair reading: **the fallback rate is real but instrument-specific; 0.150
   is its floor under the pre-registered rule alone would be lower still.**
4. Acts beyond DESIGN's nine (`ask_clarify`, the closing question; four
   two-sentence renders via boolean slots) — declared in RESULTS §0, minor.
5. "T ≤ 5 ms" is met by a wide margin either way: the 0.389 ms figure is
   render + two checker passes inside the T+P arm; T-only is 0.119 ms p50.
6. `mb1.py:32-33` says the band values are read from `realtime.yaml`; they
   are hard-coded (`{2, 15.0}`) and happen to match the published values.
   Cosmetic; recorded.
7. The keys-turn finding stands with two panel caveats I adopt: the 15 raw
   turns make no false statement (13 carry a supported arrival claim, 2 carry
   none) — they are *incomplete*, which is exactly the class grounding cannot
   see; and 15/15 is one run at one seed with near-identical outputs, so it
   is a demonstrated failure mode, not a measured rate.

**Status after the panel:** H-MB2a MET (T rows reproduced); H-MB2b — fact
gates tautological by construction, fallback 0.178 (≤ 0.3) MET on a stronger-
than-registered checker, coverage 0.911 met on the point estimate only,
naturalness UNMEASURED (position-biased judge); H-MB2c MET. The finding I
carry into the wave verdict is unchanged: **the facts belong in a receipt-
typed contract; a paraphraser deletes required sentences and must sit behind
a required-statement checker; no preference for the paraphrase was shown.**
