# ROAM-2 — "explore" covers the room · STATUS

**Card:** `README.md` · **Design:** `DESIGN.md` (sha256 `6383ff32…`, corrected
this pass — see §5 D2)
**Pre-registration:** `PREREGISTRATION.md` (sha256
`8b43cea1bbb0fc0dccea5946f72c67bf1cb74d977b2e2d6e859056f5928e5b1f` as filled;
the definitions and both arms were written **before any measurement run**, and
every number was appended in the order the card demanded)
**Executor:** Claude Opus (third real attempt) · **Verifier:** Fable
**HEAD:** `e15e466` · **2026-08-23 06:20 – 07:05 EDT** · **COMPLETE**

---

## Headline

**The coverage objective is built, wired, safe, and demonstrably running on the
product path — and measuring it produced a result the card did not expect: it
makes the dog travel LESS, not cover more.**

* **T1 (coverage ≥ 1.5 × baseline): MISSED — CEILING.** C1 = **1.0 in all six
  runs, both arms**. The metric was saturated *before the robot moved*: all 50
  entries the learned map knows sit within **7.1 m** of home, and the map's own
  visibility rule is **8.0 m**. Registered as unreachable in
  `PREREGISTRATION.md` §6.1a **before either arm ran**, so this is a property
  of the scene and the metric, not a number read off the data. No metric was
  substituted and no row was re-cut.
* **T6 (the objective actually engages) MET, and it carries the behavioural
  claim.** Arm B counted **7 / 8 / 7** coverage legs against arm A's
  **0 / 0 / 0**; `turn_coverage` 95/89/83 and `advance_coverage` 16/22/21
  samples appear in arm B's product-path reason histogram and **not once** in
  arm A's. Per-sample `coverage.enabled` was true in 467/468, 468/468, 467/468
  arm-B samples and **0/468 in every arm-A run** — flag-off never turned it on
  and never asked the map.
* **T2–T5 MET 6/6:** 0 contacts, min person clearance ≥ 1.107 m (zone 0.7 m),
  `in_bounds` true, the roam ends itself at budget.
* **How far the dog actually got (the verifier's sharpening, and the row the
  owner should read):** with the objective ON the dog **never exceeded 2.87–3.16 m
  from home** in the three static runs — against **10.06 m** (the tether) in the
  escape-branch baseline A1. The first candidate appears at a radius of only
  **1.64 m**. "Net displacement collapsed" understates it: the coverage arm is a
  dog circling its own doorstep.
* **THE FINDING:** net displacement collapsed in the coverage arm —
  **1.41 / 1.56 / 1.79 m** against the baseline's **6.51 / 3.97 / 3.61 m**.
  `coverage_candidates` returned **zero rows in 351 of 468 samples** because
  `exclude_visible` drops everything inside 8 m and *everything the map knows
  is inside 8 m of home*. A place only becomes a candidate once the dog has
  walked far enough that it falls **outside** visibility — at which point it is
  the least-recently-seen place and the dog **turns back toward it**. **On a map
  whose entries are all near home, "go to the least recently seen place" is a
  homing signal, not an exploration signal.**
* **The default was wrong in the draft and is now off at every layer** (§2.1).
* **The dynamic-city arm is now measured** (correction pass F1, §8): reported,
  not gated. C1 = 1.0 again; the homing pattern reproduces (max radius
  1.16–2.04 m on, 2.53–2.62 m off); **contacts and zero clearance appear in
  BOTH dynamic arms and in ROAM-1's own pre-ROAM-2 dynamic run (24 contacts)**,
  so they are a property of the crowded scene, not of this objective.

* **Reading note (verifier F14):** `coverage_enabled_final: false` in every
  arm-B summary is the **post-roam** snapshot — `roam_snapshot()` reports
  `enabled` from `policy.limits.coverage_bias` and the policy is `None` once the
  budget ends. It is not a flag-off. The evidence that the objective was on is
  the **per-sample** column: 467–468 of 468.
* **Diagnostic the owner should see before deciding on H2 (computed by the
  verifier from the end stores, not by me):** the fraction of the 50 seed
  entries the map's own writer **re-sighted** during the run is the **same in
  both arms** — A 44/49/42 (median 0.88) against B 41/46/42 (median 0.84). The
  objective did not make the dog re-see more of what it already knew. It did
  ground **more new** entries (B 36–42 against A 13–26) — turning in place shows
  the camera more angles — but all inside the same ~7 m radius.

