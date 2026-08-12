# W2-EVAL status — card VS-6 (2026-08-11, task_1)

Lane W2-EVAL, executor Opus. One card from the authoritative record
`scrum/20260811/task_1/FOLLOWUP_DESIGNS.md` (§0, §2, §6 card block
"Card VS-6"): **additive search-exercising eval cells + phantom mutant, v4
untouched**. No commit made.

Everything here is additive. `evals/nav_instruct/episodes/v4/**` and all four
`DIGEST_SENTINELS` are byte-identical to their pins; the proof is §6.

---

## 1. What landed

| Deliverable | Where | What it is |
|---|---|---|
| v4s generation | `evals/nav_instruct/generator.py` `+633 −1` | `generate_v4s_matrix()` + the `v4s` episode-set spec, its landmark slice, its blocking discs, its routability router. The single deleted line is the `scene_truth` import, rewritten multi-line — nothing existing was removed or re-shaped |
| v4s episode set | `evals/nav_instruct/episodes/v4s/**` (NEW, 180 episode files + own manifest) | 60 episodes on each of three axes; manifest digest `0f19350d…` |
| `--episode-set` seam | `evals/nav_instruct/run_nav_instruct_v1.py` `+63 −10` | `--episode-version`/`--episode-set` accepts `v4s`, `--per-axis`, `--freeze` REFUSES v4s, and a v4s ledger row can never be `frozen_baseline` |
| phantom mutant | `scripts/mutation_panel.py` `+116 −1` | `phantom_view_consistent`, appended seventh |
| regenerated panel | `evals/nav_instruct/results/mutation_panel.json` `+94 −2` | +1 row, every pre-existing row byte-identical (§5) |
| cells + gate tests | `tests/test_v4s_search_cells.py` (NEW, 773 lines, 28 tests) | axis claims re-derived per episode, digest invariants, panel diff, and the VS-4 phantom gate with each conjunct seeded failing |
| mutant-count pins | `tests/test_mutation_panel_freshness.py` `+11 −3`, `tests/test_nav_instruct_scene_gen.py` `+16 −2` | the two places that pinned the panel's mutant count as a literal; see §7 (out-of-OWNS, declared) |

---

## 2. The cells — what each axis measures

