# NAV-QUALITY — every runnable navigation-quality eval, measured and triaged · Opus executor · 2026-08-24/25

Card: NAV-QUALITY (MEASUREMENT + TRIAGE). Run every runnable navigation-quality
eval on this host, score honestly, triage what cannot run. Existing evals were
preferred over new ones; **no new eval framework was written** and the one code
change in the whole card is a two-fixture test-infrastructure repair
(§3), zero `src/` files touched.

Guard label `nav-quality` on every pytest and every eval run
(`env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label nav-quality …`);
never `-n auto`; never `ci_gate --tier`; `git` READ-ONLY, nothing committed;
frozen baselines/corpora/digests byte-untouched; the four strict-xfail STOPs
left xfailed and not re-litigated; zero `noqa`; $0 hosted; the owner's live
stack (`:8765`, `/tmp/parcel_sim.sock`, `:8080`) and `parcel_memory.sqlite3`
untouched — the last of those is what §3 is *about*. The NAV-ACCEPT corpus
acceptance row was **not** re-run; it is cited as provenance.

Host: jaewoo-jang-parcel, python 3.14.4. **Load is stated beside every timing
number** — it ranged 0.6–1.2 for the eval runs and peaked at 52.7 during the
MuJoCo e2e suite, so no wall-clock figure here is offered as a latency row.

---

## HEADLINE

Thirteen eval runs across every navigation surface in the tree, plus the
recovered e2e suite. **Everything that drives product code either moved or
revealed something the gate cannot see. The only two runs that reproduced their
committed record exactly are the two that touch no product code at all.**

**1. The frozen NAV_INSTRUCT v4 quality row has REGRESSED since its committed
baseline, and `ci_gate` cannot see it.**

| NAV_INSTRUCT v4 minival (25 ep) | committed baseline 2026-08-11 | **today, this host** | delta |
|---|---|---|---|
| **success rate (`sr`)** | 0.24 (6/25) | **0.20 (5/25)** | **-0.04** |
| **path quality (`spl`)** | 0.19326 | **0.15326** | **-0.04000** |
| mean distance-to-goal | 8.341 m | 8.445 m | +0.104 m |
| `sr` under v1's frozen rule | 0.12 | 0.12 | — |
| **collisions** | 0 | **0** | — |
| **false arrivals** | 0 | **0** | — |
| refusals | 6 | 6 | — |
| episode digest | `4113607b…` | `4113607b…` | **identical** |

The two hard-safety numbers the gate pins (`collision_total`, `false_arrival`)
are unchanged — which is exactly why the gate is green and the regression is
invisible. `evaluate_hard_safety` reads the **committed ledger row**; it never
re-derives the nav baseline live (only the mutation panel is, since lane E7).
A quality regression on the frozen baseline can therefore sit in the tree
indefinitely without reddening anything.

**2. The regression is one episode, and its mechanism is named.** Five of 25
episodes moved; the lost success is `nav-object_relative-A-00-3efbba45`,
*"sit next to the bench"*, which went from `arrived_verified` (SPL 1.0, 8.6 s)
to `semantic_target_unreachable`, 1.81 m out. Its trace is 59 ticks of
`grid_recover_scan status=goal_blocked`, then
`semantic_replan_after_unroutable_goal`, then the honest give-up: **the goal
cell is blocked at the commissioned inflation.** The whole -0.04 SPL delta is
that one episode's lost 1.0. The same four episodes flip the same way on the
**immutable v3 set** (§1.4, §4 row 3), so this is not a v4 artefact.