**What the verifier should look at first:** `PREREGISTRATION.md` §6.1a (the
ceiling, registered before the runs) and §6.4 (the finding), then arm A's
`coverage_enabled_samples = 0` — the flag-off identity evidence — in
`~/.cache/parcel-roam2/runs/A{1,2,3}/summary.json`.

---

## 1. Resumed from

| predecessor | what it left | what I did with it |
|---|---|---|
| **15:2x 08-22** (died in crash 2) | `online_map.py` `coverage_candidates` (+114), `patrol/mission.py` (+178), `runtime.py` ROAM-2 hunks, `tests/test_roam2_coverage.py` (687 lines, **never once run**), `tests/test_prototype_profile.py` roam-key pin (+5) | **KEPT the design and nearly all the code.** The map reader, the policy rung, the lock discipline and the degrade paths are good work and I did not rewrite them. Corrected the default, wrapped the unmarked hunks, updated the test contract, and ran the test file for the first time (26 passed). |
| **17:56 08-22** (died in crash 3) | `DESIGN.md` only (13.8 KB) — no code, no PREREGISTRATION | **KEPT**, with §b/§c corrected for the default flip. It is an accurate description of the seams and I measured against it; its §g risks 1 and 2 predicted the finding above. |
| **05:35 08-23** (died 05:38:42 in a kernel OOM caused by another executor's `pytest -n auto`) | nothing on disk | Nothing to keep. Its unfinished job — getting FINISH-1's bimodal baseline into the pre-registration — is done in `PREREGISTRATION.md` §4, and the bimodality reappeared in my own arm A (§3.3). |

**Nothing was discarded and nothing was reverted.** The one substantive change
to inherited code is the default.

---

## 2. What changed

```
 src/parcel_robot/online_map/online_map.py    +114   (inherited, UNMODIFIED by me)
 src/parcel_robot/patrol/mission.py           +190   (inherited + the default flip)
 src/parcel_robot/runtime.py                  +212   (inherited + flip + region wrapping)
 tests/test_prototype_profile.py                +5   (inherited roam-key pin; shared w/ TRUTH-1)
 tests/test_roam2_coverage.py                  687   (new; inherited, contract updated, first run)
 scrum/20260822/task_33/PREREGISTRATION.md     new
 scrum/20260822/task_33/ROAM2_STATUS.md        new
 scrum/20260822/task_33/evidence/run_roam2.py  new    (the measurement driver)
```

### 2.1 THE CORRECTION THAT MATTERED — defaults OFF

The inherited draft turned the coverage objective **ON by default at two
layers**: `limits_from_safety(..., coverage_bias: bool = True)` and
`_roam_limits`'s `overrides.get("coverage", True)`.

The draft's reasoning (written out in the old `DESIGN.md` §c) is not silly:
`limits_from_safety` is the roam behaviour's only constructor, so ON there
means "the prototype explores" while `PatrolLimits()` — which MOVE-1's harness
builds directly — stays untouched. **It still loses to this wave's standing
rule** (`../TASK_BOARD.md` rule 1; the dispatch brief's "defaults OFF for
behaviour"): a behaviour that turns itself on is a behaviour nobody wrote in a
profile.

Both are now `False`. The objective is off at **all three** layers
(`PatrolLimits.coverage_bias`, `limits_from_safety`, the `roam.coverage` read)
and the only thing in the tree that can turn it on is an explicit
`roam: {coverage: true}`.

Two consequences, both of which the measurement then used:

1. **Flag-off is ROAM-1, and it is measured, not asserted.** `_step_roam` guards
   the map query on `policy.limits.coverage_bias`, so flag-off never asks the
   map at all. Arm A's traces show `coverage.enabled` false in **0 of 468**
   samples in every run, and `test_the_objective_is_off_unless_a_profile_asks_for_it`
   asserts `asked == []` against a subclass that records every call.
2. **The measurement got a real baseline** — arm A is ROAM-1, not
   "ROAM-1 plus a query", so the two arms differ by exactly one config line.

`tests/test_roam2_coverage.py` was updated to the corrected contract:
`test_the_objective_is_off_at_every_layer_until_a_profile_says_otherwise`
replaces the old `..._turns_the_objective_on_for_the_prototype`; the runtime
fixture takes `overlay=COVERAGE_ON` (the same config line arm B runs with) in
the four tests that are about the objective; and the off-test is parametrised
over **both** halves of off — no `roam:` block at all, and an explicit
`coverage: false`. **The no-block row is the one that would have caught the
draft.**

### 2.2 Marked regions — every hunk wrapped

All ROAM-2 hunks now open `# ---- CARD ROAM-2 …` and close
`# ---- END CARD ROAM-2 …`, and all sit inside the `CARD ROAM-1` region the
card OWNS. Verified mechanically rather than by eye — every changed line in
`git diff HEAD -- src/parcel_robot/runtime.py` mapped against the marker spans:

```
unclosed regions: {}
changed lines OUTSIDE any ROAM marked region: [4329..4339]
```

Those eleven lines are **XD-1's** comment edit about P1-B's seam test, not
mine; untouched. `runtime.py` was edited under
`mkdir ~/.cache/parcel-batchb/lock-runtime.py` (owner file written, `rmdir`
after each short pass — released, verified empty at close). The
`test_prototype_profile.py` roam pin was inherited already-landed and needed no
further edit, so TRUTH-1's neighbouring region was never touched.

---

## 3. How verified

### 3.1 Unit + guard rows — every pytest through the mandatory wrapper

Prefix for all: `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label roam2 .parcel/bin/python -m pytest`

| command | result |
|---|---|
| `tests/test_roam2_coverage.py -p no:randomly -q` | **26 passed** (0.85 s) — *the first execution this 687-line file has ever had* |
| `tests/test_roam1_behavior.py tests/test_move1_patrol.py tests/test_prototype_profile.py` | **137 passed** (4.21 s) — row **R6** |
| `tests/test_c2_online_map.py tests/test_p1b_map_learns.py` | **105 passed** (0.87 s) |
| all six files together, at close | **268 passed** (5.02 s) |

**R6 holds by construction, not by assertion:** `git diff --stat HEAD --
tests/test_roam1_behavior.py tests/test_move1_patrol.py` is **empty** — this
card edits neither baseline file.

`.parcel/bin/ruff check` on all five OWNS files (incl. `evidence/run_roam2.py`)
→ **All checks passed**. Tree-wide `ruff check .` → **12 errors**, the same
count the 05:3x census recorded; **0 new**, none in my files.

> **CORRECTED 07:5x (verifier F2).** This sentence originally ended "…nothing
> `noqa`'d", **and that was false when written**: `runtime.py:5212` carried
> `except Exception:  # noqa: BLE001`. It followed the file's own convention
> (53 such directives at HEAD) and added no ratchet fingerprint, but the COMMON
> brief says never `noqa` and the claim was wrong. **The directive is gone** —
> see §8 F2 for the narrowed handler. As of the correction pass the count of
> suppression directives this card adds to any file is **zero**, checked as
> `git diff HEAD -- <the four edited files> | grep '^+' | grep -c noqa` → **0**,
> and neither new file contains one.

### 3.2 Seeded RED — four seeds, on a byte-identical scratch copy of the tree

The scratch tree is `~/.cache/parcel-roam2/seedtree` with
`PYTHONPATH=<scratch>/src`. **This mattered:** the first attempt ran green
against the *real* tree because the venv has the package installed editable —
the seed would have proved nothing. Confirmed by
`python -c "import parcel_robot.patrol.mission as m; print(m.__file__)"`
resolving inside the scratch before any seed was applied.

| seed | what was broken | tests that went RED | restored |
|---|---|---|---|
| **S1** | `_cruise_or_cover` returns `advance` unconditionally | **5 failed**, incl. `test_the_roam_asks_the_map_and_the_policy_steers_at_the_answer`, `test_the_turn_onto_a_new_objective_is_not_an_idle_checkpoint` | sha256 **YES** |
| **S2** | a stale/empty map returns `PatrolCommand(reason="idle")` instead of wandering | **4 failed**: `test_a_stale_map_wanders_it_never_stops`, `..._mid_leg_finishes_as_a_wander_rather_than_stalling`, `test_a_runtime_with_no_learned_map_still_roams`, `test_a_map_that_raises_is_a_wander_and_never_an_ended_roam` | sha256 **YES** |
| **S3 + S4** | the coverage rung injected at the TOP of `PatrolPolicy.step`, above tether, person and wall | **2 failed**: `test_a_coverage_leg_never_crosses_the_tether` (S3), `test_a_person_and_a_wall_both_outrank_the_objective` (S4) | sha256 **YES** |

Each seed: applied, `__pycache__` purged, named test watched to fail, file
restored and **sha256-matched against the pre-seed baseline**
(`~/.cache/parcel-roam2/seed_baseline.sha256`), re-run green (**26 passed**).
The scratch tree was deleted at close. **No seed ever touched the shared tree**
— four other executors are editing it.

### 3.3 The measured rows — all through the product runner

Driver `evidence/run_roam2.py`, modelled on ROAM-1's `../task_23/evidence/run_roam1.py`:
it says `submit_realtime_transcript("Go explore.")` and then **only watches**
`snapshot()` / `roam_snapshot()`. **It never constructs a `PatrolPolicy`, a
`PatrolRunner` or a `PatrolSense`** — it contributes the stopwatch and the
post-hoc geometry, nothing else.

Conditions (both arms identical except one config line): `city_block`,
`--static-city`, 120 s, 4 Hz sampling, `person_stop 0.7`, tether **10.0 m**,
`navigation.config: configs/navigation/prototype.yaml`
(`semantic_source: learned_map` — without it the runtime builds no learned map
and the card is inert), the **same frozen 50-entry seed map copied fresh into
every run** (sha256 `46d3c465b0ae39a1…`).

**Arm A — baseline, `roam: {coverage: false}` (measured 06:48–06:54, registered before arm B ran)**

| run | C1 | branch | path (m) | net in-block (m) | in_bounds | contacts | clearance (m) | legs | `coverage.enabled` samples |
|---|---|---|---|---|---|---|---|---|---|
| A1 | **1.0** (50/50) | escape (holds 7, tether@ 77.66 s) | 26.147 | **6.511** | true | 0 | 1.128 | 0 | **0 / 468** |
| A2 | **1.0** (50/50) | unclassified (holds 30) | 21.893 | **3.969** | true | 0 | 1.148 | 0 | **0 / 467** |
| A3 | **1.0** (50/50) | boxed (holds 56) | 19.480 | **3.612** | true | 0 | 1.110 | 0 | **0 / 468** |

**Arm B — coverage, `roam: {coverage: true}` (measured 06:55–07:01)**

| run | C1 | branch | path (m) | net in-block (m) | in_bounds | contacts | clearance (m) | legs | `coverage.enabled` samples |
|---|---|---|---|---|---|---|---|---|---|
| B1 | **1.0** (50/50) | unclassified (holds 17) | 18.752 | **1.409** | true | 0 | 1.108 | **7** | 467 / 468 |
| B2 | **1.0** (50/50) | unclassified (holds 3) | 20.031 | **1.562** | true | 0 | 1.113 | **8** | 468 / 468 |
| B3 | **1.0** (50/50) | unclassified (holds 26) | 17.855 | **1.790** | true | 0 | 1.131 | **7** | 467 / 468 |

**Rows:** T1 **MISSED — CEILING** · T1′ **MISSED — CEILING** · T2 **MET** 6/6 ·
T3 **MET** 6/6 · T4 **MET** 6/6 · T5 **MET** 6/6 · T6 **MET** (B: 7/8/7 legs;
A: 0/0/0) · R6 **MET** · R7 **MET**.

**Bimodality (`PREREGISTRATION.md` §4) reappeared and was wider than
FINISH-1's.** A1 is FINISH-1's *escape* branch almost exactly (6.511 m against
its 6.47–6.57 cluster; first `turn_tether` at 77.66 s inside its 77.4–78.4 s
window); A3 is *boxed* (3.612 m, `turn_hold` 56, tether never reached); A2 sits
between and is left **unclassified** rather than forced into a branch. The §4
guards did their job: every run is printed individually, no arm is summarised
by one number, and because both T1 rows fail on the ceiling the confound
question never had to be adjudicated.

---

## 4. What this does not prove

* **No robot.** No Go2, no D455, no Orin, no Mid-360 on this host (owner,
  2026-08-22). Every number is MuJoCo through a unix socket.
* **It does not prove the objective improves coverage** — the pre-registered
  metric could not discriminate here, and the distance rows say it *cost*
  travel. It proves the objective runs, engages, counts legs, and never
  endangers anything.
* **C1 cannot reward discovery.** The denominator is fixed at the start, so a
  run that learns new places scores nothing for it (`DESIGN` §g risk 2,
  `PREREGISTRATION` §1).
* **C2 is undefined here** (`|S_far| = 0`), so there is no diagnostic view of
  entries the run had to travel to.
* **One scene, one seed map.** The saturation is a fact about `city_block` plus
  a 50-entry local map, not a general claim about the metric.
* **The dynamic-city arm is now run** (correction pass F1, §8 and
  `PREREGISTRATION.md` §6.5) — reported, not gated. What it does **not** settle:
  whether the objective raises the contact count in a crowd. Coverage-on
  contacts were 37/15/21 against a coverage-off control's 14/12/6; the ranges
  overlap, the input is bimodal, and three runs per arm cannot separate them.
  **Recorded as an open question, not a finding.**
* **CURIO-1 remarks-per-leg was not measured.** The card's work item 3 asks for
  it; the checkpoint seam is wired and `advance_coverage` joins `{advance,
  idle}`, but no remark count was taken. Handoff H4.

---

## 5. Deviations

**D1 — the warm-up became three untethered runs instead of one tethered run.**
Recorded in `PREREGISTRATION.md` §2 **after the first warm-up and before any
measured run**, with no measured number seen. The single tethered warm-up
produced 57 entries of which **55 were already within 8 m of the start**, so C1
would have been ≈ 0.96 at sample 0. The warm-up was re-run as 3 × 120 s
untethered, coverage OFF, accumulating into one store. **It did not fix the
saturation** (50 entries, all within 7.1 m, `|S_far| = 0`) — recorded as such
rather than quietly re-tried, and the registered store was used unchanged. The
metric, the rule, the target and both measured arms were untouched by D1.

**D2 — `DESIGN.md` §b/§c corrected in the same pass** (explicitly allowed by the
COMMON brief): the seam table and the "default is the measurement" paragraph
described the default-ON arrangement. Both now describe defaults OFF, with the
old reasoning quoted and the reason for overruling it. The architecture is
unchanged; only one default's polarity moved.

**D3 — `evidence/run_roam2.py` is a new file under `task_33/`.** Inside the
card's OWNS (`task_33/` docs) and the direct precedent of ROAM-1's
`task_23/evidence/run_roam1.py`.

**No other deviation.** Git was read-only throughout (no add/commit/stash/
checkout/reset/restore). `scripts/ci_gate.py` was never run at any tier.

---

## 6. Sim runs — every run, with wall-clock

All ten ran **one at a time**, directly (never under pytest), under
`systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0 --quiet timeout 300`,
with `env -u TMPDIR`, a unique short socket `~/.cache/parcel-roam2/r2-<pid>.sock`,
`PARCEL_ONLINE_MAP_PATH` inside the run directory, and
`PARCEL_LATENCY_LEDGER` redirected into the run directory.

| run | purpose | started | wall (s) | rc |
|---|---|---|---|---|
| `warmup` | first seed attempt (tethered) — kept as evidence for D1 | 06:35 | 124.5 | 0 |
| `warm1` `warm2` `warm3` | the D1 seed map (untethered, coverage OFF, accumulating) | 06:40:59 · 06:43:04 · 06:45:09 | 124.1 · 124.1 · 123.9 | 0 · 0 · 0 |
| `A1` `A2` `A3` | **arm A baseline** | 06:48:26 · 06:50:31 · 06:52:36 | 124.2 each | 0 |
| `B1` `B2` `B3` | **arm B coverage** | 06:55:15 · 06:57:20 · 06:59:25 | 124.2 each | 0 |

Evidence: `~/.cache/parcel-roam2/runs/<name>/{summary.json,roam.yaml,simulator.log,online_map.sqlite3}`
plus each run's stdout. Every summary records `repo_head`, `config_sha256`,
`seed_map_sha256` and the full 4 Hz trace.

**Nothing was left running.** `tools/list_parcel_procs.py` at close: *"No
`parcel_robot.sim` process is running on this host."* No `.sock` remains under
`~/.cache/parcel-roam2/`. The scratch seed tree was deleted. No batch-B lock is
held.

**The owner's things, proved untouched by every run** (each summary carries
both): `parcel_memory.sqlite3` sha256 **unchanged** 10/10;
`evals/nav_instruct/results/ledger.jsonl` sha256 **unchanged** 10/10 — recorded
before and after rather than asserted. `/tmp/parcel_sim.sock` and `:8765` were
never created, connected to, or signalled.

### Anti-crash compliance (auditable against `~/.cache/parcel-guard/guard.log`)

Every pytest invocation went through `pytest_guard.sh --label roam2` — **24
lines in `guard.log` carry that label**, and there are no others of mine. No
`-n` flag was ever passed (so no `-n auto`, no worker fan-out at all).
`scripts/ci_gate.py` was never run at any tier, in any tree. No pytest ran in
the background. No exit 137 and no "Killed" occurred in any run of this card.

**One judgement call, recorded:** at 06:2x the rule-4 check read `avail = 232 GB`
(≫ 120) but `pgrep -fc -- '-m pytest'` read 2. Inspection showed one real peer
suite (`-m "not slow"`, 2.3 GB RSS) plus HY-1's wrapper **blocked on the guard's
own flock**; the raw `pgrep -fc` count is also inflated by shells whose command
strings contain the pattern. I waited for the peer suite to exit rather than
proceeding — **zero pytest processes and 234 GB available** when the first sim
started — and re-checked before each subsequent batch.

---

## 7. Handoffs

* **H1 — the metric needs a venue where the map outruns its own visibility.**
  C1 is only meaningful when some entries lie further from the path than
  `visibility_range_m` (8.0 m). In `city_block` the learned map never extends
  past 7.1 m from home, so C1 is 1.0 for any behaviour. A future measurement
  needs either a larger scene, a smaller `visibility_range_m`, or a metric over
  *recency* rather than *presence*. **Not a change I made after seeing the
  data** — recorded as the next card's problem.
* **H2 — the objective is anti-exploratory on a home-clustered map, and this is
  a design question, not a bug.** `exclude_visible=True` means the nearest
  candidate is always *just outside* visibility, i.e. behind the dog. Options
  worth designing (none implemented): a minimum candidate distance; a forward
  bearing preference; ranking by age *and* by distance from the path already
  walked; or a frontier over unexplored space rather than over known entries.
  The card's own `DESIGN.md` §g risk 1 says "it is a proposer, not a planner" —
  this is the measured cost of that.
* **H3 — CLOSED in the correction pass (§8 F1).** The dynamic-city arm is
  measured, reported and not gated (`PREREGISTRATION.md` §6.5). What it opened
  instead: whether the objective raises the contact count in a crowd
  (coverage-on 37/15/21 vs control 14/12/6, overlapping, 3+3 runs) — an open
  question for H2's design, not a finding.
* **H4 — CURIO-1 remarks per leg unmeasured.** The seam is wired
  (`advance_coverage` joins `{advance, idle}`; `turn_coverage` deliberately does
  not, so the checkpoint opens the instant a leg starts being walked) and arm B
  produced 7–8 legs per run, so the input for `task_24`'s cadence row now
  exists.
* **H5 — the Mid-360 seam is named, not built** (`DESIGN.md` §e): `_step_roam`'s
  checkpoint transition is where an N31 localization update belongs, because it
  is the one moment per leg when the objective's frame can be re-based without
  contradicting an in-flight command. No implementation, as instructed.
* **H6 — for the integrator:** nothing in this card touches `reactive_safety`,
  `core/hard_stop`, the supervisor, CURIO-1's region or `vlm_veto/`.
  `PINNED_LOCK_ORDER` is unchanged (`_p1b_map_lock` stays a leaf: taken from
  `_step_roam` outside `_lock` and outside `_command_lock`, held across one pure
  query that calls nothing back into the runtime).

---

## 8. Correction pass — 2026-08-23 07:30–07:55 EDT

Against the verifier's `ACCEPT-WITH-NOTES` verdict
(`~/.cache/parcel-verify/roam2/VERDICT.md`, 2 FIX / 0 HOLD). Both FIX items are
closed. **No registered row was re-cut**; §1–§7 above stand except where this
section says otherwise, and the two edits it made to earlier text are the F2
sentence in §3.1 and the dynamic-arm bullet in §4, both marked in place.

### F2 (rule, code) — the `noqa` is gone, the handler now names what it catches

`runtime.py:5212` carried `except Exception:  # noqa: BLE001 - a preference is
never worth the loop`. The COMMON brief forbids suppression directives.

**Why a bare narrowing was not enough.** The catch is load-bearing, and the
verdict's phrasing invited checking it rather than assuming: `_step_roam` is
called from `_control_loop_body` at **`runtime.py:10347`**, which is **outside**
that method's only `except` (**`:10254`**, which guards `backend.observe()`
alone), and `_control_loop` (`:10186`) wraps the body in **`try/finally` with no
`except`**. So an exception escaping this query does not degrade a behaviour —
**it kills the 10 Hz control thread.** A preference that can stop a dog is a bug.

