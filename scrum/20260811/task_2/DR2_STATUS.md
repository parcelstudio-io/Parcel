# DR-2 — the standing degraded-pose arm — STATUS

Card: `scrum/20260811/task_2/SLAM_M_PLAN.md` Wave 2, DR-2. Executor: Opus 5.
Base: `dd2e857` + the audited uncommitted batch (AUDIT_WAVE1_FABLE: PASS 3778/0).
**Not committed.** Consumes DR-1's by-name contract (DR1_STATUS §6) unchanged.

> ## ⛔ STOP-AND-REPORT — the hard invariant is RED, and the finding is real
>
> Stage A measured **`false_arrival = 1` on `calibrated_go2_reanchoring`**, the
> one arm whose MAP frame actually drifts. It is reproduced, mechanised and
> quantified in §5. In one sentence: **0.24 m of MAP error let the navigator
> verify arrival 0.15 m outside the K0 band, and the pose's own reported
> uncertainty (0.066 m) understated its realised error by 3.6x, so a
> covariance-gated arrival check would not have caught it either.**
>
> **§5b (added after Fable's Wave-2 audit, independently re-derived here) makes
> it worse and structural.** Across all seven `arrived_verified` episodes of that
> arm the controller stops a median of **0.026 m** inside a 2.5 m band while its
> MAP error runs a median of **0.068 m**: **6/7** arrivals had a true margin
> smaller than their own pose error, **3/7** stopped outside the band, and two of
> those three were absorbed as `tolerated_boundary` because they fell inside
> `ARRIVAL_BOUNDARY_EPSILON_M = 0.05`. **The honest rate is 3/61, not 1/61**, and
> it is set by the drift tier, not by unlucky geometry.
>
> Per the card this is a finding, not a tuning target. Nothing was widened,
> nothing was excluded, the scorer epsilon was not touched, and the arm stays
> red. The fix is a design decision about how much margin the arrival predicate
> must reserve for the pose it is reading — §9 hands it off.

## 1. What was already written, and what this session did

A prior session wrote the injection, the substrate and the two-stage driver and
was interrupted before measuring anything. This session **verified** that code
against the card, **fixed three real defects** in it (§2), then **measured**
(§4), **pinned** (§6) and **gated** (§7) it, and wrote the 88-case commit-tier
test module the whole thing was missing. Fable's Wave-2 audit then returned
CONFIRMED-pending-four-minor-fixes; all four are folded in and marked **[audit]**
below, and the audit's strengthened form of the §5 finding is §5b.

## 2. Verification of the pre-written implementation — and the three defects

| Card requirement | Verdict | Evidence |
|---|---|---|
| Injection via `HeadlessCityQualityHarness(pose_profile=…)` + `new_pose_provider()` | **as specified** | `runner.py:593-601`, `:666-680` |
| No `ALLOWED_NAVIGATOR_OVERRIDES` change | **honoured by DR-2** | the set *did* grow in this batch (+`person_aware_nav`, +`lock_on_verify_on_approach`) — that hunk is cards D15-B / VS-4's, landed before this session; attribution in §8 |
| No `headless_city.py` edit | **honoured** | absent from `git status` entirely; the seam is reached by a *subclass*, `_DriftSeededHarness` |
| No pin moves / frozen digests unmoved | **honoured** | ci_gate `frozen-digest-sentinels` + `frozen-digest-integrity` green (§7) |
| ONE fresh provider per episode | **as specified** | `_new_pose_provider()` is called once per episode inside `_run_navigation`, after the parser accepts and before tick 0 |
| Per-episode seed VARIED (DR-1's binding warning) | **as specified** | `episode_pose_seed = profile_seed XOR sha256(episode_id)[:4]`; measured **61 distinct seeds on all 6 drift arms** (§4) |
| Band sized off the tail, not the mean | **as specified, re-measured** | §3 |
| Re-anchor metric scoped to the re-anchoring profile | **as specified** | `non_vacuity()` asserts `> 0` only for `*_reanchoring`; measured 518 there and **0 on every other arm** (§4) |
| `--freeze` refuses a non-None profile | **as specified** | `run_nav_instruct_v1.py:220`; pinned by a test that asserts exit code 2 and the message |

### Defect 1 (substrate, load-bearing) — the referent was NOT unique in perception

`drift_cells._removed_entity_ids` built its removal set from the **landmark
table it was handed**. That table is a *slice*: `landmarks_for(v4s)` returns
`derived_landmark_table(ids=V4S_LANDMARK_IDS)` = the v2 ids plus the buildings,
and **`planter_2` is not in it** — while `HeadlessCityWorld` builds its
perception specs from the scene artifact's full `derived` section, which does
contain it. So a second planter stayed standing in perception and **every
`go next to the planter` cell resolved `semantic_target_ambiguous` on tick 1**
(measured: trace length 1, zero metres travelled). `planter_1` is the substrate's
largest target at 18 of 61 cells.

Fixed by reading the removal set from `load_artifact()["derived"]` — the table
the world itself builds from — which is the only table that can make the
module's own "unique in perception" claim true. Pinned by
`test_the_referent_is_unique_in_the_scene_s_own_perception_table`, which
asserts set equality against the artifact rather than against a transcription.
Episode ids are unaffected (`_episode_id` hashes set/seed/target/start, not the
removal list), so the substrate is the same 61 cells.

### Defect 2 (provenance) — a measurement claim that does not reproduce

`DRIFT_MAX_STEPS`'s comment claimed *"raising it to 800 and to 1200 changed
neither SR nor mean distance travelled on a 14-cell probe"*. Re-measured on the
**full 61-cell substrate** under the truth control: base 200 → SR 0.1639, mean
path 5.84 m; base 800 → SR 0.1967, mean path 6.55 m. Both moved. The comment now
carries those two numbers, the reason the base stays at 200 (raising it makes a
FLAT budget bind on every cell — the "fixed" policy the budget-honest card
replaced), and the explicit note that re-picking a constant after seeing which
value scores better is the tuning move rule 6 forbids.

### Defect 3 (persistence) — the report header dropped the arm name

`run_nav_instruct_v1.py` wrote the report to disk **before** stamping
`report["pose_drift_profile"]`, and only re-wrote it on the
`--refreeze-provenance` path. Every episode row named its arm; the report header
did not. Measured on a live probe report, then fixed by writing the report once,
after every conditional stamp. Pinned by
`test_the_persisted_report_header_names_the_arm`, which runs the real CLI into a
tmp ledger and asserts header, episode row and ledger row all name the arm.

## 3. The band, and why it is not the mean

DR1_STATUS §6's warning is binding: single-episode divergence is not the band.
The reference distribution is therefore **re-measured here, not transcribed** —
`_sweep()` in the test module reruns DR-1's instrument (straight 11.9 m at the
1 m/s cruise, seeds 0–59) and pins `DIVERGENCE_REFERENCE_PCT` against it.

| profile | mean | median | p90 (index / interp) | min | max | DR1 §6 published (mean/median/p90/max) |
|---|---|---|---|---|---|---|
| `calibrated_go2` | 3.422 | 2.891 | 6.396 / 6.384 | **0.207** | **11.444** | 3.42 / 2.89 / 6.38 / 11.44 |
| `go2_aggressive` | 6.825 | 5.759 | 12.822 / 12.755 | **0.416** | **22.725** | 6.83 / 5.76 / 12.75 / 22.73 |
| `go2_degraded` | 14.207 | 12.425 | 29.812 / 28.409 | **0.421** | **46.955** | 14.21 / 12.43 / 28.25 / 46.95 |

**[audit fix 2] Which columns reproduce, precisely.** Mean, median, **min** and
**max** reproduce DR-1's published table to the last published digit. The **p90
does not**, under either estimator — and the code comment used to claim it did.
The first two profiles agree to a rounding; `go2_degraded` is off by 1.4–1.6
points, which is an estimator difference in the tail of a 60-sample
distribution, not a difference in the underlying draw (the max agrees exactly,
and the max is the harder number to match by luck). It has **no behavioural
consequence**: only `min` and `max` feed the band, and both reproduce; the p90
is used in exactly one test, where it is re-measured locally and never compared
to a transcribed figure. `runner.py`'s comment now says all of this.

`*_lost` and `*_reanchoring` reuse their base's row because their noise block is
their base's verbatim (DR1_STATUS §2 pins the equality) and `odom_error_m` is
unaffected by MAP correction — verified against `pose.yaml` and `pose.py:617`.

The pinned band is `(min x 0.5, max x 2.0)` of that envelope, i.e. for
`calibrated_go2` `(0.105 %, 22.88 %)`. That is **wider than a p90-sized band**,
which is the safe direction the DR-1 warning points: a mean-sized ceiling reds on
the profile's own p90 and on its own shipped seed. Pinned by
`test_the_band_clears_the_tail_that_a_mean_sized_band_would_red_on`, which
asserts p90 > mean and that both the p90 and the 60-seed max sit inside the band.

What the band therefore claims, per episode, is falsifiable but modest: *this
episode's divergence lies inside the envelope this profile's own 60-seed sweep
produced* — so a row cannot have been measured with the injector off (below the
floor) or with a runaway integrator (above the ceiling). It deliberately does
**not** separate the tiers per episode; DR1_STATUS §6 proves that is impossible.
Tier separation is asserted at the **arm mean** instead (`ladder_monotone`), and
that is exactly the statistic the per-episode seed variation makes meaningful.

**[audit fix 1] How completely the bands overlap, measured on the Stage-A rows.**
The code comment used to claim an in-band row "cannot have been measured with a
different tier (either way)". That is quantifiably false: **33/33** in-band
`calibrated_go2` episodes also satisfy `go2_degraded`'s band, and **17/22**
`go2_degraded` episodes also satisfy `calibrated_go2`'s (re-derived here from
`drift-arms-stage-a-20260812T061640Z.json`, matching the audit). It is
structural — each band is its own profile's full 60-seed envelope widened
(0.5x, 2.0x), and the envelopes nest. `runner.py`'s comment now says the band
proves the injection ran and drifted plausibly, and points at `ladder_monotone`
as the thing that catches a tier mix-up.