Three axes, 60 episodes each (card floor 20; VS-5's pre-registered aim 60).
The axis code is the episode's `tier`, so the runner's existing
`by_family_tier` dashboard reports per-axis cells with **no scoring change**.

| Axis | `tier` | Claim, asserted per episode at generation AND re-derived in the test |
|---|---|---|
| look-around | `LA` | target is out of the start frustum **and** farther than the frustum's RANGE (12.0 m), so the opening full-turn scan at the start pose cannot see it; the straight corridor to it is clear of every building disc — the missing ingredient is *looking*, not routing |
| beyond-the-block | `BB` | same invisibility, but the straight corridor crosses ≥1 **building** footprint — the frontier *direction* is what has to be right |

On **every** axis the straight corridor also clears the owner ring. That is not
cosmetic: the first generation admitted 13/60 `BB` cells whose only "block" was
the default owner standing in the line, i.e. cells that would have measured the
reactive gate (D-15) while claiming to measure a detour. The owner disc now
excludes a cell from every axis, so "beyond the block" can only mean a building.
| phantom | `PH` | an `LA` cell plus a same-class distractor at the corridor midpoint: inside the opening scan's range while the real target is outside it, outside the scored goal region, with **no MuJoCo geometry** (`apply_placement_overrides` adds a perception spec only) — a detection with nothing behind it |

**Why range is the load-bearing half.** An in-place full turn sweeps every
bearing, so bearing alone cannot hide a target from the opening scan; range can.
This is the direct answer to the V-D diagnosis (§2.1(2b)): the GP-UCB look block
only runs *after* the full turn, so on the frozen matrix every in-range target
is already found and extra looks are structurally redundant. `range >
VISIBILITY_MAX_RANGE_M` is what makes a cell able to move at all.

Per-axis geometry as generated:

| Axis | n | target range from start (min / mean / max) | families | targets |
|---|---|---|---|---|
| `LA` | 60 | 12.01 / 12.82 / 13.97 m | 34 `object_goal`, 26 `object_relative` | tree_1 14, tree_2 13, bench_1 13, planter_1 13, lamp_post_1 7 |
| `BB` | 60 | 12.01 / 12.66 / 13.87 m | 40 `object_goal`, 20 `object_relative` | 10 each of all six |
| `PH` | 60 | 12.01 / 13.53 / 16.44 m | 35 `object_goal`, 25 `object_relative` | tree_1 14, tree_2 14, planter_1 14, bench_1 11, lamp_post_1 7 |

`BB`'s building blockers: `bldg_5` 41, `bldg_1` 11, `bldg_3` 10, `bldg_6` 7,
`bldg_2` 7, `bldg_4` 5 — all six buildings exercised, none owner-only.

Six targets (`tree_1`, `tree_2`, `lamp_post_1`, `lamp_post_2`, `bench_1`,
`planter_1`) × the frozen matrix's own instruction strings — v4s adds **zero new
natural-language surface**. The other instance of a two-instance class is
removed from the episode's perception specs via the existing tier-E
`remove_entities` mechanism, so a cell measures search and not instance
disambiguation (that is §2.2(a)(i)'s problem, and VS-4 owns it).

**Derived constants, no new literals**

| Quantity | Value | Derivation |
|---|---|---|
| beyond-scan threshold | 12.0 m | `VISIBILITY_MAX_RANGE_M` — the world's own frustum range, already pinned equal to it |
| start-heading offsets | `{0, ±2π/8}` | `2π / full_turn_scan_spec().n_stops`, **by reference**, bit-identical (`struct.pack`) — the same authority §2.2(b) makes the view-admission rule |
| owner corridor keepout | 2.03 m | `FOLLOW_HOLD_BAND_OUTER_M` (stand-off + deadband) — the follow stack's outermost holding ring, which clears both the gate's owner slow band (1.30 m of surface clearance) and its predictive stop at cruise (1.2 + 0.85·0.12 = 1.302 m). The D-15 lesson applied at generation time: a cell whose route dies on the owner ring measures the gate, not the search |
| placement clearance | 0.92 m | `footprint_radius_m + obstacle_stop_floor_m` — applied to start poses and phantom placement |
| phantom position | corridor midpoint | no free parameter; `range/2 > 6 m` from the target so it can never be inside the scored region, and `≤ 12 m` from the start so the opening scan reaches it |
| phantom radius/label | the target's own | it is an instance of the queried class |

**Selection rules, declared** (both fixed before any flag-on arm existed):
round-robin across targets, and nearest-first within a target — every admitted
cell is already beyond the frustum, and among those the ones just past the
threshold are the ones a better search can plausibly convert; a target 19 m away
tests the step budget.

**Routability.** Every episode asserts, at generation, a grid route from its
start **into the scored `GoalRegion`** with all six buildings and the owner
ring blocked; an unroutable candidate is dropped, never emitted. That is
strictly stronger than the frozen `_approx_shortest_path_m`, which routes to one
sampled point and *nudges* a blocked goal cell to a free neighbour. The route
length **is** each episode's `shortest_path_m`, so SPL and the scaled step
budget are computed from the same number. The test re-derives it per episode
rather than reading the recorded evidence dict.

Admissible yield (what the generator had to choose from): `LA` 99, `BB` 194,
`PH` 66 — all above the 60 taken. **No STOP-and-report on open question 8.**
Generation RAISES rather than shrinking if an axis cannot be filled, so a future
scene edit that drops the yield is a loud failure, not a quiet smaller set.

---

## 3. Measured — flag-off control arm on v4s

Protocol: `--mode candidate`, no navigator flags (the flag-OFF arm),
`scaled-path-v1` budget, `max_steps 200`, arrival rule `hold-or-trace-end-v1`,
v4s seed 20260811, all 180 episodes. Run **out of tree** by a scratchpad script
that writes no ledger row and no in-tree file.

**Determinism (card gate 3): PASS, byte-exact.** Two independent processes over
all 180 episodes:

```
run A  run_digest e2a4d151c68d45f2407ddcf177e4a6113538f243a6161bf8af77a3bf76b0f7cb  (547.7 s)
run B  run_digest e2a4d151c68d45f2407ddcf177e4a6113538f243a6161bf8af77a3bf76b0f7cb  (543.9 s)
```

The digest is sha256 over `[item.as_dict() for item in results]` — every
episode row **including its full trace** — and the two payloads compare equal
field by field (`episodes`, `aggregate`, `episode_digest` all identical;
`episode_digest` = the set's own `0f19350d…`).

**Whole arm (n = 180):** SR **0.000**, SPL **0.000**, mean dtg **10.874 m**,
collisions **0**. Failures: `grounding_error` 74, `planning_error` 73,
`false_arrival` 28, `search_error` 5. Authority: `agreement` 152,
`false_arrival` 28, `authority_disagreement` 0.

| Axis | n | SR | mean dtg | failures | authority |
|---|---|---|---|---|---|
| `LA` | 60 | 0.000 | 12.024 m | grounding 33, planning 17, false_arrival 10 | agreement 50, false_arrival 10 |
| `BB` | 60 | 0.000 | 12.555 m | grounding 41, planning 17, false_arrival 1, search 1 | agreement 59, false_arrival 1 |
| `PH` | 60 | 0.000 | 8.044 m | planning 39, false_arrival 17, search 4 | agreement 43, false_arrival 17 |

**The PH axis engages the phantom** (this is what makes VS-4's first conjunct
non-vacuous):

* **2 phantom arrivals** — arrival claimed with the final pose inside the
  phantom's own vicinity envelope: `PH-31` (0.452 m from the phantom) and
  `PH-10` (1.222 m). Flag-on must take this to **0**.
* **28 of 60** cells stopped inside the phantom's vicinity at all — the phantom
  is approached in nearly half the axis, whether or not an arrival is claimed.
* The other 15 of the 17 PH arrival claims are false arrivals somewhere else
  entirely (6–7.5 m from the phantom). Real defects, but not this gate's, and
  the gate is written so they are not miscounted as phantom arrivals.

Running the gate of §4 against this measured arm gives exactly:

```
phantom_arrival:nav-object_goal-PH-10-48835339
phantom_arrival:nav-object_goal-PH-31-2dab201e
non_vacuity: no lock-on commit-then-refutation event
non_vacuity: no FP-memory suppression on re-encounter
```

i.e. **the flag-off arm fails all three conjuncts**, which is the property that
makes the gate worth running at all.

`--episode-set` seam, end to end, in a scratch rsync (`--limit 3`): row written
with `baseline_version: "v4s"`, `frozen_baseline: false`; `--freeze` on v4s
exits with the refusal message. No in-tree ledger row.

**What this does and does not say.** SR 0 flag-off is the DESIGNED property of
these cells — VS-5's gate calls them "cells built to be unfindable flag-off" —
not evidence that the flags work. Whether a flag-on arm converts any of them is
VS-4's and VS-5's measurement, and their gates are pre-registered to
STOP-and-report if it does not.

> **CORRECTION — card AF-2, 2026-08-11. The "unfindable flag-off" property is
> MATCHER-RELATIVE, and every number in §3 above is the DEFAULT (string/alias
> fallback) arm's.** Provenance: `AUDIT_WAVE2_FABLE.md` should-fix 5, on
> `W2_WIRE2_STATUS.md` §10 / §14.1b, independently reproduced by the audit.
> With real weights (`PARCEL_SIGLIP2_ONNX=1`) the **`LA` flag-off baseline is
> SR 0.100 (6/60), not 0.000, and its 10 authority `false_arrival`s become 0** —
> real cosine matching refuses the cross-class commits the fallback accepts
> (`nav-object_goal-PH-31-2dab201e`: a real lamppost committed for a "tree"
> query, W2_WIRE1_STATUS.md §7). `BB` and `PH` stay 0.000 flag-off in both arms.
> Consequence, binding on any future card: **a gate pre-registered on these
> cells must name its matcher arm**, and the "flag-off SR is 0.000 so any
> success is a paired flip" premise holds only in the default arm. The same
> statement is now pinned next to the cells themselves, in
> `evals/nav_instruct/episodes/V4S_MATCHER_ARM.md`.

### Blocked on wiring (explicit)

* **Flag-on arms are not run here.** `lock_on_verify_on_approach` is not in
  `ALLOWED_NAVIGATOR_OVERRIDES` (VS-4 adds it, Wave-2 slot 1) and nothing
  consumes VS-1/VS-2/VS-3's landed modules yet, so a flag-on v4s arm is not
  runnable on this tree. The two runnable flags (`value_directed_search`,
  `detection_lock_on`) are wired to the *old* behaviour the rework replaces;
  measuring them would produce a number nobody should quote.
* **The non-vacuity conjuncts cannot be measured live yet** — no
  commit/refutation telemetry and no FP-memory suppression counter exists on the
  commit path until VS-4 lands. The gate is implemented and proven able to fail
  (§4); its *inputs* are what is blocked.
* **VS-5's paired statistics are not computed here.** VS-6 supplies the
  substrate (n = 60/axis, matched flag-on/flag-off pairing is per-episode);
  the exact-McNemar computation is VS-5's harness.

### A structural finding VS-5 will hit (measured, reported now)

The grid planner's local costmap is `grid_size_cells 161 × resolution_m 0.10`
= **16.1 m across, i.e. ~8 m of reach**, while the perception frustum is 12 m.
So on these cells a target becomes VISIBLE at 12 m and stays UNROUTABLE until
~8 m, and the pipeline's answer to `goal_blocked` while not making progress is
`_unroutable_goal_recovery` → release the instance → (with the twin removed)
`semantic_target_unreachable`. Range sweep, candidate mode, flag-off, on
hand-built probe cells approaching `lamp_post_1` from due south — **probes, not
v4s cells**: their corridor passes through the owner ring, which v4s excludes.
They isolate range and nothing else:

| start range | outcome |
|---|---|
| 9.0 m | `false_arrival` (dtg 2.558) |
| 11.0 m | **SUCCESS**, dtg 0.000, 153 steps |
| 12.5 m | `grounding_error / semantic_target_not_found`, dtg 11.384 — the robot barely translated |
| 14.0 m | same, dtg 12.751 |

The cliff sits exactly at the frustum boundary, which is what the v4s axes are
built across. `does_not_prove`: this says the *current* frontier search does not
close a 12 m gap; it does not say an evidence-fed one cannot. It does mean
VS-5's effect, if any, has to come from the search moving the robot, not from
better looks at a target already in view.

---

## 4. The phantom gate and its non-vacuity conjuncts (adjudication #19)

`phantom_cell_gate()` in `tests/test_v4s_search_cells.py` is the gate VS-4
runs, as a pure function over trace-derived outcomes. Three conjuncts, all
required:

1. **zero phantom arrivals** — no episode where the navigator claims arrival
   with its final pose inside the phantom's **vicinity envelope**
   (`object_near_envelope_m(...)[2]`, i.e. the same `vicinity_radius_m` the
   world stamps into that distractor's metadata — the navigator's own notion of
   "at this object", not a threshold invented for the gate). Deliberately the
   vicinity and **not** the near-goal band: the band is an annulus with an inner
   edge because it describes where a compliant approach *stops*, and both
   measured flag-off phantom arrivals landed at 0.452 and 1.222 m — both INSIDE
   the 1.7 m inner edge. A band predicate would have scored the flag-off arm
   zero and made this conjunct vacuous before VS-4 ever ran it. (That is not
   hypothetical: the band predicate was the first implementation, and the
   measured arm is what caught it.)
2. **≥1 lock-on COMMIT-then-REFUTATION** — one session that entered a committed
   state (`APPROACH`/`VERIFY`/`VERIFIED`) and *later* reported `REJECTED`.
   Vocabulary is `instructnav.scoring.ApproachVerifyState`, which VS-1's landed
   `LockOnVerifySession` already speaks; the gate invents no enum.
3. **≥1 FP-memory suppression on re-encounter** — a
   `NegativeEvidenceMemory.consult(...)` answer with `Suppression.suppressed`
   true (VS-2's surface).

**Proven able to fail — each violation seeded, each is a passing test:**

| Seeded violation | Test | Gate says |
|---|---|---|
| empty arm (nothing ran / feature never engaged) | `test_phantom_gate_fails_on_an_empty_arm` | both non-vacuity failures |
| claimed arrival at the phantom's approach band (1.8 m) | `test_phantom_gate_fails_when_the_robot_arrives_at_the_phantom` | `phantom_arrival:cell-7` |
| claimed arrival *inside* the band's inner edge (0.452 m — the measured case) | same | `phantom_arrival:cell-7` |
| claimed arrival 6 m away (a false arrival that is NOT at the phantom) | same | passes — not this gate's defect |
| committed, never refuted | `test_phantom_gate_fails_without_a_commit_then_refutation` | no commit-then-refutation |
| refuted *before* it committed (order is load-bearing) | same | no commit-then-refutation |
| session A committed, session B refuted | same | no commit-then-refutation |
| zero suppressions | `test_phantom_gate_fails_without_an_fp_memory_suppression` | no FP-memory suppression |

The empty-arm case is the V-D lesson made mechanical: "no phantom arrivals" is
also exactly what "the episodes never ran" looks like, and the gate refuses it.

---

## 5. The mutation panel — exactly +1 row

`phantom_view_consistent`: every candidate the oracle reports gains a twin
**reflected through the pose the episode started at**, at confidence 1.0. Three
properties make it the defect §2.1(3) names rather than noise:

* **view-consistent**: the twin is LATCHED — created once, re-emitted every tick
  whether or not its source is still in frustum. A phantom that vanished when
  the robot turned away would be *flicker*, which is the only thing
  `MultiViewConfirm`'s rejected-memory already catches. The latch resets when the
  world clock does (`reset()` zeroes `data.time`), so one episode's phantoms
  cannot leak into the next.
* **it wins**: `ObservationSemanticMap.query` sorts by `-confidence` first and
  the oracle reports 0.98; 1.0 is the closed upper bound
  `SemanticCandidate.__post_init__` enforces. A detector certain about something
  that is not there is the seeded defect.
* **it actually mutates**: the reflection moves position, region polygon **and**
  `metadata["goal_region"]` — the thing the navigator approaches. A phantom
  whose goal_region still pointed at the real object would be a mutation that
  does not mutate, which reads as a survivor.

**Verdict: killed**, through the channel the card names:

```
| `phantom_view_consistent` | killed | `no_false_arrival`, `success_set_identical`,
  `mean_dtg_within_tolerance`, `failure_histogram_identical`, `final_poses_within_tolerance` |
```

The kill is the V-E signature reproduced as a seeded defect: on
`nav-region_goal-A-00` the robot walks onto the *reflected* sidewalk at
(0.57, −2.43) — the south side — and claims arrival; K0 says 4.63 m from the
real region → `false_arrival` 1.

**+1-row diff, proven** (before/after `evals/nav_instruct/results/mutation_panel.json`):

| Field | Moved? |
|---|---|
| `clean_run` (all five episodes, poses, dtg, collisions, authority) | byte-identical |
| `clean_checks` (all four) | byte-identical |
| `survivors`, `equivalent_mutants`, `passed`, `episode_ids`, `episode_set_version`, `kind`, `method`, `episode_selection`, `frozen_baseline` | byte-identical |
| all six pre-existing mutant rows, in order, incl. `checks_reddened` | **byte-identical** |
| `generated_at` | changed (timestamp) |
| `episode_set_provenance` | appended: why it was re-run, and the byte-identity claim above stamped onto the artifact itself |
| `mutants[6]` | **added** — the one new row |

`git diff` on the artifact: 94 insertions, 2 deletions; the two deletions are
`generated_at` and the provenance string. Panel result: **7/7 killed, 0
survivors**, `no_false_arrival` still green on the clean run (so it remains a
live kill channel, which is the anti-rot property that file exists for).

Development iterations ran with `--out` pointed at the scratchpad; only the
final regeneration landed in-tree.

---

## 6. Frozen-digest byte-identity proof

```
$ sha256sum evals/nav_instruct/episodes/v3/manifest.json \
            evals/nav_instruct/episodes/v4/manifest.json \
            evals/companion/embodied_plan_v1/manifest.json \
            evals/companion/personal_convo_v1/manifest.json
eb1289e9723e008336b33bff83f2e4c9a91e07d1e6552866f6ede52da7f57858  v3/manifest.json
b29454443e93b68d238c11d31298e81c2e9cae89d7669d9d6556405e9b7388ec  v4/manifest.json
22736f6e0e4b106c0d130b9f7f425feca465a73b20da1431dfd5e2e3b1ce9389  embodied_plan_v1/manifest.json
d338f3352cd9597aeb9977f75c139d926bdfba1fe1d6b036b9a3ace08a1cf114  personal_convo_v1/manifest.json
```

All four equal their `DIGEST_SENTINELS` pins — including the v4 manifest hash
**`b2945444…`**, which is the sentinel (adjudication #18: it is the *manifest*
hash, not the minival digest).

Second invariant, the E8 **minival-report** digest:

```
matrix_digest(generate_minival(version="v4")) = 4113607b92c734dfdd46004b6e77baf6575fc2a1c493e5d9dc5a12c6c5490222
matrix_digest(generate_minival(version="v1")) = cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf
```

both unmoved. `git status evals/nav_instruct/episodes/` reports only the new
untracked `v4s/`; `git diff` on `episodes/v4/` is empty — the 25 v4 episode
FILES are byte-untouched, and `tests/test_v4s_search_cells.py` re-proves it file
by file against a fresh generation rather than by hash alone. Frozen manifests
are additionally asserted to carry **no** `search_axes`/`episodes_per_axis`
key: the new manifest fields are conditional and cannot reach a frozen set.

---

## 7. ci_gate, ruff, and the out-of-OWNS edits

`scripts/ci_gate.py --tier commit`, 2026-08-11T11:59:11Z, after everything in
this lane landed (identical result at 11:42:42Z before the `BB` axis was
tightened):

```
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline …v4-20260811T070536Z: collisions=0
                                          false_arrival=0 | mutation panel clean: collisions=0
                                          no_false_arrival=True | mutation panel freshness:
                                          committed fields reproduce live = True | follow-bench:
                                          7 rows hard_collision_total all 0 | walk_with_me ok
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   2 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3568 passed, 9 skipped, 36 deselected
RESULT: PASS — every hard gate green.   elapsed 124.5s
```

**Suite delta, attributed.** 3568 = W2-PURE's post-landing 3541 + **27 from this
lane**. `tests/test_v4s_search_cells.py` collects 28; one
(`test_every_v4s_start_pose_is_collision_free_in_the_world`, which builds the
MuJoCo world) is `@pytest.mark.slow`, so the default suite's `not slow`
selection takes 27 and deselected goes 35 → 36. `ruff` is back to `new 0`: the
two fingerprints W2-PURE's run attributed to `evals/nav_instruct/generator.py`
(RUF046, RUF059) were this lane's, caught mid-edit, and are fixed.

**One red found and fixed inside this lane**, recorded because it was a real
red on a real run: the first `--tier commit` after the panel regeneration failed
`tests/test_nav_instruct_scene_gen.py::test_the_panel_seeds_exactly_the_plans_six_defects`,
which pinned `set(MUTATIONS)` to exactly the original six. See the table below.
Nothing red was attributable to either sibling lane (AF-1 on
`tests/test_nominal_stop_wiring.py` + docs; W2-PURE's six new pure files).

### The two edits outside my OWNS list, declared

The card's own deliverable — "+1 mutant row" — makes two pre-existing
assertions red **by construction**, because both pin the panel's mutant count
as a literal. Neither file is in **any** card's OWNS list in the whole batch
(§6.1 matrix and all 17 OWNS lists checked). Both edits are the minimum that
keeps each guard's purpose intact; both are found and fixed here rather than
left for the audit.

| File | Was | Now | Why it is still a guard |
|---|---|---|---|
| `tests/test_mutation_panel_freshness.py` | `_EXPECTED_KILLED = 6`; `len(killed) == 6` | `_MINIMUM_KILLED = 6`; `len(killed) == len(mutants) >= 6` | a mutant disappearing, or one exercised but not killed, is still red — and it is now *stronger*: it demands EVERY mutant be killed, where before a seventh could have survived unnoticed |
| `tests/test_nav_instruct_scene_gen.py` | `set(MUTATIONS) == {the six}` | `== PLAN_SIX_DEFECTS \| set(ADDED_DEFECTS)` with `ADDED_DEFECTS = {"phantom_view_consistent": "VS-6"}` | the set stays EXACT, so no mutant can appear without being declared; adding one is a named one-line entry rather than a red build. The test name loses the stale "six" |

Fable should treat both as out-of-scope edits to adjudicate, not as silent
widenings. Neither weakens a safety property: the panel's kill channels,
verdict logic, and the four `clean_checks` the hard gate certifies from are
untouched.

---

## 8. `does_not_prove`

* The v4s cells are **not run under any flag-on arm** here. No claim is made,
  or can be made from this lane, about whether the visual-search rework moves
  them.
* SR 0 flag-off is not evidence that the cells are *solvable*. It is evidence
  they are not solvable by the current search, which is what they were built to
  be. If the flag-on arm also scores 0, VS-5's pre-registered answer is
  STOP-and-report, and the ~8 m planner reach measured in §3 is the first thing
  to look at.
* The phantom cells exercise a phantom the SIM ORACLE reports (a perception spec
  with no geometry). They say nothing about a real camera's false positives;
  that closes with hardware perception, and VS-1's `does_not_prove` says the
  same about persistence.
* `phantom_cell_gate` is proven to fail on seeded violations. It is **not**
  proven to fire on live telemetry, because that telemetry does not exist until
  VS-4 lands.
* v4s is **not frozen**: no `DIGEST_SENTINELS` entry, `--freeze` refuses it, and
  a v4s row can never be `frozen_baseline`. The digest pin in the test is a
  don't-regenerate-by-accident guard, not a freeze.
* The determinism proof covers the flag-off control arm on this tree. It says
  nothing about determinism under a flag whose code does not exist yet.

---

## 9. Files touched

**Edited (in OWNS):**
`evals/nav_instruct/generator.py`, `evals/nav_instruct/run_nav_instruct_v1.py`,
`scripts/mutation_panel.py`, `evals/nav_instruct/results/mutation_panel.json`
(regenerated deliverable).

**New (in OWNS):** `evals/nav_instruct/episodes/v4s/**` (180 episodes +
manifest), `tests/test_v4s_search_cells.py`.

**Edited (out of OWNS, declared §7):** `tests/test_mutation_panel_freshness.py`,
`tests/test_nav_instruct_scene_gen.py` — both only where they pin the panel's
mutant count as a literal.

**Untouched, as required:** `evals/nav_instruct/episodes/v4/**`,
`evals/nav_instruct/runner.py` (VS-4's file this wave — the arrival-rule table
stays its property; the CLI falls back to the runner's own default instead),
`rescore.py`, `cam_foundation_pack.json`, `evals/nav_instruct/results/ledger.jsonl`,
every `DIGEST_SENTINELS`-pinned file, `scripts/ci_gate.py`.

No commit made.