**The pattern used, and where it is from.** This file's two catch-alls without a
directive (`:12052`, `:12238`) both **re-raise**, so they are no model for a
handler that must swallow. The model that *is* in the file is the **thread
boundary at `:10254`** — a **named tuple**, no directive:
`except (OSError, RuntimeError, TypeError, ValueError) as error:`. The new
handler is that tuple, extended by what the query path itself can raise:

```python
except (ArithmeticError, AttributeError, LookupError,
        OSError, RuntimeError, TypeError, ValueError):
```

Each name is justified in the comment against the code that produces it
(`AttributeError` — `_visibility_range_m` / `entry.surface_x` / `.last_seen_wall_s`
on an object that is not a real map, and `_p1b_learned_map` is typed `Any`;
`TypeError` — non-numeric coordinates into `math.hypot` / `round` / the
`rows.sort` key; `ValueError` — the query's `float()` conversions;
`ArithmeticError` — `hypot`/`atan2` overflow; `LookupError` — a mapping-shaped
row missing a key; `OSError` — a future store-backed `active_entries()`;
`RuntimeError` — a map implementation declaring itself broken, which is what
`test_a_map_that_raises_is_a_wander_and_never_an_ended_roam` seeds).
`online_map.py`'s own query (`:1112–1200`) already swallows the conversion
errors it can see and answers `()`; this tuple is for the map objects it cannot
vouch for. The hunk stays inside its `CARD ROAM-2 … END CARD ROAM-2` markers.

