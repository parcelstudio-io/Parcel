# AUDIT · T1 — NAV-INT-1 tier on the merged tree (W1's bar 2, W4's bars, the two-leg-oracle refinement) — verifier: Fable (parcel-0e), 17:1x 08-30

**Disposition: MEASUREMENT ACCEPTED; it exposed a W4-F4 defect (F-T1-1) → W4-F7 dispatched; T1 re-runs after F7 so the committed state's numbers are the tested state's.** Run on `~/.cache/parcel-0e/wb/gate` (HEAD + W1 + W2 + W3 + W4/F4/F5 + W6; before F6/F7): 10 controls + 10 sequence controls + 40 episodes, 0 errors, ≈ 68 min, $0, orphan check clean; recorded artifacts untouched; outputs `research/20260829/nav-interrupt-1/m1-merged-*` (five files). One build produced every number (the runner was SIGTERM'd by a session task timeout at episode 39/40, teardown trapped, the 11 build blobs re-hashed byte-identical before `--offset 39 --limit 1` resumed).

| # | row | bar | HEAD 08-29 | W1 alone | W4 alone | **merged (T1)** | |
|---|---|---|---|---|---|---|---|
| 1 | instruction admission | ≥ 0.9 | 0.750 | 0.969 | 0.750 | **31/32 = 0.969** | GREEN |
| 2 | amended success (both authorities) | ≥ 0.8 | 0.393 | 0.750 | 0.500 | **16/28 = 0.571** | **RED — below W1: F-T1-1** |
| 2b | scorer (K0) only | — | 14/28 | 24/28 | 14/28 | 21/28 | |
| 2d | by goal 2 | — | bench 0/7 | 0/7·9/9·3/3·5/5·4/4 | | **0/7 · come_here 9/9 · lamppost 1/3 · sidewalk 4/5 · towards_lamppost 2/4** | |
| 3 | path ratio vs straight-line oracle | ≤ 1.1 | 1.4905 | 1.7299 | 1.4875 | 1.7225 (n=5) | RED as written |
| 3b | hold-row quotient | ≤ 1.1 | 0.977 | 0.980 | 0.978 | **0.969** | GREEN |
| 3c | resume rows vs the two-leg oracle | ≤ 1.2 | — | 1.373 | 1.468 | **1.079 (n=3)** | GREEN |
| 4a/4b | owner-referring / cue-stripped | 6/6, 8/8 | 0/6 | 6/6, 8/8 | 0/6 | **6/6, 8/8** | GREEN |
| 5–8 | return; refused-and-continued; terminal false arrivals; switch-window false arrivals (live, revision-aware) | | 8/9; 7; 3; 0 | 13/13; 0; 0; 0 | | **5/5; 0; 0; 0** | GREEN |
| 9 | authority disagreements | ≤ 2/80 | 17/80 | 9/85 | **0/80** | **7/85 strict** (20/85 incl. tolerated) | **RED — F-T1-1** |
| 10 | bench `system_failed_but_arrived` | 0/29 | 11/29 | 0/29 | 0/28 | **0/29** | GREEN |
| 11 | collisions; min clearance | 0 | 0 | 0 | 0 | **0 / 0; 0.8233 m window, 0.6494 m whole** | GREEN |
| 12–13 | blind classifier; `gold_blind.json` | exact | 0.8273 | 0.8273 | 0.8273 | **0.8273; unchanged** | GREEN |

**F-T1-1 (diagnosed live):** F4's `LegIdentity.region_id` is frozen at the FIRST committed region, but perception's lock-on legitimately refines the instance mid-leg (`lamp_post_2` at 4.2 s → `lamp_post_1` at 19.8 s, same directive and generation); the terminal receipt — claimed, inside, support-ok, settled, `arrived_verified`, `committed_entity_id_raw == scored_entity_id`, K0 arrived on 23/24 — is refused as `arrival_receipt_for_another_place` on **24 legs**. The 16/28 → 21/28 gap is entirely this defect; with it removed bar 2 is exactly W1's 21/28, still RED with `bench 0/7` as the only shortfall — the pre-registered ceiling is confirmed, not beaten (B32 makes the scorer stop certifying unstandable ground: bench legs moved from `system_failed_but_arrived` to honest `agreement` at dtg 0.24). **→ W4-F7:** the leg's identity carries the COMMITMENT CHAIN of region ids the same generation committed; `is_for` accepts a receipt in the chain, refuses a place the leg never committed or another generation; eval runners keep a one-element chain (the answer key), so B-09 stays `wrong_instance`.
**Process finding:** W4's own F1 tier never ran F4 — its long-lived runner imported the modules at ≈ 07:53, F4 landed at 08:19; `arrival_receipt_for_another_place` appears 0× in W4's artifacts, 24× in T1's; F4's wiring tests set `region_id` themselves, so none exercises the snapshot timing. T1 is F4's first tier measurement — which is what the "tested state = committed state" rule is for.

**Post-F7 requirement (integrator):** re-score the 24 refused receipts and the 7/85 disagreements by name on the T1 re-run — expected 21/28 with the residual attributed (bench 0/7 = B32's honest strip); every tier row stamped with the patch sha it ran under.

## Re-run after W4-F7 — verifier, 19:2x — **MEASUREMENT ACCEPTED; every row stamped `bfc72ae269a2cce5…`**
Start stamp identical to dispatch; close stamp differs only by the run's own outputs + W5-F1's concurrent files (none imported by the tier); all 13 build/harness blobs byte-identical launch → close; one process, no SIGTERM, no resume; 10 + 10 + 40, 0 errors, 3736 s, orphan check clean.

| # | row | bar | HEAD 08-29 | W1 alone | T1 pre-F7 | **post-F7** | |
|---|---|---|---|---|---|---|---|
| 1 | admission | ≥ 0.9 | 0.750 | 0.969 | 0.969 | **31/32 = 0.969** | GREEN |
| 2 | amended success (both authorities) | ≥ 0.8 | 11/28 | 21/28 | 16/28 | **21/28 = 0.750** — bench 0/7 · come_here 9/9 · lamppost 3/3 · sidewalk 5/5 · towards_lamppost 4/4; scorer-only = system-only = 21/28 (the authorities agree leg for leg) | **RED — the pre-registered ceiling, confirmed exactly** |
| 3 | path ratio vs the straight-line oracle | ≤ 1.1 | 1.4905 | 1.7299 | 1.7225 (n=5) | 1.7303 (n=12) | RED as written |
| 3b | hold-row quotient | ≤ 1.1 | 0.977 | 0.980 | 0.969 | **0.981 (n=3)** | GREEN |
| 3c | resume rows vs the two-leg oracle | ≤ 1.2 | — | 1.373 | 1.079 (n=3, an artefact of F-T1-1 collapsing the population) | **mean 1.374 (n=8), median 1.061** | RED on the mean (two `towards_lamppost → sidewalk` outliers 2.30/2.30, outliers in W1's run too); GREEN on the median |
| 3d | two-leg, all rows | — | — | 1.088 | 0.841 | **1.089 (n=13)** | GREEN |
| 4a/4b | owner-referring / cue-stripped | 6/6, 8/8 | 0/6 | 6/6, 8/8 | 6/6, 8/8 | **6/6 · 8/8** | GREEN |
| 5–8 | return; refused-and-continued; terminal FA; switch-window FA | | 8/9; 7; 3; 0 | 13/13; 0; 0; 0 | 5/5; 0; 0; 0 | **13/13 · 0 · 0 · 0** | GREEN |
| 9 | authority disagreements | ≤ 2/80 | 17/80 | 9/85 | 7/85 | **0/85 strict AND 0/85 incl. tolerated** | GREEN |
| 10 | bench `system_failed_but_arrived` | 0/29 | 11/29 | 9/28 | 0/28 | **0/28** | GREEN |
| 11 | collisions; min clearance | 0 | 0 | 0 | 0 | **0 / 0; 0.8241 m window, 0.6590 m whole** | GREEN |
| 12–13 | blind classifier; `gold_blind.json` | exact | 0.8273 | 0.8273 | 0.8273 | **0.8273 (91/110); `c253df2f…`** | GREEN |

**Re-score by name:** the 24 receipts T1 refused → all 24 `navigation_goal_verified` (23 scored legs `sys=T scorer=T dtg 0.0 → agreement`; `ni1-30`'s hold leg unscored); token census 24 → 0 across 109 legs; `navigation_goal_verified` 27 → 52; no other refusal class grew; **`arrival_receipt_superseded`: 0 occurrences** — the U32 tightening removed 24 false refusals and added none. Disagreements: empty. Corrections to T1's diagnosis: the 7 strict were 6 × F-T1-1 + 1 × `semantic_arrival_verification_failed` (`ni1-29 … reissue`); and the anticipated bench residual is not a disagreement at all — all 28 bench legs are `agreement` (`sys=F scorer=F`), B32's honest strip, which is why bar 9 reads 0/85.
**Reading for the close:** the plan queue (W1) + arrival authority (W4) together deliver admission 0.969, zero authority disagreements, zero false arrivals of any kind, zero collisions, and amended success exactly at the pre-registered ceiling 21/28 — the remaining 7/28 are the bench legs the honest arrival contract refuses at dtg ≈ 0.24 (B32's standable strip), an owner E3 item, not a plan-queue or authority defect. "Resume adds no path overhead" holds on the hold rows (0.98), the median (1.06) and the all-rows two-leg ratio (1.09); the mean of the 8 resume rows (1.37) is carried by two outliers that pre-date this wave.