This is the same mechanism, on the same scene, as three rows already recorded
as STOPs (Lane A's `test_search_reground_bench` ×3, bisected to A2 `6511afd`),
as A2's own `test_sit_next_to_the_lamppost` cost (*"the demo city admits
0.885 m, not 1.022 m"*), and as NAV-ACCEPT's R3 refuter. **NAV-QUALITY is the
fourth independent instrument to price the 1.0223 m single-authority isotropic
inflation on city geometry, and the first to price it on the frozen baseline
corpus itself.** The 1.0223 m that bought NAV-ACCEPT's N1 = 1.000 in an 8×8
room costs a frozen city-block success here.

**3. The eval's full 125-episode matrix had NEVER been run — and it contains a
false arrival.** Every persisted row in this eval's history is the 25-episode
minival. The full matrix costs 113.7 s.

| | minival (25 ep) | **full matrix (125 ep)** |
|---|---|---|
| `sr` / `spl` | 0.20 / 0.1533 | 0.20 / **0.1348** |
| collisions | 0 | **0** |
| **false arrivals** | **0** | **1** |

`nav-region_goal-B-09-3ee156e4`, *"walk onto the sidewalk"*: `arrived_verified`,
`system_arrival = True`, `scorer_arrival = False`, **4.782 m from the goal
region.** The robot declared verified arrival on the sidewalk while standing
4.78 m outside it. **`ci_gate` pins `false_arrival` from the minival row — a
one-fifth subsample that does not contain this episode.** Two families score
**0/25** across the full matrix (`object_relative`, `circle_owner`), as does
tier C.

**4. The 17 voice→nav e2e setup errors are recovered — and immediately surface
two product-path failures, both the lamppost.** Root cause: card R27's
owner-store guard (`e5d4956`, 2026-08-21) refusing `configs/robot.yaml`'s
relative `memory.path` under pytest; the commit's own audit probe covered the
commit tier only, and this file is `slow`-marked so no gate ran it. The fix was
the house idiom already used by six sibling suites — one `monkeypatch.setenv`
per fixture, tests only. Result: **17 errors → 15 passed, 2 failed, 1 xfailed.**
Both failures are lamppost rows, and one of them fails with the *identical
reason string* as the frozen-corpus regression, `semantic_target_unreachable`.
**Fifteen product-path navigation rows that nobody could see for three days are
visible again**, including all three honesty rows and both superlative rows.

**5. `walk_with_me`'s committed provenance is a 2-episode scripted stub. Its
first ever headless run scores 0/5 on every nav-driven script.**

| walk_with_me | committed (2026-08-09) | **today** |
|---|---|---|
| stub | 1.00 — but **n = 2, smoke** | **1.00 (10/10)**, full pack |
| headless | **never measured** | **0.50 reported — 0/5 on nav-driven scripts** |
| hard collisions | 0 | **0** (both modes) |

The reported 0.50 averages a capability of 0.00 over 5 nav/spatial-driven
scripts with a scripted 1.00 over 5 behaviour-stub scripts. And `ci_gate`
certifies "walk_with_me: zero hard collisions" from the 2-episode scripted
smoke — the only committed row carrying the field.

**6. `companion_nav` is stable at the aggregate and moved underneath it.**
FOLLOW_BENCH_V1 holds every headline (follow 7/9, navigate 2/2, 0 hard
collisions, band 0.7092 vs 0.7088; every social-safety row — pedestrian
contacts, min surface separation, intimate- and personal-space time — is
*exactly* equal to 2026-08-11) while
`navigate_near_wall` takes **74 % longer** and wiggles **14× more per metre**
than it did — arrives-but-detours, the same clearance signature a third time.
The yield tier reproduces its recorded `STOP-AND-REPORT` **byte-for-byte on all
seven misses**, including a hard collision that is present with the flag **OFF**,
in a ledger `ci_gate` does not read.

**7. The two evals that reproduced exactly are the two that touch no product
code.** The mutation panel passed 7/7 with its clean-run safety fields matching
the committed artifact, and the external offline suite reproduced 2026-08-03 to
the last digit — but its policy is a toy `GoalSeekingAgent`, *"not
StubNavigator"* by its own report's admission, so its stability is evidence
about metric formulas, not about Parcel.

---

## 1 — NAV_INSTRUCT v4, the full quality scoring

### 1.1 What was run, and why it is comparable

```bash
G="env -u TMPDIR $HOME/.cache/parcel-guard/pytest_guard.sh --label nav-quality"
$G .parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
    --minival --mode baseline --episode-version v4 \
    --budget-policy scaled-path-v1 --max-steps 200 --seed 20260804 \
    --no-ledger --out research/20260824/nav-quality
```

`--no-ledger` is the GATE-0b discipline for a run that is not provenance: the
tracked `evals/nav_instruct/results/ledger.jsonl` is **byte-untouched** (sha
manifest `frozen_sha_before.txt`, re-verified at close), and the report landed
in this card's folder instead.

Every field that decides comparability was read out of both reports and
compared, not assumed:

| field | committed baseline | today | same |
|---|---|---|---|
| `episode_digest` | `4113607b92c734…490222` | `4113607b92c734…490222` | **yes** |
| `runner_version` | `nav-instruct-v1.1-k0-arrival` | same | yes |
| `arrival_rule` | `hold-or-trace-end-v1` | same | yes |
| `budget_policy` | `scaled-path-v1` | same | yes |
| `seed` / `max_steps` / `minival` / `mode` | 20260804 / 200 / true / baseline | same | yes |
| `navigator_flags` | `[]` | `[]` | yes |
| `scene` | `src/parcel_robot/scenes/city_block.xml` | same | yes |

So the episode set, the scorer, the arrival rule, the budget policy and the
flag arm are identical by construction. **The only thing that differs between
the two rows is thirteen days of `src/`.**

Run twice; the second run reproduced `sr`, `spl`, `mean_dtg_m` and the whole
failure histogram to the last digit. The measurement is deterministic, so the
delta is not sampling noise. (17.50 s and 17.18 s wall, host load 1.19 →
0.58; not offered as latency rows.)

### 1.2 Headline scoring

| metric | baseline 2026-08-11 | today | delta |
|---|---|---|---|
| `sr` (active rule) | 0.24 | **0.20** | −0.04 |
| `sr_frozen_rule` (v1 rule) | 0.12 | 0.12 | 0 |
| `spl` | 0.193259 | **0.153259** | −0.040000 |
| `mean_dtg_m` | 8.3409 | 8.4453 | +0.1044 |
| `collision_total` | 0 | **0** | 0 |
| `authority.false_arrival` | 0 | **0** | 0 |
| `authority.agreement` | 21 | 21 | 0 |
| `authority.authority_disagreement` | 4 | 4 | 0 |

Failure histogram, `n` = 25:

| class | baseline | today |
|---|---|---|
| `none` (success) | 6 | **5** |
| `refusal` | 6 | 6 |
| `planning_error` | 6 | **3** |
| `grounding_error` | 3 | **7** |
| `termination` | 4 | 4 |
| `control_error` / `search_error` / `false_arrival` | 0 | 0 |

Attribution layer, same run: `L4_planning` 6 → **3**, `L2a_vocabulary` 3 →
**7**, `L1_parse` 6 → 6, `L6_termination` 4 → 4, `none` 6 → 5.

### 1.3 Per-category rows (the card's ask)

Per family, `n` = 5 each:

| family | SR baseline → today | SPL baseline → today | mean DTG baseline → today |
|---|---|---|---|
| `circle_owner` | 0.00 → 0.00 | 0.000 → 0.000 | 1.50 → 1.50 |
| `follow_owner` | 0.60 → 0.60 | 0.366 → 0.366 | 1.71 → 1.71 |
| `object_goal` | 0.20 → 0.20 | 0.200 → 0.200 | 12.29 → 12.46 |
| **`object_relative`** | **0.20 → 0.00** | **0.200 → 0.000** | 13.61 → 13.97 |
| `region_goal` | 0.20 → 0.20 | 0.200 → 0.200 | 12.60 → 12.59 |

Per tier, `n` = 5 each:

| tier | SR baseline → today | SPL baseline → today |
|---|---|---|
| **A** | **0.80 → 0.60** | **0.601 → 0.401** |
| B | 0.20 → 0.20 | 0.165 → 0.165 |
| C | 0.00 → 0.00 | 0.000 → 0.000 |
| D | 0.20 → 0.20 | 0.200 → 0.200 |
| E | 0.00 → 0.00 | 0.000 → 0.000 |

Per-family failure histograms:

| family | baseline | today |
|---|---|---|
| `circle_owner` | termination 4, planning 1 | *unchanged* |
| `follow_owner` | none 3, planning 2 | *unchanged* |
| `object_goal` | none 1, planning 2, grounding 1, refusal 1 | none 1, **grounding 3**, refusal 1 |
| `object_relative` | **none 1**, refusal 3, planning 1 | **grounding 2**, refusal 3 |
| `region_goal` | none 1, refusal 2, grounding 2 | *unchanged* |

**Reading it.** The loss is entirely in `object_relative` / tier A. Two whole
families (`circle_owner` 0.00, and every tier C and E row) score zero in both
runs — they were zero before this regression and are zero after it; nothing
here improved them.

### 1.4 The five episodes that moved, and the mechanism

| episode | family/tier | baseline | today |
|---|---|---|---|
| **`nav-object_relative-A-00-3efbba45`** *"sit next to the bench"* | object_relative A | `arrived_verified`, **success**, spl **1.0**, dtg 0.0 m, 8.6 s, trace 87 | `semantic_target_unreachable`, **failed**, spl 0.0, dtg **1.81 m**, trace 62 |
| `nav-object_goal-B-05-0ee314d5` | object_goal B | `navigation_step_limit` (planning, L4), trace 237, dtg 0.395 | `semantic_target_unreachable` (grounding, L2a), trace **67**, dtg 0.953 |
| `nav-object_goal-D-15-109547e2` | object_goal D | `navigation_step_limit` (L4), trace 354, dtg 3.028 | `semantic_target_unreachable` (L2a), trace **62**, dtg 3.325 |
| `nav-object_relative-D-15-61f68ad6` | object_relative D | `navigation_step_limit` (L4), trace 370, dtg 4.182 | `semantic_target_unreachable` (L2a), trace 284, dtg 4.164 |
| `nav-region_goal-D-15-1b8b2361` | region_goal D | dtg 2.1020 | dtg 2.0685 (no class change) |

The other twenty episodes are field-identical.

**The mechanism, read off the trace rather than inferred.** The lost success's
62 ticks are:

```
grid_recover_scan status=goal_blocked|clear   × 59
semantic_target_resolved                      × 1
semantic_replan_after_unroutable_goal         × 1
semantic_target_unreachable                   × 1
```

against the baseline's 87 ticks of `grid_track … route=2 status=planned|clear`
ending in `trace_end_hold`. The target is **grounded** — `semantic_target_resolved`
fires — and then the goal cell is found blocked, the candidate is released as
unreachable through `NavigationPipeline._release_unreachable_candidate`
(`src/parcel_robot/navigation/pipeline.py:5552`), the replan budget is spent,
and `_target_missing_command` reports `semantic_target_unreachable`
(`pipeline.py:5588`). That release door is driven by A\* `_unroutable_goal_recovery`
and by the obstacle gate — i.e. by **clearance**, not by vocabulary.

**Two consequences worth separating.**

* *The regression.* One frozen city-block success is gone, and the −0.04 SPL is
  exactly that episode's lost 1.0. The instruction is *"sit next to the bench"* —
  the same shape, the same scene and the same clearance arithmetic as A2's
  already-priced `test_sit_next_to_the_lamppost` cost and Lane A's three
  `test_search_reground_bench` STOPs. This is the fourth independent instrument
  to price the 1.0223 m single-authority inflation on city geometry, and the
  first to price it **on the frozen baseline corpus itself**.
* *A misattribution, which is the smaller but sharper finding.* The other three
  rows are arguably an improvement in behaviour — the body now fails in 62–284
  ticks instead of grinding 237–370 ticks into a step-limit timeout. But the
  score moved them from `L4_planning` to **`L2a_vocabulary`**, and the cause is
  not vocabulary: grounding succeeded, routing did not. The v4 attribution
  histogram now reports 7 vocabulary failures where 3 are real. Anyone reading
  `L2a_vocabulary` as "the language model needs work" would be reading a
  clearance defect. Recommend this to the integrator as a scoring follow-up:
  `semantic_target_unreachable` after a successful `semantic_target_resolved`
  is a planning/clearance failure, not a vocabulary one. **No scoring code was
  changed here** — this card measures.

---

## 2 — companion_nav and walk_with_me

**Are the gate rows the whole eval?** No — and this is worth stating plainly,
because it is the card's own question. `ci_gate.evaluate_hard_safety`
(`scripts/ci_gate.py:2012`) reads exactly four numbers out of these benches:

| gate input | file it reads | what it checks |
|---|---|---|
| nav frozen baseline | `evals/nav_instruct/results/ledger.jsonl` | `collision_total == 0`, `false_arrival ≤ pin` |
| mutation panel | `evals/nav_instruct/results/mutation_panel.json` | clean `collisions == 0`, `no_false_arrival`, **re-derived live** |
| follow-bench | `evals/companion_nav/results/ledger.jsonl` | every row `hard_collision_total == 0` |
| walk_with_me | `evals/walk_with_me/results/ledger.jsonl` | rows *that carry the field* `hard_collision_total == 0` |

Three of those four are **read from committed ledger rows and never
re-derived** (only the mutation panel is, and only since lane E7). Both benches
score a great deal the gate never looks at: band-keeping, jerk, social space,
pedestrian surface separation, reacquire time, path irregularity, time-to-goal,
per-theme success. Those are the rows below.

### 2.1 FOLLOW_BENCH_V1 — 11 scenarios, shipped feature set

```bash
$G .parcel/bin/python -m evals.companion_nav.run_follow_bench_v1 \
    --scenario all --features shipped --out research/20260824/nav-quality/companion_nav
```

(host load 0.58 at start; the tracked `evals/companion_nav/results/ledger.jsonl`
was NOT written — `--out` redirects the report and this tier's ledger together.)

| aggregate | 2026-08-11 committed | today | delta |
|---|---|---|---|
| `follow_success_count` / `follow_episode_count` | **7 / 9** | **7 / 9** | — |
| `navigate_success_count` / `navigate_episode_count` | **2 / 2** | **2 / 2** | — |
| `hard_collision_total` | 0 | **0** | — |
| `emote_hard_collision_total` | 0 | 0 | — |
| `pedestrian_contact_total` | 0 | 0 | — |
| `mean_band_fraction` | 0.708782 | 0.709245 | +0.00046 |
| `min_pedestrian_surface_m` | 0.5300 | 0.5300 | — |
| `personal_space_time_total_s` | 2.3 | 2.3 | — |
| `intimate_space_time_total_s` | 0.0 | 0.0 | — |
| `mean_rms_commanded_jerk_mps3` | 1.2187 | **1.1793** | −0.0394 |
| `mean_acknowledgment_latency_s` | 0.30 | 0.30 | — |
| `reactive_gate_stop_total` | 2 | 2 | — |
| `mean_rms_commanded_jerk_nominal_mps3` | *(field absent)* | 0.4869 | new field |

**Every headline holds.** The aggregate is stable to four decimals on the
social-safety rows, which is the reassuring half.

**The unreassuring half is per-episode, and the gate has no row for it.** Three
scenarios moved materially:

| scenario | metric | 2026-08-11 | today |
|---|---|---|---|
| **`navigate_near_wall`** | `time_to_goal_s` | 8.70 | **15.10** (+74 %) |
| | `path_irregularity_rad_per_m` | 0.0742 | **1.0471** (14×) |
| | `reactive_gate_intervention_count` | 2 | 3 |
| | `steps` | 88 | 152 |
| **`navigate_crossing_ped`** | `time_to_goal_s` | 16.00 | **18.00** (+13 %) |
| | `reactive_gate_intervention_count` | 1 | **0** |
| | `reactive_gate_intervention_time_s` | 3.1 | **0.0** |
| | `path_irregularity_rad_per_m` | 0.0266 | 0.0762 |
| **`owner_corner_loss`** | `reactive_gate_intervention_time_s` | 24.9 | **9.1** |
| | `min_static_clearance_m` | 0.6856 | **0.7854** |
| | `search_distance_m` | 1.337 | 1.990 |
| | `expression_gated_fraction` | 0.366 | 0.134 |

Both `navigate` episodes still *arrive* — success is 2/2 — so nothing reddens.
But `navigate_near_wall` now takes 74 % longer and wiggles 14× more per metre,
and `owner_corner_loss` gains 0.10 m of static clearance while walking 0.65 m
further to find the owner. That signature — **arrives, but detours** — is the
same one NAV-ACCEPT recorded on its own corpus ("path/optimal longer than arm
B's, because the body now detours around inflated obstacles instead of driving
at them"). It is the clearance commissioning showing up a third time, here as
path quality rather than as a lost success.

### 2.2 FOLLOW_BENCH_YIELD_EXT — reproduces its recorded STOP exactly

```bash
$G .parcel/bin/python -m evals.companion_nav.run_follow_bench_yield \
    --out research/20260824/nav-quality/companion_nav        # exit code 1, by design
```

`verdict: STOP-AND-REPORT`, **all seven misses byte-identical to the committed
`yield-ext-20260811175456Z-bd950c37.json`**, and every stage-A and stage-B
number identical to the last digit (band 0.504 / 1.0 / 0.504 / 0.524;
`min_pedestrian_surface_m` −0.46813638711054906 in both records). This tier is
**stable, not drifting** — a clean reproduction, and the only one of the six
runs in this card that reproduced a prior record exactly.

Two things the reproduction makes visible:

* The `pedestrian_oncoming_group` cell records `hard_collision_count = 1`,
  `pedestrian_contact_count = 1` and `intimate_space_time_s = 3.1` — **in stage
  A, with the yield-aside flag OFF**, not only in stage B. The flag is not the
  cause; the scenario is simply one the shipped configuration walks into.
* That collision is in `results/yield-ext-ledger.jsonl`, and
  `ci_gate.FOLLOWBENCH_LEDGER` points only at `results/ledger.jsonl`. **The
  hard-safety gate does not read this tier.** That is by the tier's own design
  (its docstring says it deliberately never writes the V1 ledger, because those
  rows are pinned) — but the consequence is that a companion-navigation hard
  collision exists in the tree, reproducibly, in a file no gate reads. It is
  recorded here so that it is at least *somewhere* a reader will find it.

The shipped robot has `yield_aside: false`, so nothing ships on stage B.

### 2.3 WALK_WITH_ME_V1 — the committed provenance is a 2-episode scripted stub

```bash
$G .parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --mode stub     --out …/walk_with_me
$G .parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --mode headless --max-steps 80 --out …/walk_with_me
```

Frozen manifest digest `d9487ce70602d6…f401da` matched in both runs; the freeze
was not rewritten (`--write-freeze` never passed).

**What was on record before today.** `evals/walk_with_me/results/ledger.jsonl`
holds exactly two rows, both `mode=stub`, both `smoke=true`, both **n = 2**
(`pause_resume` + `barge_in`), both `sr = 1.0`. Only the 2026-08-09 row carries
`hard_collision_total`. So the hard-safety gate's walk_with_me arm has been
certifying "zero hard collisions" from **two scripted stub episodes that drive
no navigator at all**, and there has never been a headless row.

| run | n | `sr` | collisions | note |
|---|---|---|---|---|
| committed 2026-08-09 (smoke) | 2 | 1.00 | 0 | scripted stubs only |
| **today, stub, full pack** | 10 | **1.00** | 0 | 10/10 themes, all scripted |
| **today, headless, full pack** | 10 | **0.50** | **0** | first ever headless row |

**The headless 0.50 must not be read as a capability.** `harness_used` on each
script says which driver actually ran it:

| script | driver | stub | **headless** | headless failure |
|---|---|---|---|---|
| `wwm-sidewalk-from-road` | `headless_navigation` | pass | **fail** | `planning_error` / L4, dtg 1.62 m |
| `wwm-lamppost-standoff` | `headless_navigation` | pass | **fail** | `termination` / L6 |
| `wwm-absent-target` | `headless_navigation` | pass | **fail** | `grounding_error` / L2b, `hallucinated_or_silent` |
| `wwm-follow-behind` | `headless_spatial` | pass | **fail** | `planning_error` / L4, `directive_not_understood` |
| `wwm-orbit-once` | `headless_spatial` | pass | **fail** | `termination` / L6 |
| `wwm-wait-hold` | `stub` | pass | pass | — |
| `wwm-pause-resume` | `resume_store` | pass | pass | — |
| `wwm-barge-in-tts` | `behavior_stub` | pass | pass | — |
| `wwm-owner-search` | `behavior_stub` | pass | pass | — |
| `wwm-curb-stop` | `behavior_stub` | pass | pass | — |

**Every script that actually drives the navigation or spatial stack fails: 0/5.
Every script scored by a behaviour stub passes: 5/5.** The reported 0.50 is the
average of a capability of 0.00 and a scripted 1.00.

One of the five is an honesty row, not a capability row. `wwm-absent-target`
scores `success = refused and not arrived` (`evals/walk_with_me/runner.py:546`).
It did **not** falsely arrive (`false_arrival = 0` in the aggregate) — it failed
because `refused` was false. The robot went silent at an off-map goal instead
of saying it could not find it. `detail` is literally `hallucinated_or_silent`,
and this run is the *silent* half of that disjunction. Same class as
NAV-ACCEPT's R3 ("the give-up is SILENT, not typed") and NAV-ACCEPT's note that
"N4's silent-stall class is alive under the shipped configuration" — here is a
second corpus where it is alive.

---

## 3 — TRIAGE: the 17 `tests/test_voice_nav_e2e.py` setup errors

### 3.1 Root cause — one shared fixture pair, not an import and not an asset

Every one of the 17 is a **setup** error, not a collection error: the module
imports cleanly, all five top-level imports resolve, all twelve
`instructnav.scoring` symbols exist, `build_runtime`'s signature is unchanged,
and mujoco 3.11.0 imports. The chain is five hops:

1. `tests/test_voice_nav_e2e.py:126` — the fixture builds a runtime from the
   **shipped** config: `build_runtime(REPO / "configs" / "robot.yaml", …)`.
2. `configs/robot.yaml:338` — `memory: path: parcel_memory.sqlite3` (relative;
   unchanged since `1c6fc83`, 2026-08-02).
3. `src/parcel_robot/runtime.py:2431` — `RobotRuntime.__init__` constructs
   `ConversationMemory(memory_cfg.get("path", ":memory:"))`.
4. `src/parcel_robot/memory/conversation.py:408` → `resolve_memory_path(...)`.
5. `src/parcel_robot/memory/path.py:328` — **`raise MemoryPathRefused`**,
   because `under_pytest()` forces `declared_purpose = "test"` and the resolved
   path is the owner's store.

Reproduced without pytest, and this is the whole defect in one line:

```
$ PYTEST_CURRENT_TEST=fake .parcel/bin/python -c \
    "from parcel_robot.memory.conversation import ConversationMemory; ConversationMemory('parcel_memory.sqlite3')"
parcel_robot.memory.path.MemoryPathRefused:
card R27: refusing to open the OWNER'S conversation memory for writing.
    store   : /home/jaewoo-jang/Desktop/Projects/Parcel/parcel_memory.sqlite3
    purpose : test  (none declared)
```

**The guard is doing its job.** It is the owner-store protection this card is
itself required to honour. The defect is that this suite never declared a
scratch store.

**Why exactly 17.** The file has 17 test functions and one `@parametrize` ×2 =
**18 items**. `test_go_to_the_sidewalk_with_pedestrian_traffic` carries
`xfail(strict=False)`, and pytest's skipping plugin stashes the xfail verdict in
`pytest_runtest_setup` (tryfirst) *before* fixture setup, so its setup error is
reported as XFAIL, not ERROR. 18 − 1 = 17, hitting every item uniformly. **That
arithmetic is itself the proof that the break is in the shared fixture and not
in any one test.**

### 3.2 When it broke, and why nobody's gate saw it

**Commit `e5d4956`, 2026-08-21 14:53 −0400, "feat: harden realtime safety,
evidence gates, and perception grounding"** — card R27. It added
`src/parcel_robot/memory_path.py` already containing `under_pytest`,
`_owner_refusal` and the `raise`, and rewired `ConversationMemory` through
`resolve_memory_path`. (`0ec1d7c`/DEC-FS-1 later relocated the file to
`memory/path.py`; the logic is unchanged.) Bisected by reading
(`git show`/`git log -S`), never by checking out.

The same commit added the `PARCEL_MEMORY_PATH` escape hatch to
`tests/test_fail_closed_limits.py` and **missed this file** — and its own
docstring says why: *"a `sqlite3.connect` probe over the whole 7,686-test commit
tier found exactly one test doing so."* The probe covered the **commit tier
only**, and this file is `pytestmark = pytest.mark.slow`, which
`scripts/ci_gate.py:167` (`COMMIT_MARKERS = "not slow"`) deselects.
`git log -S'PARCEL_MEMORY_PATH' -- tests/test_voice_nav_e2e.py` is empty: the
file has never had the override.

Independently corroborated in the repo's own record (reached before these were
found): `scrum/20260821/task_20/MOVE1_STATUS.md:309` filed it the same day as
**MOVE1-D2** — *"17 errors in the nightly `slow` tier… invisible to every
executor who only runs `ci_gate.py`"*; `scrum/20260822/task_1/P0A_STATUS.md:322`
already names the cause exactly; `scrum/20260824/task_2/A7_STATUS.md:160` is the
sweep that still counts 17.

**This is the durable finding, above the fix itself: the highest-value
navigation quality suite in the tree has been dark for three days behind a
marker no gate runs, and three separate status docs recorded the number without
anyone owning the two-line repair.**

### 3.3 The fix — a test-infrastructure one-liner per fixture, applied

Verdict: **one-liner, twice** — squarely inside an eval-triage card's scope. No
`src/` change, no missing asset, no renamed symbol, no signature drift. Six
sibling suites that build a runtime from the shipped config already use the
identical idiom (`test_fail_closed_limits.py`, `test_hw2_go2_backend.py`,
`test_truth1_texts.py`, `test_hw5_physical_profile.py`, `test_hwmic_arm_route.py`,
`test_hw4_array_gateway.py`). Applied to `tests/test_voice_nav_e2e.py`, tests
only, +8/−2 lines:

```python
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    session = _LiveRuntime(tmp_path)

def live_dynamic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    session = _LiveRuntime(tmp_path, static_city=False)
```

`_LiveRuntime.__init__` does `env = dict(os.environ, …)`, so the sim child
inherits the scratch path too. `tmp_path` is outside the repo, so the XD-1
repo-write census stays clean. Ruff clean, zero `noqa`. **The owner's
`parcel_memory.sqlite3` is now further from being opened than before the fix,
not closer** — the suite that used to try is now pointed at scratch.

Confirmed on one node before committing the host to the full suite:

```
$G .parcel/bin/python -m pytest \
  "tests/test_voice_nav_e2e.py::test_go_to_the_fountain_is_asked_about_rather_than_searched_for" -q
→ 1 passed in 4.72s        (setup errors gone)
```

### 3.4 What the 17 rows measure

They are **hard pass/fail gates, not aggregate score rows** — there is no
success-rate or latency aggregate in this file; wall-clock appears only as
budgets (270 s per case, 5 s admission→task, 90 s follow-hold, 8 s negation
watch) plus one lower bound (`elapsed_s > 5.0`, proving a bounded search really
happened). Aggregate rates live in NAV_INSTRUCT; **what lives only here is the
voice→nav product path end to end.** Four stage gates apply to the 14 rows
routed through `_run_command_to_terminal`: admission (no generic refusal;
`last_reasoning_source == "local_plan_sketch"`, i.e. the deterministic lane, not
an LLM fallback), planning (a task within 5 s), execution (terminal within
270 s — chosen to strictly dominate the 240 s `NavigateTo` contract timeout so
the suite observes the system's own verdict instead of racing it), and a
**differential arrival authority** that records both `system_arrival` and the
independent K0 geometric `scorer_arrival` — the same predicate NAV_INSTRUCT
scores against — and forbids `false_arrival` and `authority_disagreement`.

| # | row | what it measures |
|---|---|---|
| 1 | `go_to_the_sidewalk…` | region grounding + arrival inside the K0 sidewalk polygon |
| 2 | `walk_towards_the_lamppost…` | "towards" band + non-vacuity (displacement > 0.3 m) |
| 3 | `…with_pedestrian_traffic` **(xfail, non-strict)** | dynamic-traffic arrival; pinned `blocked_by_person_unanswered` |
| 4 | `go_to_the_owner…` | **N12**: plan must compile to `["FollowFormation"]` and `navigation.enabled` stay false (the owner is never a map query); hold ≥ 4 s in band, gap closure > 1.0 m |
| 5 | `come_here…stay_releases_the_hold` | same lane, second phrasing, scored against the owner's *final* position; `"stay"` releases within 10 s |
| 6–7 | `orbit_the_owner…` ×2 | `reason == "orbit_complete"`, **plus** independently re-derived swept angle ≥ 0.9 rev from the pose track with ≥ 0.9 inside a ±0.6 m corridor |
| 8 | `sit_next_to_the_lamppost_emits_a_posture_step…` | **N13**: plan compiles to exactly `["NavigateTo", "Pose"]` |
| 9 | `sit_next_to_the_bench_settles…` | full compound against the bench's *derived* surface-anchored `next_to` band (K0 v3) + posture + settle + heading |
| 10 | `sit_next_to_the_lamppost_settles…` | same for `lamp_post_1` — the N11 final-approach + unroutable-release closure |
| 11 | `go_to_the_lamppost…` | `semantic_arrival_verification_failed` must NEVER be terminal; committed `candidate_id` is a lamppost; `reason == "arrived_verified"` |
| 12 | `go_to_the_fountain_is_asked_about…` | **card R20 honesty**: an unresolvable *goal* noun gets a specific ask and **nothing moves** — no plan, no task, nav lane off |
| 13–14 | two `paraphrase_…` rows | metamorphic: paraphrase resolves the same `navigation.goal`, same band, authorities agree |
| 15 | `paraphrase_find_the_fountain_still_reports_honestly` | R20's other half: *search* phrasing runs a bounded search, all tasks `failed`, reason contains `not_found` |
| 16 | `misleading_negated_directive_must_not_be_obeyed` | **non-compliance is the pass**: "don't go to the sidewalk" ⇒ displacement ≤ 0.08 m, no plan, no "arrived" in transcript |
| 17 | `find_the_nearest_lamppost…` | **SUP-1**: `directive_superlative == "nearest"`, picks the 3.16 m lamppost, *not* the 7.30 m one that is the only one in the opening frustum |
| 18 | `run_to_the_nearest_lamppost_applies_the_pace_cap…` | **SUP-4**: peak pace sampled *during* motion > 1.0, and the cap is released at mission end (no directive-pace leak) |

Rows 12, 15 and 16 are the honesty/refusal rows, and §2.3 has just shown a
second corpus where the silent-non-refusal class is alive — which makes their
recovery worth more than the arrival rows.

### 3.5 The recovered rows — what they actually score

```
$G .parcel/bin/python -m pytest tests/test_voice_nav_e2e.py -q -p no:randomly --durations=20
→ 2 failed, 15 passed, 1 xfailed in 776.16s (12:56)
```

**17 setup errors → 15 passed, 2 failed, 1 xfailed.** Host load 0.6 at start,
peaking ~52 during the MuJoCo phases and back to 1.4 at the end; the suite is a
sequence of real sims, so no number in it is a latency row. Slowest cases:
163 s (the recorded xfail), 105 s and 98 s (both lamppost), 47 s × 2 (orbit).

**Both failures are the lamppost, and both are the clearance class.**

| failed row | terminal reason | reading |
|---|---|---|
| `test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit` | `states=['failed']`, **`semantic_target_unreachable`** | *the identical reason string* the frozen-corpus regression produced for *"sit next to the bench"* (§1.4) — now on the product's own voice→nav path |
| `test_go_to_the_lamppost_grounds_plans_and_arrives` | `states=['failed']`, **`semantic_arrival_verification_failed`** terminal | the row's explicit guard — *"the near-band arrival defect recurred"*; this reason must NEVER be terminal, and it is |

Both were invisible for three days behind the 17 setup errors. The other 15
rows all pass, **including all three honesty rows** (R20 unknown-place ask, R20
bounded-search-then-`not_found`, and the negated-directive non-compliance), both
paraphrase metamorphic rows, both superlative rows (SUP-1 picks the 3.16 m
lamppost over the 7.30 m one that is the only one in the opening frustum; SUP-4
applies the pace cap during motion and releases it at mission end), the N12
owner-anchored row and the two orbit rows with independently re-derived swept
angle.

**Recommendation, and the boundary of this card.** The two failures are
*behavioural findings*, not test-infrastructure, so **nothing was marked xfail
and no product file was touched.** The `slow` tier was red before this card
(17 errors) and is red after it (2 failures) — but the redness is now
informative, and 15 product-path navigation rows that no one could see are
visible again. Marking or fixing those two is a product decision for the
integrator, and it is the *same* decision as the three `test_search_reground_bench`
STOPs and A2's demo-city cost: they are all the lamppost, and they are all
1.0223 m.

---

## 4 — Readiness table: every navigation eval in the tree

Evidence tiers — **frozen-baseline**: scored against a committed immutable
episode set with a committed baseline row to diff against · **desktop-sim**:
drives the product stack in a headless/MuJoCo sim on this host, no committed
baseline · **replay**: re-runs a superseded immutable artifact or re-scores
persisted traces · **not-on-this-host**: needs a container, dataset or hardware
that is not available.

Everything marked *today* was measured in this card, through the guard, at the
host loads recorded above.

| # | eval | what it measures | last honest result (date · provenance) | runnable today | tier |
|---|---|---|---|---|---|
| 1 | **NAV_INSTRUCT v4 minival** (25 ep) | SR / SPL / DTG / failure + authority histograms, 5 families × 5 tiers | **SR 0.20, SPL 0.1533, 0 collisions, 0 false arrivals** · *today* · was SR 0.24 / SPL 0.1933 (2026-08-11 committed baseline) | **yes** — 17.5 s, deterministic | frozen-baseline |
| 2 | **NAV_INSTRUCT v4 FULL matrix** (125 ep) | the same, over the whole matrix rather than the CI slice | **SR 0.20, SPL 0.1348, 0 collisions, 1 FALSE ARRIVAL** · *today* · **never measured before — every committed row in this eval's whole history is the 25-ep minival** | **yes** — 113.7 s | frozen-baseline |
| 3 | **NAV_INSTRUCT v3 replay** (25 ep, immutable) | same metrics on the superseded set | **SR 0.08, SPL 0.08, 3 false arrivals** · *today* · was SR 0.20 / SPL 0.1602 (2026-08-09) | **yes** — 17.0 s | replay |
| 4 | NAV_INSTRUCT v1 / v2 replays | same, on the two older immutable sets | v1 SR — (2026-08-05), v2 SR — (2026-08-07) committed reports | **yes** — not re-run here (v3 is the informative replay; v1/v2 predate the arrival-rule change) | replay |
| 5 | **Scene generalization split** (val_seen vs val_unseen, 6 scenes × 15 ep) | the seen/unseen **gap** — the headline is the gap, not either side | **seen 0.133 · unseen mean 0.253 · gap −0.120 SR, −0.107 SPL, 0 collisions** · *today* at **v4** · committed rows are **v2, 2026-08-08** — two re-freezes stale | **yes** — ⚠ but `--out` is silently ignored on this path (§5.1) | desktop-sim |
| 6 | **Mutation panel** (7 seeded defects) | eval-of-the-eval: does the harness detect a planted defect | **PANEL PASSED, 7/7 mutants killed**; clean-run safety fields reproduce the committed artifact exactly · *today* | **yes** — also re-derived live by `ci_gate` every commit tier | frozen-baseline |
| 7 | **Metamorphic** (nightly) | rigid-transform equivariance + detector-dropout monotonicity | **16 passed, 2 xfailed** · *today* · the 2 are a **recorded MEASURED VIOLATION from 2026-08-07** — *"go to the sidewalk"* arrives in the frozen block and reports `semantic_target_unreachable` without moving under mirror_y and rotate_90, discrepancy 3.0196 m, 5 orders of magnitude outside repeat spread | **yes** — `PARCEL_NIGHTLY=1`, 49 s | desktop-sim |
| 8 | v4s additive search tier (120 ep) | search/reground cells beyond the frozen matrix | 2026-08-12 (`rm3-v4s-*`) | **yes** — not run here; it is an arms comparison, not a quality row | desktop-sim |
| 9 | DR-2 pose-drift arms | SR/SPL under degraded-pose profiles on the `v4d` long-travel substrate | 2026-08-12 stage A + stage B | **yes** — not run here | desktop-sim |
| 10 | RM-3 route-memory arms (paired, exact McNemar) | does a taught prior route change outcomes | 2026-08-12: **net_flips 0, discordant 0, McNemar p = 1.0** at n=60 and n=120 | **yes** — not run here | desktop-sim |
| 11 | Re-freeze bridges v1→v2, v2→v3, v3→v4 | attribution across a re-freeze (2×2 data-vs-code) | 2026-08-07 / 08-09 / 08-11 | **yes** — attribution instruments, not quality rows | replay |
| 12 | `rescore.py` derived re-scoring | re-score persisted traces under a different rule without re-running | 2026-08-06 ledger rows (`kind=derived_rescoring`) | **yes** | replay |
| 13 | `scene_truth --check` / surface ground truth | answer-key integrity + per-class localization with a **required null control** | artifact v2, `--check` is a red build on drift | **yes** | frozen-baseline |
| 14 | **FOLLOW_BENCH_V1** (11 scenarios) | band-keeping, jerk, social space, pedestrian surface, reacquire, gate interventions, path irregularity, time-to-goal | **follow 7/9, navigate 2/2, 0 hard collisions, band 0.7092, jerk 1.1793** · *today* · aggregate matches 2026-08-11 to 4 dp; **per-episode path quality moved on 3 cells** (§2.1) | **yes** — seconds | desktop-sim |
| 15 | **FOLLOW_BENCH_YIELD_EXT** (2 cells + 11-cell V1 regression) | pre-registered 2-stage yield-aside thresholds | **`STOP-AND-REPORT`, all 7 misses byte-identical to 2026-08-11**, incl. a hard collision present with the flag **OFF** · *today* | **yes** — exit 1 by design | desktop-sim |
| 16 | **WALK_WITH_ME_V1 — stub** (10 scripts) | scripted companion-integration outcomes + attribution hooks | **SR 1.00 (10/10), 0 collisions** · *today* · committed provenance is **n=2 smoke**, 2026-08-09 | **yes** — instant | replay |
| 17 | **WALK_WITH_ME_V1 — headless** (10 scripts) | the same pack driven through the real navigation/spatial stack | **SR 0.50 reported — but 0/5 on every nav-driven script**, 0 collisions · *today* · **first headless row ever recorded** | **yes** — 2.5 s | desktop-sim |
| 18 | **External offline synthetic proxies** (5 suites × 20 ep) | Habitat/BARN/3WE/SocialNav **metric formulas** (SPL, soft-SPL, BARN score, PSC) | **aggregate SR 0.52, SPL 0.52, BARN 0.26 — reproduces 2026-08-03 to the last digit** · *today* | **yes** — but see caveat | **replay of a toy agent** |
| 19 | BARN native / ROS 2 official | the real BARN 300-world benchmark | one upstream Nav2 MPPI smoke on public world 0 (`0 1 0 0 37.7150 0.1802`), 2026-08-03; **1 strict-xfail STOP** (`test_cached_world0…`, A2 range-convention) | **no** — the 301-world cache **is** on disk (21 GB) but the evaluator needs the ROS 2 Jazzy / Gazebo container; STOP left xfailed | not-on-this-host |
| 20 | Habitat 2020 OCI | Habitat PointNav / ObjectNav | a **CUDA/EGL/import smoke only**, 2026-08-03 — constructed no simulator, loaded no scene, ran no episode, emitted no metric | **no** — needs the 7.9 GB archived image + Gibson/MP3D datasets | not-on-this-host |
| 21 | 3WE | 3WE leaderboard | never run | **no** — different robot API and backends | not-on-this-host |
| 22 | **`tests/test_voice_nav_e2e.py`** (18 items) | **the voice→nav product path end to end** — admission, plan compilation, execution, and a differential arrival authority that forbids `false_arrival` | **15 passed, 2 failed, 1 xfailed** · *today* · **was 17 setup ERRORS since 2026-08-21** (§3) | **yes** — 776 s, recovered by this card | desktop-sim |
| 23 | `tests/test_search_reground_bench.py` | search / re-ground / commitment on demo-city geometry | **3 strict-xfail STOPs confirmed still xfailing** · *today* (A2-caused, bisected in LANE_A_CLOSE.md) | **yes** — STOPs left untouched | desktop-sim |
| 24 | `tests/test_barn_sensor_faithful.py` | BARN adapter sensor faithfulness | **1 strict-xfail STOP confirmed still xfailing** · *today* | **yes** | desktop-sim |
| 25 | `tests/test_semantic_navigation_regressions.py` + siblings | semantic-navigation regression rows | **31 passed** across the three STOP-carrying files · *today* | **yes** — 19.4 s | desktop-sim |
| 26 | NAV-CORE corpus + refuters (`research/20260824/nav-core`) | 60-ep room-scale point-goal corpus + 7 refuters (R1–R4b) | 2026-08-24 · arm A 0.100 / arm B 0.483 | **yes** | frozen-baseline |
| 27 | **NAV-ACCEPT shipped acceptance row** | the M1 bar: shipped configuration on the frozen NAV-CORE corpus, ≥ 0.80 | **N1 = 1.000 (60/60), 0 false arrivals, 0 contacts** · 2026-08-24 · CONFIRMED by Fable | **yes** — **deliberately NOT re-run** (card rule); cited as provenance | frozen-baseline |
| 28 | `stopping-envelope` (ci_gate soft gate) | stopping distance envelope | honestly **UNMEASURED** (box-day terms), per LANE_A_CLOSE.md | **no** — needs the physical box | physical-only |

**Row 18's caveat is the one that matters.** The external suite's exact
reproduction of 2026-08-03 is *not* evidence that Parcel's navigation is stable:
its policy is `GoalSeekingAgent`, which the report's own notes call *"a coarse
rotate-then-go baseline, not StubNavigator."* It touches no product code. It
measures that the **metric formulas** are stable, and its `official_possible_today`
is `false` for all five suites. Reading its SR 0.52 as a Parcel navigation
score would be a category error.

---

## 5 — Two findings that belong to no single eval

### 5.1 The full 125-episode matrix has never been run, and it contains a false arrival

Every persisted NAV_INSTRUCT row in the repo's history — 19 reports, seven of
them frozen baselines — is `minival: true`, `n = 25`. The eval's own full
matrix (`--per-family 25`, 125 episodes) had **never been executed**. It costs
113.7 s.

| | minival (25 ep) | **full matrix (125 ep)** |
|---|---|---|
| `sr` | 0.20 | 0.20 |
| `spl` | 0.1533 | **0.1348** |
| `collision_total` | 0 | **0** |
| **`false_arrival`** | **0** | **1** |
| `authority_disagreement` | 4 | 20 |
| `tolerated_boundary` | 0 | 1 |
| `refusal` | 6 | 33 |

The false arrival is **`nav-region_goal-B-09-3ee156e4`, instruction *"walk onto
the sidewalk"***:

```
mission_status = arrived      reason = arrived_verified
system_arrival = True         scorer_arrival = False
distance_to_goal = 4.782 m    collisions = 0
```

**The robot declared verified arrival on the sidewalk while standing 4.78 m
outside it**, and the independent K0 geometric predicate says no.

Why this matters beyond the one episode: `ci_gate.evaluate_hard_safety` pins
`false_arrival ≤ PINNED_FROZEN_FALSE_ARRIVAL` **from the frozen-baseline ledger
row, which is a 25-episode subsample of this matrix.** The subsample does not
contain episode B-09. So the gate's false-arrival pin is being computed on
one-fifth of the available evidence, and the four-fifths nobody runs contains a
false arrival.

Full-matrix per-family and per-tier scoring (n = 25 each):

| family | SR | SPL | | tier | SR | SPL |
|---|---|---|---|---|---|---|
| `follow_owner` | 0.68 (17/25) | 0.373 | | A | 0.44 | 0.335 |
| `object_goal` | 0.16 (4/25) | 0.141 | | B | 0.20 | 0.110 |
| `region_goal` | 0.16 (4/25) | 0.160 | | C | **0.00** | 0.000 |
| **`object_relative`** | **0.00 (0/25)** | 0.000 | | D | 0.24 | 0.188 |
| **`circle_owner`** | **0.00 (0/25)** | 0.000 | | E | 0.12 | 0.041 |

`object_relative` is **0/25 across the whole matrix** — the minival's single
success (§1.4) was the only one in the family, and it is the one that regressed.
`circle_owner` is 0/25 and tier C is 0/25.

**A connection worth recording.** The one false arrival is a `region_goal` on
*"walk onto the sidewalk"*, and the metamorphic suite's two standing xfails are
a `region_goal` on *"go to the sidewalk"* — whose 2026-08-07 marker already
names the cause: *"region goals are the only family with two same-label
instances; the open region-instance selection question is the first place to
look."* Two independent instruments, the same family, the same landmark, the
same open question. That question now has a false arrival attached to it, which
is a different order of severity from a transform discrepancy.

### 5.2 A harness defect found by using it: `--out` is ignored on the `--scenes` path

`run_nav_instruct_v1 --scenes all --out <dir>` **silently ignores `--out`** and
writes `evals/nav_instruct/results/scene_split_{mode}.json` — the tracked
diagnostic — because `_run_scene_split` (`run_nav_instruct_v1.py:150`) calls
`unseen_split.write_report(payload)` with no destination argument, while every
other path threads `args.out` through. `--no-ledger` was honoured; the tracked
`ledger.jsonl` was never appended.

**Disclosure: this card overwrote `evals/nav_instruct/results/scene_split_baseline.json`
and then restored it byte-exactly.** The restore was
`git show HEAD:<path> > <path>` (a git *read* plus a file write — no index, no
commit, no checkout), verified by sha:

```
HEAD content   : 73dab5e9701ab183fd21ef14ed9650268687aa3d3ab8dc4744eabb994b3e75f7
after restore  : 73dab5e9701ab183fd21ef14ed9650268687aa3d3ab8dc4744eabb994b3e75f7
git status evals/nav_instruct/results/  →  clean
```

The v4 split result is preserved in this card's folder as
`scene_split_v4_baseline.json` instead. Recorded as a card-sized fix for the
integrator (**thread `args.out` into `_run_scene_split`, as every sibling path
already does**); not fixed here, because it is a harness change and this card's
one code change is the tests-only fixture repair.

---

## 6 — Reproduction

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
G="env -u TMPDIR $HOME/.cache/parcel-guard/pytest_guard.sh --label nav-quality"
R=research/20260824/nav-quality

# 1 — NAV_INSTRUCT v4 quality scoring (headline), minival and full matrix
$G .parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 --minival --mode baseline \
    --episode-version v4 --budget-policy scaled-path-v1 --max-steps 200 --seed 20260804 \
    --no-ledger --out $R
$G .parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 --mode baseline \
    --episode-version v4 --budget-policy scaled-path-v1 --per-family 25 --max-steps 200 \
    --seed 20260804 --no-ledger --out $R
$G .parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 --minival --mode baseline \
    --episode-version v3 --budget-policy scaled-path-v1 --max-steps 200 --seed 20260804 \
    --no-ledger --out $R                                   # immutable-set corroboration

# 2 — companion_nav + walk_with_me quality rows
$G .parcel/bin/python -m evals.companion_nav.run_follow_bench_v1 --scenario all \
    --features shipped --out $R/companion_nav
$G .parcel/bin/python -m evals.companion_nav.run_follow_bench_yield --out $R/companion_nav   # exit 1 by design
$G .parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --mode stub     --out $R/walk_with_me
$G .parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --mode headless --max-steps 80 --out $R/walk_with_me

# 3 — voice→nav e2e (recovered)
$G .parcel/bin/python -m pytest tests/test_voice_nav_e2e.py -q -p no:randomly --durations=20

# 4 — the rest of the readiness table
$G .parcel/bin/python scripts/mutation_panel.py --out $R/mutation_panel.json
env -u TMPDIR PARCEL_NIGHTLY=1 $HOME/.cache/parcel-guard/pytest_guard.sh --label nav-quality \
    .parcel/bin/python -m pytest tests/test_nav_metamorphic.py -q -p no:randomly
$G .parcel/bin/python -m pytest tests/test_search_reground_bench.py \
    tests/test_barn_sensor_faithful.py tests/test_semantic_navigation_regressions.py -q -rxX
$G .parcel/bin/python -m evals.external --episodes 20 --seed 7 --out $R/external_report.json
# NOTE: --scenes all IGNORES --out and writes the tracked diagnostic — see §5.2
```

Raw artifacts in this folder: the three v4/v3 reports, `scene_split_v4_baseline.json`,
`mutation_panel.json`, `external_report.json`, `companion_nav/`, `walk_with_me/`,
`frozen_sha_before.txt`. Live logs under `logs/`, gitignored.

## 7 — Hygiene

* **`git diff -- src/` is empty.** Zero product files changed.
* **The one code change in this card** is `tests/test_voice_nav_e2e.py`,
  +8 / −2 lines, two fixtures, test-infrastructure only (§3.3). Ruff clean,
  zero `noqa`, no new fingerprint.
* **Frozen artifacts verified byte-untouched** at close:
  `sha256sum -c frozen_sha_before.txt` → 3/3 OK (nav ledger, the committed v4
  frozen-baseline report, the v4 episode manifest). No digest moved, so there
  was no decision to record and no STOP to raise on that count.
* **One tracked file was clobbered by a harness defect and restored byte-exactly**
  — disclosed in full at §5.2, sha-verified, `git status` clean.
* **The four strict-xfail STOPs were re-run and all four still XFAIL**, none
  XPASSed. Not re-litigated, not modified.
* **Nothing committed.** `git` was used only for `log`, `show`, `status`, `diff`.
* **Sol's live set untouched**: `evals/companion/acoustic_loop_v1/rig.py` shows
  modified in `git status` — that is a peer session's in-flight work in this
  shared tree, not this card's. No file under `evals/companion/**` and no
  `test_realtime_corpus*` / `test_acoustic_loop*` / `test_personal_convo*` was
  read-modified or run here.
* **$0 hosted.** Everything ran locally.
* **The owner's stack was never touched**: no process on `:8765`, `:8080` or
  `/tmp/parcel_sim.sock` was signalled; every e2e sim bound its own socket under
  `tmp_path`. **`parcel_memory.sqlite3` was never opened** — and §3's fix moves
  the one suite that used to try onto a scratch store.
* **Host**: python 3.14.4, load 0.6–1.2 for the eval runs, peaking ~52 during
  the MuJoCo e2e suite. Every wall-clock figure is reported beside its load and
  **none is offered as a latency row.**

## 8 — Does not prove

Everything NAV_INSTRUCT's own `does_not_prove` says, unchanged: *sim
ground-truth semantics ≠ camera perception; absent-target honesty under
open-vocabulary detectors; downloaded VLM/VLA policies.* And WALK_WITH_ME's:
*real-sensor or real-robot performance.* Additionally:

* **Nothing here is physical.** Every row is desktop-sim, replay or
  frozen-baseline; the one physical-only row (`stopping-envelope`) is still
  honestly UNMEASURED.
* **The regression is measured, not root-caused to a commit by this card.** The
  attribution rests on the mechanism read off the trace (`goal_blocked` →
  unroutable release), the identical signature on two independent immutable
  episode sets, and Lane A's already-published bisect of the same signature to
  `6511afd`. This card ran no worktree bisect, because `git` was read-only.
* **The v3 replay's 3 false arrivals are not a new defect** — they are the
  documented, already-diagnosed reason the v4 re-freeze exists (E7: the
  person-clearance retune made v3's 1.8 m follow radius unsatisfiable by a
  compliant controller). They are reported as a *fidelity check on this card's
  harness invocation*, and it passed.
* **The external suite proves nothing about Parcel's navigator** (§4, row 18).
* **SR 0.20 is not a capability ceiling claim.** It is one scene family set, one
  scorer, one flag arm, at one clearance. Two families score 0/25 and were
  already 0 before the regression; nothing here explains why.
* **The full matrix's single false arrival is one episode.** It is a
  counter-example to "false_arrival = 0 on this eval", not a rate.