The cross-lane trap is pinned as its own cell:
`test_the_fixed_shipped_seed_is_the_trap_dr1_measured` re-measures the shipped
seed 20260807 against the 60-seed mean on `go2_degraded` and asserts the fixed
draw sits above 1.5x the mean — the 25.8-vs-14.2 finding, re-derived rather than
quoted.

## 4. Substrate provenance and the Stage-A table

### The substrate (`evals/nav_instruct/drift_cells.py`, set `v4d`)

Additive, candidate-only, **not** a member of `EPISODE_SETS` — registering it as
an episode-set *version* is precisely what would let `--freeze` and the
frozen-baseline ledger flag reach it. Built entirely from v4s's geometry
primitives and the live K0 goal builders, reusing `V4S_TARGETS` verbatim, so it
adds **zero** new natural-language surface and **zero** new arrival semantics.

Admission (all three, from a free `_v4s_start_lattice` point): target inside the
frustum range with the start yaw facing it (`visible_from_start` True, so the
cell measures TRAVEL, not search); straight corridor crossing no building disc
and not the owner keep-out ring; and a grid route into the scored `GoalRegion` of
at least `DRIFT_MIN_ROUTE_M = 10.0` m.

`DRIFT_MIN_ROUTE_M` is **derived, not chosen**: DR1_STATUS §2's `*_lost` window
is `(start 4.0 s, duration 3.0 s)`, derived there against a ~12 s episode so the
window has healthy operation before *and* after it, with the stated constraint
that a substrate "materially shorter than ~10 s of travel" needs a DR-1 handoff.
10 m at the harness's 0.85 m/s cruise is ~11.8 s of pure travel. **Measured
outcome: 1830 LOST ticks over 61 episodes on each `*_lost` arm = exactly 30 per
episode, and 61/61 recovered** — the derived window fits the substrate, so no
DR-1 handoff is needed.

