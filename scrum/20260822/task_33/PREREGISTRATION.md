# ROAM-2 — PREREGISTRATION

**Card:** `README.md` · **Design:** `DESIGN.md` · **Board:** `../TASK_BOARD.md`
**Executor:** Claude Opus (third real attempt) · **Verifier:** Fable
**HEAD:** `e15e466` · **Written:** 2026-08-23 06:2x EDT

**This file is written BEFORE any measurement run of either arm.** Rows are
measured exactly as written below. A row that is missed is reported as missed;
no row is re-cut after a number is seen. Two predecessors died before writing
it, so the ordering is stated explicitly: the definitions and the arms are
fixed here, then the **baseline arm runs and its numbers are appended to §6 of
THIS file**, and only then does the coverage arm run.

---

## 1. What "coverage" means, exactly

The card's words: *"distinct map entries seen (within the learned map's own
visibility rule) / entries known at start"*. Made operational:

> **C1 (the headline metric).** Let `S` be the set of entries in the learned
> map **as it exists at the moment the run starts** (`active_entries()` of the
> store reloaded by P1-B's `reload_on_start`). Let `P` be the robot's sampled
> path over the 120 s roam. An entry `e ∈ S` is **covered** iff
> `_was_expected_visible(e, P)` — i.e. **some sample of `P` lies within the
> map's own `visibility_range_m` of `(e.surface_x, e.surface_y)`**. Then
>
> **C1 = |covered| / |S|**, reported as a fraction and as `k / N`.

`_was_expected_visible` is **the map's own rule**, not a re-implementation:
`online_map.py:771`, the same predicate `close_visit` decays entries against,
and the same `distance <= self._visibility_range_m` test
`coverage_candidates` reports as `within_visibility`. `visibility_range_m` is
`DEFAULT_VISIBILITY_RANGE_M = 8.0` (`online_map.py:99`) and is recorded in
every run's `summary.json`.

**It reads P1-B's learned map, never sim ground truth.** `S` comes from the
persisted online-map store; the scene sidecar, `extract_city_semantics` and
every MuJoCo oracle read are unused by this metric. That is what makes the
number transfer to a D455/Go2 venue unchanged (DESIGN §e).

**C2 (secondary, DIAGNOSTIC ONLY, never a substitute for C1).** The same
computation restricted to `S_far = {e ∈ S : e is NOT within visibility_range_m
of the run's FIRST sample}` — the places the run actually had to travel to.
**C2 = |covered ∩ S_far| / |S_far|**. C2 is reported beside C1 in every row.
**No pass/fail row is gated on C2.** It exists because C1 carries a ceiling
(see §5) and the verifier is entitled to see whether a C1 miss is a behaviour
result or an arithmetic one.

### What C1 deliberately does NOT reward

Discovering a place that was never in `S`. A run that learns ten new entries
scores no better for it — the denominator is fixed at the start. This is the
card's definition and it is kept; DESIGN §g risk 2 says the same.

---

## 2. The two arms — one config line apart

Both arms are **the same product path**: `submit_realtime_transcript("Go
explore.")` into the runtime's own loop, watched through `snapshot()` /
`roam_snapshot()`. **No harness constructs a `PatrolPolicy`, a `PatrolRunner`
or a `PatrolSense`.** The driver is `evidence/run_roam2.py`, modelled on
ROAM-1's `../task_23/evidence/run_roam1.py` (which is the same "say it and
only WATCH" instrument), and it contributes nothing but the stopwatch and the
post-hoc geometry.

| | arm A — **BASELINE (ROAM-1 tethered)** | arm B — **COVERAGE** |
|---|---|---|
| config | `roam: {coverage: false}` | `roam: {coverage: true}` |
| everything else | identical | identical |

`coverage: false` is **the shipped default** (`PatrolLimits.coverage_bias =
False`, `limits_from_safety(coverage_bias=False)`, `overrides.get("coverage",
False)`) and arm A therefore also stands as the **flag-off byte-identity**
check: with the flag off, `PatrolPolicy._cruise_or_cover` returns
`PatrolCommand(vx=cruise_vx, reason="advance")` on its first branch and the
policy is ROAM-1's. MOVE-1's and ROAM-1's unit baselines
(`tests/test_move1_patrol.py`, `tests/test_roam1_behavior.py`) are **not
edited by this card** and are re-run green as row R6.

**Common conditions, fixed here:**

* scene `city_block`, `--static-city`, budget **120 s**, sample 4 Hz —
  ROAM-1's and FINISH-1's conditions verbatim.
* `safety.person_stop_m: 0.7` (the prototype's social zone, P1-E) — FINISH-1's
  seven-run condition.
* tether **ON at 10.0 m** (`DEFAULT_ROAM_TETHER_M`).
* `navigation.config: configs/navigation/prototype.yaml` —
  **`semantic_source: learned_map`**. This is a CONDITION OF THE NUMBER, not a
  detail: under the shipping `oracle` source the runtime constructs no learned
  map at all, `_roam_coverage_objective` returns `{}` for every tick, and this
  card is inert (DESIGN §g risk 4).
* `PARCEL_ONLINE_MAP_PATH` = an absolute path under
  `~/.cache/parcel-roam2/` — never the owner's `parcel_memory.sqlite3`, never
  a repo path.
* unique short socket under `~/.cache/parcel-roam2/`; ledger redirected
  (nothing appended to `evals/nav_instruct/results/ledger.jsonl`);
  `duplex.log_dir` outside the repo.

### The seed map — why there is a warm-up, and why it is not a third arm

C1's denominator must exist before the run starts, and a cold store is empty
(`|S| = 0`, C1 undefined). So:

1. **One warm-up run** (120 s, **coverage OFF**, i.e. plain ROAM-1) writes a
   store. It is **not** a measured run and its numbers are reported in §6 as
   context only.
2. That store is frozen as **`seed_map.sqlite3`**, its **sha256 recorded in
   §6 before any measured run**, and **copied fresh into every one of the six
   measured runs**. Every measured run therefore starts from a
   byte-identical map, and `|S|` is the same integer in both arms.
3. The warm-up is coverage-OFF so the seed map cannot be biased toward arm B.

If the warm-up store ends with `|S| < 5` the measurement is **NOT MEASURED**
and reported as such with the store's contents — five entries is the floor at
which a ratio out of `|S|` is worth printing. (Registered now, not after.)

#### DEVIATION D1 — the warm-up is THREE untethered runs, not one tethered run

**Recorded 2026-08-23 06:4x, after the warm-up run and BEFORE any measured run
of either arm. No measured number had been seen when this was written.**

The single tethered warm-up ran (124.5 s, escape branch, 6.50 m net in-block,
0 contacts) and produced a store of **57 active entries** — and probing it
showed **55 of the 57 lie within `visibility_range_m` (8.0 m) of the start
pose**, i.e. `|S_far| = 2`. C1 is therefore ≈ 0.96 **at the first sample of any
run**, in either arm, before the robot has moved. The metric would have been
saturated and would have measured nothing about either behaviour — the §5
ceiling, reached not by the behaviour being good but by the seed map being
tiny and local.

The cause is geometric and worth writing down: entries are grounded near the
robot, a tethered 120 s roam covers ~26 m of path within ~10 m of home, so
*everything it learns is already inside the 8 m visibility of home*.

**What changes:** the warm-up becomes **three 120 s runs, coverage OFF and
`tether_m: null` (unbounded)**, accumulating into ONE store through P1-B's own
`reload_on_start`. That is a dog that has been on longer outings before —
which is the only setting in which "go and look at what you have not seen
lately" can differ from "wander".

**What does NOT change, and this is the point:** the metric C1, the rule
(`_was_expected_visible`), the target (≥ 1.5 × baseline), the two arms, and
every condition of the MEASURED runs — both arms stay **tethered at 10.0 m**,
120 s, `--static-city`, `person_stop 0.7`, and both start from the SAME frozen
seed map. The warm-up is a condition of the denominator, is coverage-OFF, and
therefore cannot favour either arm. §5's ceiling rule still stands verbatim: if
median C1(A) still exceeds 0.667, T1 is reported **MISSED — CEILING**.

The first warm-up's store (sha256
`70112d1d4e9a6af67681d9ff5ae5a3df4b3b4e9248db8ef80ed1519531589037`, 57
entries) is kept as evidence of why this deviation exists.

---

## 3. Rows

Measured rows. **T1 is the card's target row.** Three runs per arm, and
**every run that starts is reported**, including a crashed one.

| row | claim | threshold | how read |
|---|---|---|---|
| **T1** | coverage rises | **median C1 (arm B, 3 runs) ≥ 1.5 × median C1 (arm A, 3 runs)** | §6 tables |
| **T1′** | …and not only on medians | **min C1 (arm B) ≥ 1.5 × max C1 (arm A)** | §6; see §4 |
| **T2** | no contacts | **contacts == 0 in 6/6 runs** | `collision_ticks` |
| **T3** | the zone is respected | **min person clearance ≥ 0.7 m in 6/6** | `min_person_clearance_m` |
| **T4** | in-block | **`in_bounds` true in 6/6** (\|x\|,\|y\| ≤ 12 m) | ROAM-1's qualifier verbatim |
| **T5** | the roam still ends itself | **`roam.active` false at budget end, 6/6** | `roam_final` |
| **T6** | legs are real and countable | **arm B: `roam.coverage.legs` ≥ 1 in ≥ 2 of 3 runs; arm A: legs == 0 in 3/3** | `roam_snapshot()["coverage"]` |
| **R6** | flag-off changes nothing | **`test_move1_patrol.py` + `test_roam1_behavior.py` green, unedited by this card** | `git diff --stat` empty for both |
| **R7** | the guards hold | **`tests/test_roam2_coverage.py` green**; seeds S1–S4 RED then green | §5 of the status doc |

**Reported, not gated** (the card says so): ROAM-1's distance rows beside the
coverage number (path length, net raw, **net in-block**), the reason
histogram, and a **second arm in the dynamic city** if time allows.

---

## 4. The input is BIMODAL — and T1′ is why

FINISH-1 measured **seven** tethered 120 s product-path runs and got two
modes, not one number with noise:

> **1.30 · 3.10** m net in-block (*boxed* branch, 2/7 — the budget spent on
> blocked lanes near home, `turn_hold` 61–98 samples) and
> **6.48 · 6.47 · 6.54 · 6.56 · 6.57** m (*escape* branch, 5/7, pairwise
> separation ≤ 0.34 m, first `turn_tether` at 77.4–78.4 s).
> *"Which branch a run takes is timing- and load-sensitive, not a setting."*

Three runs can therefore land 3/3 in either mode by luck. Guards registered
now:

1. **All three runs of each arm are printed individually.** No arm is ever
   summarised by one number alone.
2. **T1 is on MEDIANS** of three — the statistic a 2-of-7 minority mode cannot
   move by itself.
3. **T1′ (min-B ≥ 1.5 × max-A)** is the bimodality-proof row. If **T1 passes
   and T1′ fails**, the headline of `ROAM2_STATUS.md` must say in words that
   the pass rests on medians over a bimodal input and is not a separation of
   the distributions.
4. **Every run is branch-labelled** in §6 from its own trace — `turn_hold`
   sample count and the time of the first `turn_tether` — so an arm whose
   three runs are all *escape* against an arm that is all *boxed* is visible
   as a confound rather than hidden inside a ratio.
5. If the two arms differ in branch composition (e.g. A = 3 boxed, B = 3
   escape), **T1 is reported CONFOUNDED** whatever its arithmetic, and the
   status doc says the comparison did not isolate the flag.

Note that C1 is a coverage fraction, not a distance, so it need not inherit
the distance metric's modes — but it is measured on the same trajectories, so
the guards apply until the data says otherwise.

---

## 5. The ceiling on C1, registered before it is seen

C1 ≤ 1.0 by construction, so **T1 is arithmetically unreachable whenever
median C1(arm A) > 2/3**. This is registered now so that it cannot become an
excuse later:

* If **median C1(A) > 0.667**, T1 is reported **MISSED — CEILING**, with the
  exact baseline number, and the status doc states plainly that the target as
  written could not be met by any behaviour. It is **not** re-cut, and C2 is
  **not** substituted for it.
* C2 is reported in the same table so the verifier can see whether the
  behaviour moved on the entries that had headroom.
* No other contingency is claimed. If C1 has headroom and T1 misses, T1 is a
  plain MISS.

---

## 6. Registered numbers

### 6.1 Seed map (filled BEFORE any measured run)

**Filled 2026-08-23 06:48, before the first measured run.**

| item | value |
|---|---|
| warm-up runs (D1) | `~/.cache/parcel-roam2/runs/warm{1,2,3}` — 3 × 120 s, coverage OFF, `tether_m: null`, accumulated into one store |
| frozen seed | `~/.cache/parcel-roam2/seed_map_final.sqlite3` |
| seed sha256 | `46d3c465b0ae39a128a0990417524aff45a2dccf35de0b1c542b952d74119f0a` |
| `\|S\|` (entries known at start) | **50** (≥ 5, so the §2 floor is met) |
| `\|S_far\|` (entries outside visibility of the start pose) | **0** |
| `visibility_range_m` | **8.0** (`DEFAULT_VISIBILITY_RANGE_M`) |
| max entry distance from home | **7.1 m** |

### 6.1a THE CEILING IS REACHED BEFORE THE FIRST MEASURED RUN — registered now

Every one of the 50 entries lies **within 7.1 m of the start pose**, and the
map's own visibility rule is **8.0 m**. Therefore `_was_expected_visible` is
true for all 50 at the run's FIRST SAMPLE, and

> **C1 = 1.0 for every run of BOTH arms, before the robot has moved.**

By §5 this makes **T1 `MISSED — CEILING`** and it is recorded here **before
either arm was measured**, so it is a property of the scene and the metric, not
a result read off the data. `|S_far| = 0` also makes **C2 undefined** — there
is no entry the run had to travel to.

Deviation D1 was applied precisely to avoid this and **did not fix it**: the
untethered warm-up runs reached **20.6 m from home** (their *net in-block*
number, 12.0 m, is clipped at the 12 m half-extent — corrected here per the
verifier's F15), and the map still learned nothing beyond 7.1 m. The learned map in `city_block` is intrinsically
local — the detector grounds the buildings, windows, storefronts, lampposts and
trees immediately around home and grounds nothing new further out (entry counts
across the three accumulating warm-ups: 43 → 49 → 50).

**Both arms are still measured, all six runs, all rows.** T1 is reported as the
ceiling miss it is; T2–T6 and the distance rows are unaffected and **T6 — the
row that asks whether the objective actually engaged on the product path — is
the one that carries this card's behavioural claim.** No metric is substituted
for C1 and no row is re-cut.

### 6.2 Arm A — BASELINE, `roam: {coverage: false}` (filled BEFORE arm B runs)

**Measured 2026-08-23 06:48–06:54, BEFORE any arm-B run.**

| run | C1 (k/N) | C2 | branch | path (m) | net in-block (m) | in_bounds | contacts | min clearance (m) | legs |
|---|---|---|---|---|---|---|---|---|---|
| A1 | **1.0** (50/50) | undefined (\|S_far\|=0) | escape (holds 7, tether@ 77.664) | 26.147 | 6.511 | true | 0 | 1.128 | 0 |
| A2 | **1.0** (50/50) | undefined (\|S_far\|=0) | unclassified (holds 30, tether@ —) | 21.893 | 3.969 | true | 0 | 1.148 | 0 |
| A3 | **1.0** (50/50) | undefined (\|S_far\|=0) | boxed (holds 56, tether@ —) | 19.480 | 3.612 | true | 0 | 1.110 | 0 |

**median C1(A) = 1.0** · **max C1(A) = 1.0** ·
**T1 threshold = 1.5 × 1.0 = 1.5** · **T1′ threshold = 1.5 × 1.0 = 1.5**

**Both thresholds exceed the metric's maximum, so T1 and T1′ are `MISSED —
CEILING` by §5 — as §6.1a registered before either arm ran.** The three
baseline runs confirm the ceiling empirically rather than by argument: all 50
entries are covered in every run, and 50/50 was already true at sample 0.

**Bimodality confirmed on the distance rows (§4), and wider than FINISH-1's:**
A1 is the *escape* branch (6.51 m net, `turn_hold` 7, first `turn_tether`
77.66 s — inside FINISH-1's 77.4–78.4 s window and within 0.06 m of its 6.47–6.57
cluster); A3 is *boxed* (3.61 m, `turn_hold` 56, tether never reached); A2 sits
between the two (3.97 m, `turn_hold` 30) and is left **unclassified** rather
than forced into a branch. This is why §4 exists and why no arm is summarised
by one number.

### 6.3 Arm B — COVERAGE, `roam: {coverage: true}` (filled after arm B runs)

**Measured 2026-08-23 06:55–07:01.**

| run | C1 (k/N) | C2 | branch | path (m) | net in-block (m) | in_bounds | contacts | min clearance (m) | legs |
|---|---|---|---|---|---|---|---|---|---|
| B1 | **1.0** (50/50) | undefined (\|S_far\|=0) | unclassified (holds 17) | 18.752 | 1.409 | true | 0 | 1.108 | **7** |
| B2 | **1.0** (50/50) | undefined (\|S_far\|=0) | unclassified (holds 3) | 20.031 | 1.562 | true | 0 | 1.113 | **8** |
| B3 | **1.0** (50/50) | undefined (\|S_far\|=0) | unclassified (holds 26) | 17.855 | 1.790 | true | 0 | 1.131 | **7** |

**median C1(B) = 1.0** against a T1 threshold of **1.5** → **T1 MISSED —
CEILING**; **T1′ MISSED — CEILING**. Both were registered as unreachable in
§6.1a before either arm ran.

**T6 MET, and it is the row that carries the behavioural claim.** Arm B counted
**7, 8 and 7** coverage legs; arm A counted **0, 0, 0**. The product-path
reason histogram is the same statement from the runtime's own snapshot: arm B
shows `turn_coverage` 95/89/83 and `advance_coverage` 16/22/21 samples, and arm
A shows neither reason at all. Per-sample `coverage.enabled` was true in
**467/468, 468/468, 467/468** arm-B samples and in **0/468 in every arm-A run**
— the flag-off arm never turned the objective on, and never asked the map.

### 6.4 THE FINDING THIS CARD ACTUALLY PRODUCED (reported, not gated)

**Net displacement COLLAPSED in the coverage arm: 1.41 / 1.56 / 1.79 m against
the baseline's 6.51 / 3.97 / 3.61 m.** Path length fell too (18.8 / 20.0 / 17.9
against 26.1 / 21.9 / 19.5). The behaviour is not broken — 0 contacts, zone
respected, in-block, the roam still ends itself — but **the objective as
specified made the dog travel LESS, not cover more.**

The mechanism is visible in the trace and it is not churn (only 4–8 distinct
targets per run, 6–15 switches over 120 s — the objective is stable):

> `coverage_candidates` returned **zero rows in 351 of 468 samples** of B1,
> because `exclude_visible=True` drops every entry within the map's 8.0 m
> visibility and **all 50 entries are within 7.1 m of home**. So for three
> quarters of the run there is no objective and the patrol wanders as ROAM-1
> does. An entry only becomes a candidate once the dog has walked far enough
> that it falls *outside* 8 m — at which point it is the least-recently-seen
> place and the dog **turns back toward it**.

**The least-recently-seen objective is a HOMING signal on a map whose entries
are all near home.** It pulls the dog back to what it already knows rather than
outward, and it spends the budget turning: `turn_coverage` outnumbers
`advance_coverage` roughly 4 : 1 in all three runs.

This is DESIGN §g risks 1 and 2 arriving together and sharper than they were
written — "a proposer, not a planner", over "entries the map ALREADY KNOWS" —
and it is the honest result of the card. It is recorded here as a measured
finding, not as a row, because no pre-registered row asked it.

---

## 7. Seeds (RED before green, on a byte-identical scratch copy of `src/`)

| seed | what is broken | the test that must go RED |
|---|---|---|
| **S1** | the coverage input is ignored — `_cruise_or_cover` returns `advance` unconditionally | the policy-steers test in `tests/test_roam2_coverage.py` |
| **S2** | a stale/empty map STOPS instead of wandering — `_cruise_or_cover` returns `PatrolCommand()` when there is no objective | `test_a_stale_map_wanders_it_never_stops` |
| **S3** | a coverage leg outranks the tether — the coverage rung is moved above the tether rung in `PatrolPolicy.step` | the tether-outranks-coverage test |
| **S4** | the yield order is broken — coverage is asked before the person/wall rungs | the yield-order pin |

Each seed: apply to the scratch copy, run the named test, watch it fail,
restore byte-identically by sha256, purge `__pycache__`, re-run green. Seeds
are applied to a **scratch copy**, never to the shared tree, because four other
executors are editing it right now.

---

## 8. What no number here can prove

No robot. No Go2, no D455, no Orin, no Mid-360 exist on this host (owner,
2026-08-22) — every number is MuJoCo through a unix socket. The metric does
not prove the behaviour *reads* as exploring to a person, does not prove a
frontier or a plan (there is neither; DESIGN §g risk 1), and does not measure
places the map never knew.


---

## 6.5 Dynamic city — REPORTED, NOT GATED

**Registered 2026-08-23 07:47, AFTER the static rows of §6.1–§6.4 were seen and
recorded. Nothing in §1–§6.4 changes; no registered row is re-cut.** This
subsection exists because the verifier's F1 found that `README.md` item 4's
"second arm in the dynamic city reported, not gated" had never been run. It is
reported here and gated nowhere.

Conditions identical to §2 except the simulator runs **without** `--static-city`
(pedestrians move — the same thing ROAM-1's own dynamic arm did,
`../task_23/evidence/roam_dynamic_20260822T104612Z`). Same frozen seed map
(sha `46d3c465…`, `map_entries_at_start = 50` in all six), same 120 s budget,
same tether 10.0 m, same `person_stop 0.7`, same product runner.

**A coverage-OFF control triple was run as well**, though the correction brief
called it optional: contacts appeared in the coverage arm, and a safety-shaped
number must not be attributed to a flag without a same-HEAD control.

| run | arm | C1 | legs | path (m) | net in-block (m) | **max radius from home (m)** | contacts | min clearance (m) | in_bounds | `coverage.enabled` samples |
|---|---|---|---|---|---|---|---|---|---|---|
| D1 | coverage **true** | 1.0 (50/50) | 2 | 7.391 | 0.215 | 1.159 | 37 | 0.000 | true | 468/468 |
| D2 | coverage **true** | 1.0 (50/50) | 3 | 11.196 | 1.219 | 2.043 | 15 | 0.000 | true | 468/468 |
| D3 | coverage **true** | 1.0 (50/50) | 7 | 9.904 | 2.004 | 2.004 | 21 | 0.000 | true | 468/468 |
| Dc1 | coverage **false** (control) | 1.0 (50/50) | 0 | 7.654 | 0.756 | 2.529 | 14 | 0.000 | true | **0/468** |
| Dc2 | coverage **false** (control) | 1.0 (50/50) | 0 | 10.391 | 1.623 | 2.557 | 12 | 0.000 | true | **0/468** |
| Dc3 | coverage **false** (control) | 1.0 (50/50) | 0 | 10.470 | 2.622 | 2.622 | 6 | 0.000 | true | **0/468** |

### What the dynamic arm says

1. **C1 is 1.0 again, in all six.** The ceiling is a property of the seed map
   and the map's own 8.0 m visibility rule (§6.1a); the crowd does not touch it.
2. **Contacts and zero clearance are a DYNAMIC-CITY property that predates this
   card, not something the objective introduced.** ROAM-1's own dynamic run, at
   the same `person_stop_m: 0.7` and the same 120 s, before ROAM-2 existed:
   **24 contacts, `min_person_clearance_m` 0.0**, path 6.61 m, net 1.58 m. The
   coverage-OFF control here reproduces it (**14 / 12 / 6** contacts, 0.0
   clearance). In this scene a pedestrian walks into the standing robot; the
   patrol answers with `turn_contact` / `turn_person`, which is the yield ladder
   working.
3. **The coverage arm's contact counts are higher — 37 / 15 / 21 (median 21)
   against the control's 14 / 12 / 6 (median 12) — and this is NOT claimed as a
   result.** Three runs per arm, an input already known to be bimodal (§4), and
   overlapping ranges: the honest statement is that the coverage arm did not
   show *fewer* contacts and may show more, and that a claim either way needs
   more runs than this card has. **Recorded as an open question, not a finding.**
   It is a plausible mechanism — the objective keeps the dog turning near home
   where the pedestrian density is highest — and H2 should be designed with it
   in mind.
4. **The homing pattern of §6.4 reproduces.** Max radius from home is
   **1.16–2.04 m** with the objective on against **2.53–2.62 m** with it off,
   and zero-candidate samples run 343–428 of 468 (against 468/468 in the control,
   which never asks the map). The dog circles its doorstep in the dynamic city
   too, only tighter.
5. **T2 and T3 are NOT met by the dynamic runs — and they were never registered
   over them.** T2 (contacts 0) and T3 (clearance ≥ 0.7) were registered in §3
   over the six *static* runs and are MET there 6/6. The dynamic arm is
   `reported, not gated` by the card's own wording, and its numbers are printed
   above without softening.