One follow-on: the explanatory comment originally quoted the directive
literally, and **ruff parsed the quotation as a directive**
(`warning: Invalid noqa directive on runtime.py:5214`). The prose was reworded
so no comment line contains the token. `ruff check` is now **warning-free**.

**Verified:** `ruff check` on all six OWNS files → *All checks passed* (no
warning); `ruff check --select BLE001 src/parcel_robot/runtime.py` → *All checks
passed*; tree-wide `ruff check .` → **12 errors**, unchanged, none in ROAM-2's
files. Suppression directives added by this card, across every file it touches:
**0**. Tests through the wrapper: `tests/test_roam2_coverage.py` **26 passed**;
the six-file set **268 passed**.

### F1 (measurement, reported not gated) — the dynamic-city arm

`README.md` item 4's "second arm in the dynamic city reported, not gated" had
never been run; my 06:24 pre-registration read "both arms" as baseline/coverage
(the dispatch EXTRAS use that wording too) and softened the dynamic arm to "if
time allows". The verifier is right that under the README's literal reading the
DoD was unmet. **It is now measured** — full table and reading in
`PREREGISTRATION.md` **§6.5**, registered there as a new subsection that
explicitly changes nothing in §1–§6.4.

`--dynamic-city` maps to omitting the simulator's `--static-city` flag
(`run_roam2.py:296` → `start_simulator(static_city=...)` →
`run_move1_diagnosis.py:349`), i.e. pedestrians move — the same thing ROAM-1's
own dynamic arm did (`../task_23/evidence/roam_dynamic_20260822T104612Z`).