61 cells, digest `a88a54ec107a0985aca8b1b75af68915bb4d0cd142004a87661c72698be46337`,
generation deterministic (a pure function of the artifact; no sampling):

| target | family | cells | route m (min/mean/max) |
|---|---|---|---|
| `tree_1` | object_goal | 17 | |
| `planter_1` | object_relative | 18 | |
| `bench_1` | object_relative | 10 | overall **10.00 / 11.14 / 13.50** |
| `lamp_post_1` | object_goal | 9 | |
| `tree_2` | object_goal | 7 | |
| `lamp_post_2` | object_goal | **0** — admits no cell under rule 1 | |

### Stage A — 7 arms x 61 cells, candidate mode, `scaled-path-v1`, base 200

Artifact: `evals/nav_instruct/results/drift-arms-stage-a-20260812T061640Z.json`
(generated `20260812T061640Z`, runner `nav-instruct-v1.1-k0-arrival`, 1586 s of
simulation). **This table was written here before any floor was pinned.**

| profile | SR | collisions | false_arrival | path m (total/mean) | divergence % (mean/min/max) | in band | LOST (held/recovered) | re-anchors |
|---|---|---|---|---|---|---|---|---|
| `truth (control)` | 0.1639 | 0 | 0 | 356.0 / 5.84 | — | — | — | — |
| `calibrated_go2` | 0.1475 | 0 | 0 | 384.5 / 6.30 | 2.65 / 0.22 / 6.54 | 33/33 | 0/0 | 0 |
| `go2_aggressive` | 0.0984 | 0 | 0 | 350.0 / 5.74 | 5.00 / 0.48 / 12.79 | 26/26 | 0/0 | 0 |
| `go2_degraded` | 0.0492 | 0 | 0 | 319.8 / 5.24 | 14.13 / 3.24 / 26.61 | 22/22 | 0/0 | 0 |
| `calibrated_go2_lost` | 0.1148 | 0 | 0 | 359.1 / 5.89 | 2.24 / 0.23 / 6.38 | 31/31 | 61/61 | 0 |
| `go2_degraded_lost` | 0.0492 | 0 | 0 | 329.9 / 5.41 | 13.56 / 3.26 / 34.38 | 26/26 | 61/61 | 0 |
| `calibrated_go2_reanchoring` | 0.0656 | 0 | **1** | 437.3 / 7.17 | 2.46 / 0.32 / 6.60 | 43/43 | 0/0 | 518 |

Supporting per-arm evidence from the same artifact:

| profile | distinct seeds | mean divergence m | mean distance m | slip events | LOST ticks | re-anchor events |
|---|---|---|---|---|---|---|
| `calibrated_go2` | **61/61** | 0.158 | 6.303 | 0 | 0 | 0 |
| `go2_aggressive` | **61/61** | 0.266 | 5.737 | 0 | 0 | 0 |
| `go2_degraded` | **61/61** | 0.639 | 5.243 | **9** | 0 | 0 |
| `calibrated_go2_lost` | **61/61** | 0.131 | 5.887 | 0 | **1830** | 0 |
| `go2_degraded_lost` | **61/61** | 0.645 | 5.408 | **10** | **1830** | 0 |
| `calibrated_go2_reanchoring` | **61/61** | 0.176 | 7.168 | 0 | 0 | **518** |

**Stage A verdict: FAIL** — one problem, and only one:
`calibrated_go2_reanchoring: false_arrival=1 != 0`.

### Non-vacuity evidence, item by item

1. **The injection ran.** Every drift arm recorded 61 drift rows for 61 episodes;
   the truth control recorded **no** `pose_drift` block at all, which is asserted
   as its own failure mode (`truth control recorded a pose_drift block`).
2. **It drifted, in its own envelope.** 181 of 181 banded episodes across the six
   arms are in band; **zero** out-of-band episodes. Reported as a count against
   `episodes_banded`, never as a mean, so one wild row cannot hide behind fifty.
3. **Every episode drew its own seed.** 61 distinct seeds on all six arms.
4. **The tiers separate at the arm mean.** 2.65 % → 5.00 % → 14.13 % on
   nominal → aggressive → degraded: strictly monotone, and a clean 1 : 1.89 : 5.33
   ladder on a substrate whose paths include turns (DR-1's straight-line ladder is
   1 : 2.00 : 4.15; turns partially cancel accumulated heading bias, exactly as
   DR1_STATUS §6 warns, so the two are not expected to match).
5. **Slip fired.** 9 and 10 discrete slip events on the two `go2_degraded*` arms,
   zero on every non-slip profile.
6. **The LOST window held and recovered.** 1830 = 61 x 30 ticks on each `*_lost`
   arm, 61/61 episodes recovered, 0 ticks on every other arm.
7. **The re-anchor metric is scoped and real.** 518 MAP zero-crossings on
   `calibrated_go2_reanchoring` and **0** on all six other arms — measured, not
   assumed, so the scoping in `non_vacuity()` is justified by the data.

## 5. The STOP-and-report finding, reproduced and mechanised

Episode `nav-drift-object_goal-10-0871ef2f` (`walk towards the tree`, target
`tree_1`, K0 `relative_band` [0.6, 2.5] m around (-5.0, 3.15)). It **succeeds
cleanly under the truth control** (`agreement`, true distance 2.468 m, inside the
band). Under `calibrated_go2_reanchoring` it is a `false_arrival`.

Reproduced twice from the arm's own prefix (episodes 0–10 of the same fresh
runner, the run order the arm uses), at the tick the navigator claimed arrival:

| quantity | value |
|---|---|
| MAP-frame distance to the anchor | **2.4929 m** — inside the 2.5 m band edge |
| TRUE distance to the anchor | **2.6530 m** — 0.153 m outside it |
| MAP-vs-truth error | 0.2391 m (episode peak; re-anchors cap it every 5 s) |
| MAP position sigma reported by the provider | **0.0658 m** |
| ODOM-vs-truth divergence | 0.539 m = 5.70 %, **in band** |
| `reason` / `system_arrival` / `scorer_arrival` | `arrived_verified` / True / **False** |

Three things follow, and all three are measurements:

1. **Drift reaches the arrival predicate through MAP, not ODOM.** On the other
   six arms `map_correction` is off, so `_maybe_correct_map` assigns
   `MAP := truth` every tick (`pose.py:564-570`) and the navigator's arrival
   check reads an *exact* pose. `calibrated_go2_reanchoring` is the only arm
   where MAP genuinely drifts — and it is the only arm with a false arrival.
   That is a mechanism, not a coincidence.
2. **The margin is small and the error is smaller.** 0.24 m of MAP error was
   enough, because it only had to cross a 2.5 m band edge by 0.15 m.
3. **Covariance would not have saved it.** The provider reported
   `position_sigma_m = 0.0658 m` against a realised error of 0.2391 m — **3.6x
   under-reported**, because `_var_xy` accumulates only the alpha terms and the
   *systematic* scale and yaw biases are deliberately excluded from it
   (DR1_STATUS §9's stated convention: covariance reports the noise model, not
   the realised error). So "gate the arrival claim on MAP covariance" is not, by
   itself, a sufficient fix.

Not tuned away. The band was not widened (the episode is **in** band — the
injection behaved exactly as specified), the arm was not dropped, and the hard
invariant is left red. Handoff in §9.

### 5b. The finding is STRUCTURAL, not unlucky geometry — and the rate is 3/61

