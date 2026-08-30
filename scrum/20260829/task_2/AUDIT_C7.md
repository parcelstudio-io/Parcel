# AUDIT · C7 HARNESS-TRUTH-1 — verifier: Fable (parcel-0e), 2026-08-29 22:2x EDT

**Disposition: ACCEPT.** Research files only; no product code touched (verified: the product tree's dirty files are the owner's diff and the other executors' OWNS).

## Re-run / re-read by the verifier

| row | executor | verifier |
|---|---|---|
| LIT-1: arrival phrase on failed receipts | RED 10/10 → GREEN 0/10 (r101–r105) | each r10x JSONL contains the phrase exactly once — in `scripted_text` / `dropped_sentences` (the record of what was dropped), never in `text`; the spoken line at `voice_offer` reads "My task executive reports the task for the bench as failed (receipt: task_failed, detail: semantic_target_unreachable)… I have no camera… Do you want me to head back to the lamppost?" — **receipt-typed, confirmed** |
| LIT-1 receipt-kind sequence 5/5 byte-identical | claimed | not re-run (fake-tier sims; the artifacts carry the sequence) |
| `offer_for_terminal` exists and types by receipt | `sim_loop.py:874`, `dropped_sentences` `:907/:935` | confirmed |
| NAV-INT-1 `gold_blind.json` sha256 | `c253df2f…1fc1e5` unchanged | **`c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65`** — identical to my pre-registration pin |
| NAV-INT-1 cue-stripped re-issue admits | RED "I did not understand" 0 admitted → GREEN 1 admitted; 2/2 on one queue episode | not re-run (needs the tier's sims); the honest note that arrival did not reproduce across two reps is the right disposition (H-NI1b's number, not this card's bar) |
| NAV-GEN-1 rendering | 3 keys + 3 table sections added; old values unchanged | `covered_frac 0.4459`, `grounding_frac 0.535`, `best.gain_points 2.0` unchanged; new keys `frozen_block_summary_A0`, `run_provenance`; C3's `arm_config_facts` line untouched |
| ruff on the four folders | clean | **All checks passed** |
| sims torn down | `teardown_proof.clean = true` | no C7 sims alive; the live ones are C1's guarded pytest and C2's `c2nir` tier — theirs |

## Findings worth keeping
- NAV-GEN-1's prose host loads (3.06/2.97/2.72) were in no artifact — the real sweep-A start was 12.94/23.51/16.13; the worker count was never recorded (three different numbers in prose). Now rendered from artifacts, with `run_provenance` written by `run.py`. This is the "no number typed by hand" rule earning its keep.
- NAV-INT-1's `refused` metric only matched "couldn't admit", so the RED read `refused: false`; a `not_understood` flag was added without widening anything.
- Shared-file note for the integrator: `nav-gen-attribution-1/run.py` now carries C2's `run_unit` hunk and C7's provenance dict — non-overlapping; C2's "the ONLY change to this file" comment is stale and will be reconciled at close.

## Follow-up F1 (NAV-INT-1 harness scored a hardcoded sidewalk instance) — verifier, 01:0x

Verified: `harness.py` now carries `GoalSpec.region_with_provenance(committed=…)` with the stated same-label tie-break (`committed_instance` / `default_instance` / `default_instance_label_mismatch`) and per-leg `region_provenance`; `gold_blind.json` sha256 `c253df2f…` unchanged; ruff clean. Offline re-score of all 82 non-owner legs: `false_arrival` 6 → 0, `agreement` 63 → 69, `authority_disagreement` 13 → 13 (all six flips are sidewalk legs that committed `sidewalk_south`, DTG 4.98 m → 0.0). Live re-run of the six `sidewalk_south` legs on a pinned scratch export (own sockets, MemoryMax=12G, recorded artifacts never opened for writing): **6/6 agreement, DTG 0.0, rule `committed_instance`** — read from the RESULTS.md "Card C7-F1" table; the scratch jsonl holds the raw episodes (receipts, tracks), which I did not re-score myself. Two disclosures recorded (a `lamp_post_2` commit under a `lamp_post_1` hardcode — corrected, no rate moves; ≤ 0.001 m re-score rounding). **Consequence for C2's bar:** of NAV-INT-1's 16/80 authority disagreements, 6 were the harness; the remaining 10 are the bench legs now being attributed per leg by the C0/C2 follow-up.