| run | arm | C1 | legs | net in-block (m) | max radius (m) | contacts | min clearance (m) |
|---|---|---|---|---|---|---|---|
| D1 · D2 · D3 | coverage **true** | 1.0 · 1.0 · 1.0 (50/50) | 2 · 3 · 7 | 0.215 · 1.219 · 2.004 | 1.159 · 2.043 · 2.004 | 37 · 15 · 21 | 0.0 ×3 |
| Dc1 · Dc2 · Dc3 | coverage **false** (control) | 1.0 ×3 (50/50) | 0 ×3 | 0.756 · 1.623 · 2.622 | 2.529 · 2.557 · 2.622 | 14 · 12 · 6 | 0.0 ×3 |

`in_bounds` true 6/6; `roam.active` false at budget end 6/6; seed
`46d3c465…` and `map_entries_at_start = 50` in all six; `coverage.enabled`
468/468 in D, **0/468** in Dc.

**The coverage-OFF control triple was extra** (the brief called it optional). I
ran it because contacts appeared in the coverage arm and a safety-shaped number
must not be pinned on a flag without a same-HEAD control. It settles the
attribution: **contacts and 0.0 clearance are a dynamic-city property that
predates this card** — ROAM-1's own dynamic run, same `person_stop_m` and
budget, before ROAM-2 existed, recorded **24 contacts and 0.0 clearance**, and
the control reproduces it (14/12/6). What it does **not** settle: the coverage
arm's counts are higher (median 21 vs 12) with overlapping ranges on a bimodal
input, so that is **an open question, not a finding** (§4, and a design input
for H2 — the objective keeps the dog turning near home, which is where the
pedestrians are).