Fable's Wave-2 audit ran a margin analysis over **every** `arrived_verified`
episode of the re-anchoring arm rather than the one that reddened. It was
re-instrumented and re-derived here independently, and reproduces
digit-for-digit. Margin = the K0 band's 2.5 m outer edge minus the stop
distance; positive = inside.

| episode | authority verdict | MAP margin m | TRUE margin m | claim-tick MAP error m | reported sigma m |
|---|---|---|---|---|---|
| `…object_goal-10-0871ef2f` | **false_arrival** | 0.0071 | **−0.1530** | 0.2391 | 0.0658 |
| `…object_goal-52-4ff26643` | *tolerated_boundary* | 0.0258 | **−0.0429** | 0.2321 | 0.0592 |
| `…object_goal-27-117a16ff` | *tolerated_boundary* | 0.0021 | **−0.0239** | 0.0402 | 0.0610 |
| `…object_goal-15-a60da7f9` | agreement | 0.0397 | 0.0050 | 0.1651 | 0.0648 |
| `…object_goal-16-2dd13a3a` | agreement | 0.0112 | 0.0112 | 0.0614 | 0.0690 |
| `…object_goal-35-9e407a31` | agreement | 0.0267 | 0.0205 | 0.0065 | 0.0632 |
| `…object_goal-00-1d1e67a2` | agreement | 0.0323 | 0.0376 | 0.0676 | 0.0681 |

Read it in this order:

1. **The arrival predicate consumes 100 % of the band and keeps no margin for
   pose error.** Every one of the seven stops sits **0.0021–0.0397 m** inside the
   outer edge (median 0.026 m) — the controller drives to the boundary and stops
   *on* it. Against that, the claim-tick MAP errors are **0.0065–0.2391 m**
   (median 0.068 m): an order of magnitude larger.
2. **So 6 of 7 arrivals had a TRUE margin smaller than their own MAP error** —
   i.e. on six of seven the pose error alone was large enough to have decided the
   verdict. Whether a given episode lands inside or outside is then a coin flip
   weighted by the drift tier, not by the cell's geometry.
3. **Three of seven actually stopped TRUE-outside the band** (−0.153, −0.043,
   −0.024 m). Only the first exceeded the scorer's
   `ARRIVAL_BOUNDARY_EPSILON_M = 0.05` (`instructnav/scoring.py:100`) and was
   counted `false_arrival`; the other two were **absorbed as
   `tolerated_boundary`** — a category that exists for quantisation, not for
   pose error.

**Therefore the honest rate of drift-induced outside-band stops on this arm is
3/61, not 1/61**, and the mechanism is structural: because the predicate leaves
no margin, the false-arrival rate is set by the *drift tier*, and a worse tier
with a drifting MAP would produce more of them. The single red the gate reports
is the visible tip of it.

`ARRIVAL_BOUNDARY_EPSILON_M` was **not** changed, the gate was **not** changed,
and the two absorbed episodes were **not** re-counted into any gated number. The
epsilon is doing its documented job; what §5b establishes is that on a drifting
MAP it is also absorbing a different failure than the one it was sized for, and
that is the owner's call, not this card's.

## 6. The pinned floors

Mechanical and total: `floor(profile, sr) = Stage-A sr - 1/n`, n = 61, quantum
0.016393442622950821. No other margin, no per-profile discretion.

| profile | Stage-A SR | successes | pinned floor |
|---|---|---|---|
| `calibrated_go2` | 0.14754098360655737 | 9/61 | **0.13114754098360656** |
| `go2_aggressive` | 0.09836065573770492 | 6/61 | **0.08196721311475409** |
| `go2_degraded` | 0.04918032786885246 | 3/61 | **0.032786885245901634** |
| `calibrated_go2_lost` | 0.11475409836065574 | 7/61 | **0.09836065573770492** |
| `go2_degraded_lost` | 0.04918032786885246 | 3/61 | **0.032786885245901634** |
| `calibrated_go2_reanchoring` | 0.06557377049180328 | 4/61 | **0.04918032786885246** |

Provenance, pinned in `run_drift_arms.DRIFT_FLOORS_PROVENANCE`:
`drift-arms-stage-a-20260812T061640Z.json`. The truth control carries **no**
floor — it is the reference the others are read against, not a claim.

**[audit fix 3] A truncated Stage B can no longer certify the floors.** The CLI
and `run_stage` used to return `passed=True` from `--stage b --limit N` at any
N, which is a one-flag way to dodge a red floor: the floors were derived on
n = 61, so an SR over a prefix is a statistic about a different set. A truncated
Stage B now skips `check_floors` entirely, records `floors_certified: False`,
appends its own problem and **cannot pass** (`main` exits 1). Stage A is
unaffected — it certifies nothing derived. This is the same rule ci_gate's
nightly arm already applied (`:floors` → non-hard `skip` at `limit > 0`), so the
module and the gate now agree. Five cells cover it, including the seeded-failure
companion `test_a_red_floor_cannot_be_dodged_by_truncating` (every arm under
water; both the full and the truncated run must refuse to pass).

