# P1_STATUS — card P-1, plan revision r2

- **Card:** `SPIKE_AND_PLAN_CARDS.md` §"Card P-1 [sol] — plan revision r2"
- **Base:** commit `7242660`
- **Date:** 2026-08-12

OWNS, and the complete set of files touched:

- `../task_1/PRODUCTION_COMPANION_PLAN.md`
- `../task_1/RESEARCH_LEDGER.md`
- `../task_1/VALIDATION.md`
- `P1_STATUS.md` (this file)

Nothing under `src/`, `configs/`, `evals/`, `tests/`, `scripts/`, `backlog/`, or
`design_spike/` was modified. `FABLE_VERDICT.md` and `FABLE_REVIEW_BRIEF.md` were read
only. `backlog/BLOCKED.md` B5/B6 were read only; their numbers are quoted into the plan,
and the defects themselves stay owner-gated.

## 1. Traceability — every verdict item to a named hunk

Each row names the section the hunk lands in, so it can be found by heading rather than
by line number (line numbers moved as the file grew).

### `PRODUCTION_COMPANION_PLAN.md`

| # | Item | Section (hunk anchor) | What changed |
|---|---|---|---|
| 1 | RC-6 | front matter, `Parent baseline:` | r1's "current dirty worktree" replaced by commit `7242660`; new `Revision: r2` line naming the verdict items folded in; status line moved from "design candidate" to "Iteration 3 accepted, Wave 0 accepted to begin"; r1's file-overlap stop condition recorded as moot |
| 2 | RC-6 | §Honest baseline, `Test suite` row | `3,889` → `3,943` at `7242660`, with the r1 figure disclosed inline as an unrepeatable mid-batch transient and a pointer to `VALIDATION.md` |
| 3 | N-8 | §Honest baseline, `Dynamic-cost timing` row | "210/211 pass" withdrawn as **unreproducible** (no test selection recorded); only the 3.07–3.47 ms micro-gate measurement retained as evidence |
| 4 | RC-5 | §P0 defects, item 9 | "the 50 Hz control step" → "the 10 Hz `RobotRuntime` semantic loop (`loop_hz=10`, `frame_hz=10`) — the loop that dispatches motion"; states the 50 Hz `ControlManager` thread does no duplex logging; notes the defect and W0-G's aim are unchanged and only the budget arithmetic moves (100 ms period, not 20 ms) |
| 5 | N-7 | §Decision comparison, new subsection "Abandonment criteria for the hybrid architecture itself" | Answers brief Q12 for the architecture: four measured falsifiers (stop authority cannot be isolated; sole-writer exclusivity unenforceable on shipped firmware; the contract seam costs more than the rewrite it avoided; Python-preservation stops paying), each naming the wave that can produce its evidence |
| 6 | N-6 | §Timescales and process topology, load-shed paragraph | Reconciles the contradiction by separating *physical priority* (authority over motion) from *shed order* (product harm per resource freed); reorders so shadow/proposal-only models shed **second**, before TTS quality and conversation size, because shedding a non-authoritative component cannot change behavior; open-vocabulary grounding moves to last of the shed-able set; shedding past the list is a hold, not a degraded-autonomy mode |
| 7 | RC-2 | §`TerminalWitnessV2` (heading now marked `REVISED per RC-2`) | Adds the required localization-uncertainty reserve: `pose_uncertainty_reserve_m` with recorded derivation, a positive effective margin `region_margin_m − reserve` as a pass condition, the claim-tick pose-error estimate and its provenance, and an explicit statement that `HEALTHY` and covariance are inputs to the reserve and never substitutes. Quotes B5's measured episode (0.002–0.040 m stopping margin vs 0.007–0.239 m claim-tick MAP error; 3 of 7 TRUE-outside; covariance 3.6× optimistic). Adds a scope boundary: product arrival changes stay owner-gated by B5's 2×2; the nightly `pose-drift-arms:safety` red is not to be greened |
| 8 | RC-3 | §Speed from evidence, envelope block + new subsection "Directional and closing relevance are part of the envelope" | `clearance` → `clearance(theta)` in the envelope; new subsection gives the final-governor directional/closing semantics in five numbered rules (per-sector clearance against the candidate's swept footprint; a *derived* closing-rate floor replacing the `1e-9` float test; TTC rather than distance alone; lateral vs along-track clearance stated separately; monotonicity preserved — directional relevance may only decline to escalate, and missing/stale/ambiguous evidence falls back to the conservative scalar test). Cites B6 with its measured numbers (0.8 m stop radius, 87.7° off-axis, `cos(−1.53) = 0.041`, 63 zeroing brake calls, 40/42 cells, reachable flag-OFF). Scope boundary: `apply_collision_brake` is owner-gated by B6's 2×2 |
| 9 | N-7 | §Navigation candidates, new subsection "Abandonment criteria for the RPP/DWPP baseline" | Four falsifiers for retiring the deterministic baseline (structural infeasibility proven by two parameter sweeps, not tuning; a challenger winning on hard gates with zero regression on held-out data; loss of replay determinism; deadline economics inverting), plus the rule that a challenger winning on progress/SPL alone does not retire it and that retirement is a recorded decision |
| 10 | N-7, RC-2, RC-3, RC-4 | §Metrics and proposed promotion gates, preamble + all four bullet blocks | New preamble states that **every** numeric target is "proposed pending hazard/ODD derivation", concedes brief Q11 without qualification, and binds two consequences (no number may be cited as a safety argument; no target may be relaxed to pass a gate). Every bullet now carries an explicit `Proposed:` marker, including the `100%`/`zero`/`100/100` thresholds; the four latency gates that owe the RC-4 derivation are marked `⟂`. The follow-band ≥90% and SR→≥90% bullets are conditioned on B6, the "zero false-arrival credit" clause on B5, and the terminal-witness bullet now requires a positive effective margin after the RC-2 reserve |
| 11 | RC-6 | §Wave 0, new "Base pointer" paragraph | Every W0 card baselined on `7242660`; card re-runs must report the commit they ran at; the W0-owned file list is enumerated and the overlap stop condition recorded as moot; `runtime.py` restated as single-owner (W0-A) |
| 12 | RC-4 | §Card W0-C, new "Pre-freeze deliverable" block + new gate bullet | States the live TTL `command_timeout_s = 0.35 s` with all three verified locations; specifies the derivation table's required columns (proposed p99 gate; 50 Hz period and periods spanned; the 0.35 s TTL and its 17.5 periods; worst-case distance at the 0.3–0.5 m/s ceiling; whether the gate is dominated by the TTL; the derivation or measurement behind each number); names the specific tension to resolve (a 150 ms client-loss gate inside a 350 ms validity window means "stop initiated" ≠ "motion ended"); answers the retune question — **no, derive first, retune only from measurement** — with the reasoning (frozen rows, global rules 3 and 6) and makes an irreconcilable table a STOP-and-report; adds the pinned-table gate bullet |
| 13 | N-5 | §Card W0-F, new "Definition of the Fable gate" block | Defines it as a new hard `authority-invariants` tier in `scripts/ci_gate.py`: **what it gates** (ported provenance/epoch/NaN/latch/monotonicity/sole-writer invariants, the RC-4 pin, the RC-2 and RC-3 regressions, and the 20/20 mutation kill); **when it runs** (`commit` tier, with the mutation-kill sub-gate nightly with a freshness check, following the existing `mutation-panel-freshness` pattern); **what reddens it** (any ported invariant failing, kill count below 20/20, a new authority seam without a manifest entry, the pin disagreeing with live constants, manifest not reproducing) — red is STOP-and-report, never a waiver; and what it does not do (owns no product behavior, changes no success rule, and a green gate is a precondition for a Fable review, not a substitute) |
| 14 | RC-5 | §Card W0-G, new "Budget analysis uses the real loop" block + gate bullet | Restates the rate as the 10 Hz semantic loop, keeps the card's aim unchanged, and redefines the quantity to bound: how long a blocked/rotating write delays the *next dispatch*, measured against the 0.35 s `command_timeout_s` — i.e. whether a stalled logger lets the issued setpoint expire — rather than whether it misses a 20 ms tick; requires any 20 ms-derived figure to be recomputed at 100 ms |
| 15 | RC-2, RC-3 | §Wave 0 MUST NOT TOUCH | Adds the B5 product surface (K0 arrival predicate, K0 band, scorer epsilon, `calibrated_go2_reanchoring` arm) and the B6 product surface (`apply_collision_brake`, `safety.stop_distance_m`, the `CollisionPolicy` relevance gate) as owner-gated; closes with the rule that Wave 0 lands the RC-2/RC-3 contracts, fixtures and tests but not the product changes they imply |
| 16 | RC-3 | §Wave 2 exit | Exit gate explicitly conditioned on the B6 owner decision: the ≥90% band is unreachable while the brake stands, so it is **not armed as an exit condition** until the 2×2 lands and the frozen `collision=0` rows are re-proved; names the predictable failure mode (relaxing the band instead of fixing the brake); if the owner declines to change the brake, the target is re-derived rather than left standing |
| 17 | RC-2, RC-3 | §Wave 3 exit | Both halves conditioned: the ≥90% success target on B6 (`v4r` wall-line clutter fails on both arms), the "zero false terminals" half on B5 (honest rate 3/61, and a suite cannot certify zero false arrivals using the predicate that produces them); both measurable and reportable meanwhile, labelled with the open defect |
| 18 | RC-1d (verdict "CLAIMS THAT MUST BE DOWNGRADED") | §Basic design tests completed in this task | "seeded 200-case corruption campaign" → "a seeded campaign of **200 draws over 12 single-fault evidence-corruption classes**"; marks the `43 passed` figure as r1's, points to `S1_STATUS.md` for the post-hardening counts, and records the honest r1 result (12 of 20 invariant-killing mutants survived the 43-test suite) |
| 19 | RC-2, RC-3, RC-4, RC-1d, N-1, N-2, N-3 | §Required product tests, new items 24–28 | 24 `test_terminal_witness_requires_pose_uncertainty_reserve` on B5's episode (0.007 m margin vs 0.239 m error must not pass) with a required seeded-failure proof; 25 `test_collision_brake_relevance_is_bearing_and_closing_aware` on B6's geometry (0.8 m, 87.7°, closing fraction 0.041) plus the conservative-direction assertion; 26 the TTL/latency derivation pin; 27 20/20 mutants killed, each named by its killing test; 28 the verdict's missing-failure-case list folded in (prior-epoch lease, NaN/None/inf in every clock/timestamp/TTL field, latch persistence, the B5 and B6 fixtures, in-place search without fresh 360° evidence, the composed origin pipeline, zero-gate dominant verdict and CLAMP production) |

### `RESEARCH_LEDGER.md`

| # | Item | Section (hunk anchor) | What changed |
|---|---|---|---|
| 20 | RC-5, N-8 | header paragraph | New `Revision r2` note naming the three corrected rows and recording that no primary-source row changed (all 24 externally checked claims verified with zero mismatch) |
| 21 | RC-5 | §Local evidence reviewed, `duplex/coordinator.py` row | "The 50 Hz duplex step" → the 10 Hz `RobotRuntime` semantic loop, with the r1 wording preserved inline as the thing corrected; design-implication column now budgets against the 100 ms dispatch period and the 0.35 s TTL |
| 22 | N-8 | §Local evidence reviewed, `Focused navigation test run` row | "210/211 passed" withdrawn as unreproducible (no selection recorded, so neither numerator nor denominator regenerates); only the micro-gate measurement retained; adds the obligation that future focused runs record their exact `pytest` selection |
| 23 | N-8 | §Local evidence reviewed, `2026-08-12 desktop probe` row | "Whisper/Piper services answer health checks" corrected: **Piper is a subprocess, not a health-checked service**, so no liveness evidence exists for it; Whisper's reachability retained; adds that a subprocess failure surfaces at synthesis time and that W0-D's output preflight is what would give the TTS path a real readiness signal |

### `VALIDATION.md`

| # | Item | Section (hunk anchor) | What changed |
|---|---|---|---|
| 24 | RC-6 | whole file, rewritten as r2 | Baseline moved from "current dirty worktree" to commit `7242660`; new section explaining what r1 recorded and why it was re-run; the executed commit-gate output recorded verbatim with start/finish stamps; an r1↔r2 reconciliation table (3,889 → 3,943, skips/deselects/ruff unmoved, elapsed 149.8 → 190.8 s, PASS → PASS); the 3,889 transient disclosed as the required change rather than silently replaced; a disclosure that the run carried concurrent in-flight tranche-1 edits, so it is not a pristine-checkout measurement; `does_not_prove` preserved and extended with B5/B6 and the pristine-checkout caveat |
| 25 | RC-1d | §Design-contract spike | Marks the spike run **not executed** for r2 and explains the sequencing (S-1 is rewriting the spike concurrently); marks r1's `43 passed` stale by construction and redirects to `S1_STATUS.md`; corrects "seeded 200-corruption boundary campaign" to 200 draws over 12 single-fault classes |

## 2. Judgment calls, declared

1. **Rows 18 and 25 are RC-1d, whose card owner is S-1.** RC-1d's spike-side work is
   S-1's; but the same overstated claim ("200-case corruption campaign") is printed in
   two files S-1 may not touch and I own. The verdict lists it under CLAIMS THAT MUST BE
   DOWNGRADED, so leaving it standing in the plan and the validation record would leave
   a required change unlanded with nobody able to land it. I corrected the wording in my
   two files only and did not touch `design_spike/**`, including its README, which
   remains S-1's item 7.
2. **Row 10 marks targets rather than rewriting them.** N-7 says to mark every numeric
   target "proposed pending hazard/ODD derivation" where not already. I added a binding
   preamble plus a per-bullet `Proposed:` marker and did not change any number — moving
   a target is exactly what the hazard derivation is for.
3. **Rows 7, 8, 15, 16, 17 keep the product untouched.** RC-2 and RC-3 required contract
   and specification language; B5 and B6 remain owner-gated. Every one of those hunks
   states its scope boundary explicitly so the next executor cannot read the spec as
   authorization to change the brake or the arrival predicate.
4. **The RC-3 closing-rate floor is specified as a derivation, not a number.** B6 lists
   three candidate mechanisms for the owner's 2×2; picking one here would pre-empt the
   2×2, and inventing a replacement for `1e-9` would be a constant tuned to a gate
   (global rule 6). The plan states what the floor must be derived *from* instead.

## 3. Verification of the RC-4 constants — done independently

RC-4 requires the live TTL. Verified in-tree at `7242660`, not taken from the verdict:

- `src/parcel_robot/control/models.py:69` — `ControlTiming.command_timeout_s: float = 0.35`
  (the same dataclass carries `control_hz: float = 50.0`, `state_timeout_s: float = 0.25`)
- `configs/robot.yaml:116` — `command_timeout_s: 0.35` under `control:` (with
  `control_hz: 50`)
- `src/parcel_robot/control/factory.py:166` —
  `command_timeout_s=float(config.get("command_timeout_s", 0.35))`

All three agree at 0.35 s, so the plan states it as the live value without hedging. The
50 Hz control rate is likewise confirmed in both the dataclass default and the config.

## 4. Gate status

| Gate | Status |
|---|---|
| Every RC/N item traceable to a named hunk | **Met** — table in §1; RC-2, RC-3, RC-4, RC-5, RC-6, N-5, N-6, N-7, N-8 each have at least one row, plus the RC-1d claim downgrade |
| No content drift beyond the items | **Met** — 25 hunks, each carrying an item tag; no section without a verdict item was rewritten |
| VALIDATION re-run executed, not hand-edited | **Partly met** — `ci_gate --tier commit` executed fresh (PASS, 3943, 190.8 s, verbatim in `VALIDATION.md`). The spike run and `git diff --check` were not executed: the session's shell stopped starting processes after the gate run. See §5 |
| `git diff --check` clean | **Not verified** — see §5 |

## 5. What could not be done, and why

After the commit-gate run completed at `2026-08-13T01:02:15Z`, the shell stopped
starting processes entirely — every command, down to the builtin `true`, returned exit 1
with empty stdout and stderr, in both foreground and background modes. An independent
agent in a separate session was dispatched to run the same commands and reproduced the
identical failure, including with the sandbox disabled, which places the fault in the
tool/shell layer rather than in this workspace or these commands. That blocked three
things:

1. the design-spike pytest run, which this card deliberately sequenced last so it would
   land after S-1's edits;
2. `git diff --check -- scrum/20260812/task_1`;
3. a close-of-work `git status --porcelain` to pin the exact worktree inventory during
   the gate run (the disclosure in `VALIDATION.md` therefore uses the session-opening
   snapshot and states it as a lower bound).

Both `VALIDATION.md` and this file record these as unexecuted rather than carrying r1
figures forward. Nothing was written into a result block that was not actually observed.
The tranche audit should execute all three on a clean tree and replace the corresponding
lines. Note that the spike figure was going to be superseded by `S1_STATUS.md` in any
case, since S-1 is changing both the test count and the campaign's class count.

**Mitigation for the unverifiable `git diff --check`.** The check's default failure mode
is trailing whitespace on added lines, and these three files use two-space Markdown hard
breaks in their front matter — so copying that house style into new lines would have
produced exactly the violation I could no longer detect. The front matter of the plan
and of `VALIDATION.md` was therefore converted to bulleted lists, which need no trailing
spaces, and every other added line ends on a word or punctuation mark. No conflict
markers exist in any of the three files. This reduces the risk but does not discharge
the gate: the audit still has to run the check.

## 6. Handoff

- **W0-C dispatch brief is unblocked**: the RC-4 derivation obligation, its required
  table columns, the verified live constants, and the "derive first, do not retune"
  recommendation are all in §Card W0-C of the plan.
- **W0-F** now has a defined gate (§13) and should reconcile it with S-1's final mutant
  list before implementing.
- **Nothing new goes to `backlog/`** from this card. B5 and B6 were absorbed into the
  plan text as required; neither was modified, and no new product defect was found —
  this card executed no product code.