### Sim ledger — correction pass (all rc=0, one at a time)

Each: `env -u TMPDIR systemd-run --user --scope -p MemoryMax=12G -p
MemorySwapMax=0 --quiet timeout 300 .parcel/bin/python
scrum/20260822/task_33/evidence/run_roam2.py --budget 120 --dynamic-city
--person-stop 0.7 --coverage <true|false> --tether 10.0 --seed-map
~/.cache/parcel-roam2/seed_map_final.sqlite3 --out ~/.cache/parcel-roam2/runs/<tag>`

| run | arm | started | wall (s) | rc |
|---|---|---|---|---|
| D1 · D2 · D3 | coverage true | 07:33:39 · 07:35:44 · 07:37:49 | 124.1 · 124.2 · 124.1 | 0 · 0 · 0 |
| Dc1 · Dc2 · Dc3 | coverage false | 07:40:37 · 07:42:42 · 07:44:47 | 124.2 · 124.1 · 124.1 | 0 · 0 · 0 |

Unique socket `~/.cache/parcel-roam2/r2-<pid>.sock` per run;
`PARCEL_ONLINE_MAP_PATH` and `PARCEL_LATENCY_LEDGER` redirected into each run
directory. **`parcel_memory.sqlite3` and `evals/nav_instruct/results/ledger.jsonl`
sha256 unchanged in 6/6** (recorded before and after in every `summary.json`).
Card total: **16 sim runs**, every one rc=0, never two at once.