**[audit fix 4] Traceability now checks the artifact is the FULL substrate.**
`test_the_pinned_floors_are_exactly_the_recorded_stage_a_artifact` re-derived
the floors from the provenance artifact but never checked what that artifact
covered — `derive_floors` is total and would happily re-derive from a
three-episode run. It now asserts `payload["n"] == len(generate_drift_cells())
== 61`, that every arm row carries `n == 61`, and that the arm set equals the
pre-registered `DRIFT_ARMS`. Two seeded-failure companions prove it: a Stage-A
artifact truncated to n = 3, and one missing an arm, are both rejected.

`test_the_pinned_floors_are_exactly_the_recorded_stage_a_artifact` opens that
artifact, re-runs `derive_floors` over its own arm rows and asserts equality, so
a hand-edited floor cannot survive a commit and a floor can always be traced to
the invocation that produced it (the Y-3 lesson, enforced rather than promised).

**Why pin at all when Stage A failed its hard invariant.** The floors are SR
regression catchers and a *different gate* from `:safety`. Leaving them unpinned
would have traded a real red (`:safety`, correctly firing on a live defect) for
a silent one (`:floors` skipping forever). Nothing here turns the safety gate
green; §7 shows it red.

### Stage B

`.parcel/bin/python -m evals.nav_instruct.run_drift_arms --stage b` →
`evals/nav_instruct/results/drift-arms-stage-b-20260812T064743Z.json`

**Verdict: FAIL — on the §5 finding and on nothing else.**

- **Floors: PASS.** `check_floors` returns the empty list; all six arms sit at or
  above their pinned floor. The only entry in Stage B's `problems` list is
  `calibrated_go2_reanchoring: false_arrival=1 != 0`.
- **Reproducibility: exact.** Stage B reproduces Stage A bit for bit on every
  arm's `(SR, collisions, false_arrival, total path m)`, and
  `derive_floors(stage_B) == derive_floors(stage_A) == DRIFT_FLOORS`. The two
  stages really are one harness invocation apart, which is what makes the "minus
  exactly one episode quantum" margin meaningful rather than decorative.
- Consequently the false arrival is **not a flake**: it is a deterministic
  property of that episode under that profile, observed on two independent full
  runs 30 minutes apart.

## 7. Gate table

| Gate | Result |
|---|---|
| `ci_gate --tier commit` (final, fresh, `2026-08-12T07:49:21Z`, post-audit-fixes) | **PASS — every hard gate green.** 3909 passed, 9 skipped, 0 failed; ruff 7 violations = baseline 7, **new 0**; all 4 frozen sentinels byte-identical; frozen baseline collisions=0 false_arrival=0 |
| `tests/test_dr2_pose_drift_arm.py` | **88 passed** in ~16 s |
| `ruff check` on every touched file | **All checks passed** — 0 new fingerprints |
| nightly `pose-drift-arms:safety` | **FAIL** — the §5 finding, correctly red |
| nightly `pose-drift-arms:non-vacuity` | **PASS** |
| nightly `pose-drift-arms:floors` | **PASS** (full substrate) |

**Exactly what was run for the three nightly verdicts.** The nightly arm is
~26 minutes of simulation per invocation, so it was exercised twice, and both
are reported rather than one being presented as the other:

1. **The real gate, at a stated limit** —
   `evaluate_pose_drift_arms(tier="nightly", limit=12)`, 7 arms x 12 cells:

   ```
   [FAIL ] HARD  pose-drift-arms:safety       calibrated_go2_reanchoring: false_arrival=1 != 0
   [PASS ] HARD  pose-drift-arms:non-vacuity  43/43 episode(s) in band; SR truth=0.250,
                                              calibrated_go2=0.250, go2_aggressive=0.000,
                                              go2_degraded=0.000, calibrated_go2_lost=0.167,
                                              go2_degraded_lost=0.000,
                                              calibrated_go2_reanchoring=0.083
   [SKIP ] soft  pose-drift-arms:floors       limit=12 truncates the substrate the floors
                                              were derived on (6 arm(s) pinned); a partial
                                              run cannot certify them either way
   ```

   The finding is inside the first 12 cells (episode index 10), so the truncated
   run reproduces it.

2. **Full substrate (n = 61), DERIVED — not a third 26-minute run.** The Stage-B
   artifact above *is* the payload `evaluate_pose_drift_arms(limit=0)` computes
   (`run_stage("b")`), so its arm rows were passed through ci_gate's own
   `hard_invariants` / `non_vacuity` / `ladder_monotone` / `check_floors`:
   `:safety` **FAIL** (`false_arrival=1`), `:non-vacuity` **PASS** (181/181
   episodes in band), `:floors` **PASS** (6 arms at or above their floor). Stated
   as derived, because it is.

### The nightly self-test the card requires

