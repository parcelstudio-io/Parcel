# Arbitration — cross-review round, 2026-08-06 (Fable)

Inputs: [OPUS_STATUS.md](OPUS_STATUS.md), [SOL_N11_STATUS.md](SOL_N11_STATUS.md),
[REVIEW_OPUS_ON_SOL_N11.md](REVIEW_OPUS_ON_SOL_N11.md) (REQUEST CHANGES),
[REVIEW_SOL_ON_OPUS_20260806.md](REVIEW_SOL_ON_OPUS_20260806.md)
(REQUEST CHANGES), plus arbiter ground-truth inspection of the tree.

## Ruling on the unattributed N11 wiring

A third hand wired N11 mid-review (pipeline.py `_update_ramp_memory` /
`_ramp_now_s` / approach ranking; extensions to `traffic_aware.py` 313→432
and its tests 40→45). Arbiter inspection: the wiring **improved** on the
SOL_N11 recipe in two of Opus's three seam blockers (Opus-B2: `_ramp_now_s`
has a finite-stamp check + tick-counter fallback, no TypeError path;
Opus-B3: the person-stop check reads `cnote` before shield concatenation),
but kept the navigator-side seed Opus measured as ~96% shaper-masked
(Opus-B1 stands), left the align-tick wipe live (Opus-S2 stands), and
reintroduced the frozen-bundle hard-import defect (Sol-B2 — the default
gate is red on `test_barn_v8_policy_bundle`). **Ruling: the wiring is
accepted as the N11 baseline and inherits the review findings as its fix
list. Ownership: Opus (it is existing-file wiring). The extensions to
Sol's files pass 45/45 but are unclaimed: Sol reconciles them (claim or
fix) — unreviewed code may not stay unowned.**

## Binding — Opus lane (existing files)

| ID | Ruling |
|---|---|
| OB-1 | Default gate red: extend the card-4 soft-import pattern to `traffic_aware` in the v8-replacement `pipeline.py` import (same REPO_ROOT fallback as `paths`); do not widen V8_ADDITIONS. Gate green at end of round. |
| OB-2 | Sol-B1 sustained: `relation ∈ {follow, behind}` is accepted post-decode from a model-facing validator while schema `const` is doctrine-level a hint. Key the accepted relation set off the registry via the existing two-validator split (runtime.py:530/534) so a loose-decode provider cannot author `relation="follow"`. The "like reacquire" analogy is rejected — reacquire is transitively blocked via registry exclusion; follow is not. |
| OB-3 | Opus-B1 sustained: move the yield-advance seed to the runtime S-curve shaper (it already supports seeding), single-writer — drop or sim-gate the navigator `seed_ramp` path. Measured +6.4% via navigator seeding does not meet the card's purpose. |
| OB-4 | Opus-S2 sustained (wiring side): do not `note_running` on align/zero ticks — record only when `cmd.vx` > 0.05. (Sol adds the API-level floor too; both sides intentional defense in depth.) |
| OB-5 | Sol-S4 sustained: unify resume-intent mode default (`runtime.py:2070` "behind" vs channel "direct") to `"direct"`. |
| OB-6 | Sol-S1/S2 sustained: correct U31 (honest upper bound **4/25**, not 8/25 — only the 3 stopped `arrived_verified` traces plus the one already-passing row are hold-fixable; the 4 `circle_owner spatial_step_limit` rows are not); add the non-invalidating option (paired re-scoring of persisted traces under same `runner_version`, new derived rows, frozen rows untouched); file the `nav-object_goal-D-15` dtg 3.1995 m verification-vs-K0-authority disagreement as its own register entry (claim-without-predicate class). |
| OB-7 | Surviving `sketch_come`→`behind` defect: fix minimally — `come` is an approach, not a formation; compile it to the non-behind relation with no heading precondition (same ruling as "follow me"). |
| OB-8 | Sol-S3 sustained: reword the "reverted dishonest repair" claim in OPUS_STATUS to what git evidence supports (uncommitted; unverifiable); keep the verified part (current pins test real behavior). Soften the duplex "can never again be edited" phrasing (run_duplex_v1.py:343 still hard-pins). |
| OB-9 | End-of-round verification: full default suite green; ruff clean on touched files; then run `pytest -m slow tests/test_voice_nav_e2e.py`. If the traffic case now passes, flip the xfail to a hard gate; if not, update the xfail reason with the measured post-wiring delta — no silent xfail. |

## Binding — Sol lane (Sol-owned files only: traffic_aware.py, its tests, status doc)

| ID | Ruling |
|---|---|
| SB-1 | Opus-S1 sustained: cost tunneling (exactly 0.0 at ≥10 m/s) — adaptive substep bounded by `influence_m / (2·|v|)` so no track can step across the influence band; pin with 10 and 15 m/s tests. |
| SB-2 | Opus-S3 sustained: cap total samples (floor on effective `step_s`). |
| SB-3 | Opus-S7 sustained: every public entry raises ValueError as documented (repo style), not TypeError. |
| SB-4 | Opus-S2 (API side): `note_running` ignores vx below a documented floor (default 0.05) so an align tick cannot wipe held state even if a future wirer forgets OB-4. |
| SB-5 | Opus-S4/S5 sustained: add `top_k` to `rank_approach_candidates`; optional `max_age_s` staleness filter for tracks (CV-extrapolating stale tracks is confidently wrong). |
| SB-6 | Reconcile the unclaimed 313→432 extensions + 45-test state: review line-by-line, claim what is correct, fix what is not, and record the reconciliation in SOL_N11_STATUS (ownership may not stay ambiguous). |
| SB-7 | Opus-S6 sustained: correct the status-doc citations (pipeline line drift; `relations.py` is `instructnav/`). Fix the `release()` "full reset" docstring and note the `step_s`/parked-cost coupling. |

## Rulings on contested items

- **`proxemic_approach.py`: PARK** (Opus's recommendation adopted). Do not
  wire (two disagreeing proxemic authorities = defect class D5), do not
  delete (its TTC term and `reject_cost` shape are the right ingredients
  for a later fail-closed veto on the ranked winner). Recorded as a named
  future card in backlog NEXT.
- **Byte-identity guarantee: verified sound** by adversarial float testing
  (Opus) — claim stands as written; no action.
- **U31 deferral itself: correct** (frozen-baseline invalidation is a K0
  decision) — only its options analysis and bound were wrong (OB-6).
- **Both AP­PROVE-with-changes verdicts stand**; neither lane's accepted
  work is reopened beyond the items above.