### guard.log — correction pass lines

Four wrapped pytest runs, `label=roam2`, all rc=0, no `-n`:

```
07:04:30 START label=roam2 … -m pytest tests/test_roam2_coverage.py -p no:randomly -q
07:04:32 END   label=roam2 rc=0
07:04:44 START label=roam2 … -m pytest <the six OWNS files> -p no:randomly -q
07:04:50 END   label=roam2 rc=0
07:32:59 START label=roam2 … -m pytest tests/test_roam2_coverage.py -p no:randomly -q
07:33:00 END   label=roam2 rc=0
07:33:00 START label=roam2 … -m pytest <the six OWNS files> -p no:randomly -q
07:33:06 END   label=roam2 rc=0
```

`grep -c 'label=roam2' guard.log` → **28** for the card (24 before this pass).
`scripts/ci_gate.py` still never run at any tier; no background pytest; no
exit 137. Environment checked before each sim batch: 0 pytest processes, 0
sims, 233 GB available.

### Verifier NOTEs also actioned

**F14** — the `coverage_enabled_final` reading note is in the headline.
**F15** — `PREREGISTRATION.md` §6.1a's "12.0 m" corrected: the untethered
warm-ups reached **20.6 m from home**; 12.0 m was the *net in-block* number,
clipped at the 12 m half-extent. **The verifier's re-sighting diagnostic**
(A median 0.88 vs B 0.84 — the objective did not make the dog re-see more of
what it knew) is quoted in the headline with attribution, since H2 is the
decision it informs. F3–F13 are confirmations requiring no change.

### Not done, and why

The verifier's "smallest re-registration that makes T1 measurable" options
(move the start pose to a block corner; re-cut C1 to the map writer's
re-sighting; lower `visibility_range_m`) are **not** implemented. Each is a new
registration or a code change, T1 is a MISS that stands, and re-cutting a row
after seeing its number is precisely what the card forbids. They belong to
whoever picks up **H1**.