`TestNightlyGateSelfTest` (13 cells) seeds a failure at the harness boundary —
`run_stage` is monkeypatched to return a payload shaped exactly like a real
Stage-B run — so every verdict is produced by ci_gate's **real** checkers
(`hard_invariants`, `non_vacuity`, `ladder_monotone`, `check_floors`) with no
gate logic stubbed. Proved to redden on: a seeded collision, a seeded
false_arrival, an arm whose seeds did not vary, an out-of-band episode, an arm
that silently ran on truth (`pose_drift` absent — green on safety, red here),
an SR one epsilon below its pinned floor, and a harness explosion (which must
`error` rather than disappear). Also proved: the clean payload is green on all
three; the unpinned state is a loud non-hard `skip`, never a quiet pass; the
nightly tier really wires `evaluate_pose_drift_arms` in; and the commit tier
really does not.

One nightly-arm change was made for honesty: `evaluate_pose_drift_arms(limit=N)`
with `N > 0` now degrades `:floors` to a non-hard `skip` naming the limit,
because a truncated run measures a *different* set from the one the floors were
derived on and cannot certify them either way. Safety and non-vacuity are
per-episode properties and stay hard at any limit. Both behaviours are pinned.

## 8. OWNS compliance, with git-diff numbers

| File | numstat | DR-2's share |
|---|---|---|
| `evals/nav_instruct/runner.py` | +441 / −15 | **+431 / −12**; the other +10 / −3 is the `ALLOWED_NAVIGATOR_OVERRIDES` growth (cards D15-B `person_aware_nav`, VS-4 `lock_on_verify_on_approach`), which landed in this batch before this session |
| `evals/nav_instruct/run_nav_instruct_v1.py` | +194 / −23 | the `--pose-drift-profile` and `--drift-cells` arguments, the two `--freeze` refusals, the `v4d` set label / report suffix, the report + ledger stamping, and the report-write reorder (§2 defect 3). The rest is the prior card's `--episode-set` / `--per-axis` / v4s generation work, already in the batch |
| `scripts/ci_gate.py` | +225 / −0 | **+112 / −0**, all of it `evaluate_pose_drift_arms` + 2 lines of nightly wiring. **Commit-tier logic untouched by DR-2** — the one commit-tier line in the diff (`evaluate_followbench_jerk_ledger`) is the jerk-ratchet card's |
| `evals/nav_instruct/drift_cells.py` | NEW, 351 lines | DR-2 |
| `evals/nav_instruct/run_drift_arms.py` | NEW, 417 lines | DR-2 |
| `tests/test_dr2_pose_drift_arm.py` | NEW, 1191 lines, **88 tests** | DR-2 |
| `evals/nav_instruct/results/ledger.jsonl` | +1 / −0 | one **candidate**, `frozen_baseline: false` row from the CLI end-to-end proof |
| `scrum/20260811/task_2/DR2_STATUS.md` | NEW | this doc |

Only DR-2's own deletions in `runner.py` (12 lines) touch pre-existing code, and
they are three edits: adding `replace` to a `dataclasses` import; hoisting
`_nav_observation(...)` out of the `navigator.step(...)` call so a
`pose_provider=` can be passed (byte-identical when it is `None` — proved
below); and adding `and note != POSE_LOST_HOLD_NOTE` to the terminal condition.

**MUST-NOT-TOUCH honoured.** `runtime.py`, `navigation/pipeline.py`,
`route_memory/**` (RM-2's), `pose.py`, `configs/navigation/pose.yaml` (DR-1
frozen) and `headless_city.py` are untouched by this card. No frozen episode
file, no frozen digest and no frozen row moved; the only results written are
candidate-mode. RM-2 is concurrently editing `pipeline.py` / `runtime.py` /
`route_memory/{proposer,runtime_hook}.py`; their flag is default-OFF and their
edits appeared mid-run without moving any DR-2 number.

### Flag-off byte path, proved four ways

1. **Structural.** With no profile named the harness is *literally* the stock
   `HeadlessCityQualityHarness` (type identity asserted, not `isinstance`), and
   `_new_pose_provider()` returns `(None, None)` — not "a truth provider".
2. **Observation-level.** `_nav_observation(obs, …)` and
   `_nav_observation(obs, …, pose_provider=None)` produce the same position,
   heading and extras key set, with `extras["pose_provider"] is None` in both.
3. **Row-level.** A flag-off `EpisodeRunResult.as_dict()` carries neither
   `pose_drift_profile` nor `pose_drift`, so a truth-pose row keeps the shape
   every row already in the ledger has.
4. **Digest-level, for the one changed line of control flow.** The terminal
   condition gained `and note != POSE_LOST_HOLD_NOTE`. Rebinding that constant to
   a note no command can carry restores the **pre-DR-2 condition exactly**;
   `test_the_pose_lost_note_guard_is_inert_on_the_truth_path` runs the same
   episode both ways and asserts the two payload sha256 digests are **equal**.
   Corroborated structurally: `pipeline._pose_lost_hold` needs a LOST **MAP**
   pose, and a truth-pose observation is asserted `HEALTHY`.

That guard is not cosmetic. Without it the runner ended an episode on the LOST
window's first tick, and the `*_lost` arm's recovery assertion was *unprovable*
rather than false. With it, the measured result is 61/61 windows held and
recovered.

## 9. Handoffs

1. **[OWNER / a pipeline card] The arrival predicate keeps no margin for pose
   error.** §5 and **§5b**. The claim is evaluated on the MAP pose while K0
   scores truth, and the controller stops a median of **0.026 m** inside a 2.5 m
   band against MAP errors with a median of **0.068 m** — so **6 of 7** arrivals
   on the re-anchoring arm had a true margin smaller than their own pose error,
   **3 of 7** stopped outside the band, and only the one exceeding
   `ARRIVAL_BOUNDARY_EPSILON_M = 0.05` was reported. The honest rate is
   **3/61, not 1/61**, and it scales with the drift tier rather than with
   geometry.

   What will *not* fix it, measured: (a) `_semantic_arrival_verified` already
   blocks the claim on `DEGRADED` health — this provider reports `HEALTHY`;
   (b) gating on covariance — the reported `position_sigma_m` (0.059–0.069 m
   across all seven arrivals) is **3.6x optimistic** against a 0.239 m realised
   error, because `_var_xy` excludes the systematic scale and yaw biases by
   design (DR1_STATUS §9); (c) widening `ARRIVAL_BOUNDARY_EPSILON_M` — that
   hides the symptom in `tolerated_boundary`, which is where two of the three
   already went.

   The decision is whether the arrival predicate must reserve a margin
   proportional to the pose uncertainty it is reading, and what that uncertainty
   is allowed to be — a design question in `navigation/pipeline.py` and
   `instructnav/scoring.py`, both out of DR-2's OWNS.
2. **[SUBSTRATE, a future card] The admission rule under-approximates geometry.**
   `_v4s_point_is_free` / `_v4s_segment_blockers` model buildings as **discs**
   while MuJoCo has boxes, so an admitted start can sit far tighter than the rule
   believes: measured true clearances of **0.06 m, 0.82 m, 0.98 m** at admitted
   starts. Under the truth control, cells starting below 2 m of true clearance
   succeed **1 of 25** (4 %) against **9 of 36** (25 %) above it. It is the
   single largest driver of the substrate's low SR. Fixing it means giving the
   generator the world's own occupancy, which changes the cell set — a
   re-derivation, not an edit, and one that must not be done while a floor
   derived from the current set is pinned.
3. **[REPORT-ONLY] The v4 minival tripwire was not run.** The card registers it
   as report-only (no floor); it is drift-insensitive (13.5 m total across 25
   episodes, Lane B measured an SPL delta of 0.0003), so it was left out rather
   than reported as if it meant something. `--pose-drift-profile` works on any
   set, so it is one command away.
4. **[DR-1] No handoff needed.** The derived `(4.0 s, 3.0 s)` LOST window fits
   this substrate with room on both sides (§4); `pose.yaml` stayed frozen.

## 10. does_not_prove

- **Six of the seven arms cannot exercise arrival honesty against drift at all.**
  `MAP` is truth-passthrough on every profile without `map_correction`
  (`pose.py:564-566`), so on those arms the navigator's arrival predicate reads
  an *exact* pose: injected drift cannot reach it, and a `false_arrival` there
  would have to come from something other than pose. (Those arms do show 3–5
  `authority_disagreement` verdicts each, so the instrument is live — it simply
  is not measuring pose.) As a test of pose-induced arrival dishonesty the
  invariant is informative on `calibrated_go2_reanchoring` only — where it fired.
- The substrate's absolute SR (truth control **0.1639** = 10/61) is low, and 40
  of its 51 failures are `navigation_step_limit`. These arms measure
  *relative* degradation under drift against a control on the same cells; they
  are not a capability claim about the navigator, and the SR floors are
  regression catchers, not a bar anything passed.
- The spatial families (`follow_owner` / `circle_owner`) build their provider
  inside `harness.run`, so their rows carry only end-of-episode counters, never
  the per-tick LOST / re-anchor observations. No drift cell is a spatial family,
  so no measurement here depends on that path.
- These profiles are a stand-in for leg odometry, not a model of one
  (DR1_STATUS §9). Nothing here claims any of it resembles a real Go2 on real
  terrain, and nothing here is camera perception.
- Stage A and Stage B are the *same* deterministic invocation one apart, so
  Stage B agreeing with Stage A is a reproducibility check, not independent
  evidence.
- The `k = 2` / `k = 4` tier multipliers, the slip constants and the
  `(0.5x, 2.0x)` band factors are declared choices with documented derivations.
  None of them may ever be tuned against a downstream eval gate.
