# EVAL lane — watchable eval, bundled re-freeze, Wave-2 instruments · status

**Date:** 2026-08-07 · **Plan:** [docs/STRATA_GENERALIZATION_PLAN.md](../../../docs/STRATA_GENERALIZATION_PLAN.md)
(eval instruments 1, 3, 6b; sequencing Wave 2) · **Concurrency:** two other
executors were editing `src/parcel_robot/**` throughout. Nothing in this round
touches `src/`; every measurement below was produced by eval-side code against
whatever the tree held at that moment, and where the tree was mid-edit it is
said so.

## Outcome per card

| card | outcome |
|---|---|
| V-1 watchable sequential UI eval | **done.** `scripts/watch_nav_evals.sh`, verified end to end headless on one case. |
| V-2 bundled re-freeze (episode set v2) | **done.** v1 byte-identical, v2 frozen, bridge measured per correction, U31/U32 closed with evidence. |
| V-3a scene-generalization split | **done.** 5 frozen `val_unseen` scenes, `--scenes`, gap measured in both modes. **The SR gap is not resolvable at n=15; the distance gap is, and it is worse unseen.** |
| V-3b metamorphic pairs | **done, and it found a defect.** Rigid-transform equivariance is violated on `go to the sidewalk` under both transforms; pinned xfail with the measurement. |
| V-3c mutation panel | **done. 6/6 mutants killed** — after a coverage fix the panel itself forced. |

---

## V-1 — the watchable sequential eval

```
scripts/watch_nav_evals.sh                     # every case, in file order, one window each
scripts/watch_nav_evals.sh --only sidewalk     # substring filter on the case name
scripts/watch_nav_evals.sh --pause             # wait for Enter between cases
scripts/watch_nav_evals.sh --list              # print the plan, run nothing
```

It is a **viewer**, not a harness. Each case is `pytest tests/test_voice_nav_e2e.py::<case>`
in its own subprocess (the e2e fixture already tears the sim and the runtime
down per case), so the verdicts are pytest's own and no scoring lives here. The
banner's instruction, xfail reason and goal region are read out of the test
source by AST — the test file stays the single source of truth and is never
imported by the driver, never edited, and never given a second copy of its
table. The metrics after each case come from the case's **own** evidence dict,
captured by a pytest plugin (the same file, `-p watch_nav_evals`) that wraps
`_run_command_to_terminal`; it changes no assertion, so a verdict under the
watcher is the verdict under plain pytest.

`MUJOCO_GL` defaults to `glfw` in the wrapper (a real window) and the wrapper
fails fast with a readable message when `DISPLAY`/`WAYLAND_DISPLAY` are unset,
instead of a MuJoCo crash 20 s later.

**Verified headless** (`MUJOCO_GL=egl`, one case, the owner will run it windowed):

```
CASE 1/1   test_walk_towards_the_lamppost_grounds_plans_and_arrives
  instruction     : 'can you walk towards the lamppost'
  expected        : PASS (hard gate)
  goal region     : lamp_post_1: relative_band centre (0.2, 3.15) band (0.6, 2.5) m
  city            : static
  VERDICT         : PASSED   (20.4 s wall)
     reply        : Okay—I'll go wait near lamppost safely.
     moved        : [0.0, 0.0] -> [-0.0, 0.681]  (0.681 m in 18.0 s)
     dist to goal : 0.0 m
     task states  : ['succeeded']  details=['navigation_goal_verified']
     arrival      : system=True scorer=True -> agreement
```

17 cases are collected in file order. **Not claimed:** the windowed path is
untested here — `MUJOCO_GL=glfw` was never exercised on this machine, only the
`egl` override. If glfw fails for the owner it will fail at sim startup with the
sim's own error, which the driver prints.

---

## V-2 — the bundled re-freeze (episode set v2)

Full record: [`evals/nav_instruct/EPISODES_V2_CONTINUITY.md`](../../../evals/nav_instruct/EPISODES_V2_CONTINUITY.md).

**v1 is untouched.** Digest still `cf4d5384…`; both frozen report JSONs
byte-identical (`1871a938…`, `0f6cac9b…`); the first nine ledger lines
byte-identical (`dab60242…`); `scene_truth.json` byte-identical (`43688b1c…`).
Every default in `generator.py` still resolves to v1 — v2 has to be asked for by
name, and a test asserts that too.

**v2** = digest `a17c04dbec43a1749386c304060fb479a71f27d4b51b8c1b0fbb949753fc563d`,
`evals/nav_instruct/episodes/v2/` (25 files + manifest), two new ledger rows
marked `baseline_version: "v2"`, `arrival_rule: "hold-or-trace-end-v1"`.
`evals/nav_instruct/episodes/v1/` was written out as well, so the superseded set
is an artifact and not just a digest.

### Bridge — per correction, all cells measured on one tree

`evals/nav_instruct/results/bridge_v1_v2.json`. Six cells (2 modes × {v1, v1a,
v2}) in one pass. **v1a** is a bridge-only intermediate carrying correction (a)
alone, so (a) and (b) are separable rather than lumped. (a) and (b) are read
with **both sides under the frozen hold rule**; (c) is read **inside the v2 run**
(same traces, two rules), so no correction can borrow credit from another.

| mode | correction | SR before | SR after | Δ SR | Δ mean dtg (m) |
|---|---|---|---|---|---|
| baseline | (a) derived scene truth | 0.04 | 0.04 | **0.00** | −0.0075 |
| baseline | (b) episode spec fixes | 0.04 | 0.04 | **0.00** | −0.4156 |
| baseline | (c) arrival rule | 0.04 | **0.16** | **+0.12** | — |
| baseline | **total v1 → v2** | 0.04 | **0.16** | **+0.12** | −0.4231 |
| candidate | (a) derived scene truth | 0.04 | 0.04 | **0.00** | −0.0005 |
| candidate | (b) episode spec fixes | 0.04 | 0.04 | **0.00** | −0.2123 |
| candidate | (c) arrival rule | 0.04 | **0.08** | **+0.04** | — |
| candidate | **total v1 → v2** | 0.04 | **0.08** | **+0.04** | −0.2128 |

(c)'s flips: baseline `region_goal-A-00`, `object_goal-A-00`, `object_goal-D-15`;
candidate `object_goal-A-00`. Collisions 0 in every cell.

Why not differenced against the frozen v1 rows: those were measured on
2026-08-05/06 code and four lanes have landed since (Lane D alone moved mean dtg
−0.027 m). They are carried in the artifact as
`historic_v1_rows_for_context_only` and are not subtracted from anything.

### Spec bridge — 9 of 25 episodes moved, each attributed

7 by (a) — the four region polygons (the north sidewalk was scored as
y ∈ [2.4, 3.6] against a scene sidewalk of y ∈ [2.2, 4.2], 0.8 m narrower) and
the three bench episodes (centre 3.0 → 3.045, footprint 0.7 → 0.733757).
2 by (b):

| episode | instruction | v1 anchor → v2 anchor |
|---|---|---|
| `nav-object_goal-B-05-0ee314d5` | walk towards the **streetlight** | `tree_1` → `lamp_post_1` |
| `nav-object_goal-D-15-109547e2` | walk towards the **tree** | `tree_1` → `tree_2` |

Both are fixed by *rules*, not row overrides: word-boundary class matching
(`"tree" in "walk towards the streetlight"` is `True` — "s\[tree\]tlight", the
entire B-05 defect) and visible-instance anchoring for definite references,
using the world's own 70°/12 m predicate, pinned equal to it by a test that
compares the two functions on the same inputs rather than just their constants.

### What (b) did to `false_arrival` — the point of the exercise

Lane D found the class was "not a measurement of arrival honesty at all" because
both rows in it were mis-specified episodes. Under v2 it reports something real:

| run | `false_arrival` | reading |
|---|---|---|
| baseline v1 (today's code) | 2 | both eval-spec defects |
| baseline **v2** | **1** — `object_goal-B-05` | **genuine**: asks for a lamppost, scored against a lamppost, still claims `arrived_verified` at **dtg 0.3164 m** outside the band |
| candidate v1 | 1 | eval-spec defect |
| candidate **v2** | **1** — `object_goal-D-15` | **genuine**: claims `arrived_verified` at **dtg 2.9178 m** — it walked to the *other* tree and verified against that |

`object_goal-D-15` under the **baseline** goes the other way: anchored to the
tree it can see, it arrives at **dtg 0.0** and is a clean success. The row that
opened U32 was, in the end, a correct navigator and a wrong question.

### Protocol

| requirement | evidence |
|---|---|
| old frozen rows byte-identical | ledger prefix sha256 identical before/after; pinned in `tests/test_nav_instruct_episodes_v2.py` |
| old episode files immutable | v1 digest `cf4d5384…`, pinned in two test modules |
| v2 is a new versioned artifact | own digest, own directory, manifest recording which corrections it carries |
| new rows marked | `baseline_version` + `arrival_rule` + `sr_frozen_rule` on both |
| continuity doc | `EPISODES_V2_CONTINUITY.md`, old→new mapping total and 1:1 (asserted) |
| eval-integrity tests pass against v2 | regeneration diff over the checked-in v2 files, oracle isolation (the v2 table *is* the derived section), visibility-predicate pin |
| no other frozen artifact moved | embodied (1250), duplex mirrors and BARN were neither read nor written |

**Backlog:** U31 and U32 closed-with-evidence in `backlog/UNVERIFIED.md`, each
with the residue named (U31: the runner still terminates one tick early, so
branch (b) still *assumes* the unobserved 0.9 s; U32: two genuine
`false_arrival` rows remain, undiagnosed, plus the identical `planter_1`/
`planter_2` ambiguity left deliberately unfixed because the re-freeze carries
three approved corrections and no fourth).

---

## V-3a — the scene-generalization split

`evals/nav_instruct/scene_gen.py` emits 5 frozen `val_unseen` scenes into
`configs/scenes/generated/`, each as **one artifact of three files**: the MJCF,
its semantics sidecar (re-emitted from `city_block.semantics.yaml` with only
`scene:` changed, and validated by the real loader before it is written), and its
derived scene-truth manifest with the acceptance record.

Rejection sampling, ProcTHOR-style, four filters: **round-trip** (the derived
table must agree with what the sampler wrote — the generator never asserts
geometry it did not read back through MuJoCo), **overlap** (furniture discs
disjoint at 0.35 m; buildings as *boxes*, because a bounding-circle test rejects
the frozen city block itself), **layout** (the crosswalk stays on the road), and
**navigability** (4-connected search at 0.25 m with obstacles inflated by
`RobotProfile.footprint_radius_m + 0.32 = 0.64 m`, from every episode start pose
to every landmark's stand-off band). Acceptance cost: 4 of 5 seeds accepted on
the first proposal, one on the second (a `layout` rejection).

The unseen pack is the **v2 minival regenerated against each scene's derived
table**, narrowed to the three scene-dependent families (15 episodes/scene).
`follow_owner`/`circle_owner` are excluded on purpose: their goals are
owner-anchored discs at a fixed position and would contribute the same number in
every scene. A test asserts the packs carry identical instructions, tiers and
start poses to the seen pack, and that their goals do move — so the gap is
scenes and cannot be episodes.

```
.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 --scenes all --mode candidate
```

| mode | val_seen SR | val_unseen mean SR (5) | **Δ SR** | val_seen dtg | val_unseen dtg | **Δ dtg** |
|---|---|---|---|---|---|---|
| baseline | 0.200 | 0.187 | **+0.013** | 12.918 | 13.571 | **+0.653 m worse unseen** |
| candidate | 0.067 | 0.133 | **−0.067** | 12.673 | 13.201 | **+0.528 m worse unseen** |

(The candidate row was measured twice, ~40 min apart, while `src/` was being
edited by other executors: SR identical both times, mean dtg 12.813 → 12.673
seen and 13.333 → 13.201 unseen, gap +0.520 → +0.528. The gap is stable across
that drift; the absolute numbers are not, and should not be quoted without the
tree they came from. The checked-in artifact is the second run.)

**Read honestly, and this is not the result the card expected.**

- **The SR gap is not resolvable at this scale.** 15 episodes per scene means one
  episode is 0.067 SR. The baseline gap is +0.013 (one fifth of one episode) and
  the candidate gap is *negative* — the unseen scenes scored **better**. Neither
  number is evidence of anything. Anyone quoting "the unseen gap is X" from this
  table is over-reading it.
- **The distance gap is consistent and is the informative number.** Mean
  distance-to-goal is worse on unseen scenes in **both** modes, by +0.65 m and
  +0.52 m, and the per-scene spread (13.15–14.13 m) does not overlap the seen
  value in the baseline. That is the expected direction and it is the honest
  headline.
- **Nothing was tuned.** The seeds were chosen once, the scenes were emitted
  once, and no parameter anywhere was changed after seeing these numbers.
- Collisions: **0** across all 12 scene-runs.

**Not claimed:** n = 1 run per cell (the runner is deterministic, so a repeat
adds nothing, but it is one run); 5 scenes is a small split (R2R's val_unseen is
11, so small is legitimate, but small is small); and the generated scenes are
block *variants*, not new environments — same vocabulary, same entity ids, same
robot. They test geometric generalization and nothing else.

---

## V-3b — metamorphic pairs, and the violation they found

`evals/nav_instruct/metamorphic.py` + `tests/test_nav_metamorphic.py`
(nightly tier: `PARCEL_NIGHTLY=1`; the pure transform half runs in the default
suite because a wrong transform makes every nightly verdict meaningless).

**Repeat variability, measured** (N=8, `go to the sidewalk`): mean **2.9e-5 m**,
sd **1.9e-5 m**. So the runner is effectively but not exactly deterministic, the
plan's z-test does have a scale, and a floor of one footprint radius (0.32 m)
sits on top of it so a z-test against a 2e-5 m sd cannot call float noise in a
90° rotation a defect.

### Rigid-transform equivariance — 4 of 6 cases hold exactly, 2 violate

| episode | mirror_y | rotate_90 |
|---|---|---|
| `nav-object_goal-A-00` (towards the lamppost) | **0.0000 m**, success True→True | **0.0000 m**, True→True |
| `nav-object_relative-A-00` (next to the bench) | **0.0000 m**, False→False | **0.0000 m**, False→False |
| `nav-region_goal-A-00` (**go to the sidewalk**) | **3.0196 m**, **True→False** | **3.0196 m**, **True→False** |

The violating episode arrives at dtg 0.0 in the frozen block and reports
`semantic_target_unreachable` **without moving at all** in both transformed
scenes. The identity transform through the same ElementTree round-trip arrives
normally (184 ticks, dtg 0.0), so the machinery is not the cause; the identical
3.0196 m under two different transforms says one cause, not two.

Region goals are also the only family with two same-label instances
(`sidewalk`/`sidewalk_south`), which a mirror swaps sides — that is where to
look first, and it is Lane D's open "does *the* sidewalk mean a specific polygon
or any sidewalk?" question. **Pointing is not attributing and this round does
not attribute it**; the two cases are pinned `xfail(strict=False)` carrying the
measurement, so they flip loudly when that lands. `src/parcel_robot/**` was not
touched.

### Detector-dropout monotonicity — holds

Single-variable rungs (dropout only; no range sigma, no false positives), 3
episodes × 3 perception seeds per rung:

| dropout | SR mean | per seed |
|---|---|---|
| 0.0 | **0.667** | 0.667, 0.667, 0.667 |
| 0.2 | **0.556** | 0.667, 0.333, 0.667 |
| 0.5 | **0.333** | 0.000, 0.667, 0.333 |

Monotone. **The first version of this test was wrong and is worth recording:**
with one seed it read 2 → 1 → 2 successes and *failed*, because at n=3 episodes a
single seed moves the count by a whole episode. The relation is a claim about a
distribution, so it is now judged on the seed mean with a one-episode tolerance.
Three seeds is still small.

---

## V-3c — the mutation panel

`scripts/mutation_panel.py`, nightly tier. Six defects from the plan, seeded one
at a time by **monkeypatch/config injection only — never a committed source
edit**. Verdict is three-valued: `killed` (reddened a named harness check),
`equivalent` (the run was *identical* to clean, so the defect was never
exercised — no claim made), `survived` (the run changed and nothing noticed).

| mutation | verdict | harness checks reddened |
|---|---|---|
| `arrival_radius_x2` | killed | `final_poses_within_tolerance` |
| `reactive_gate_disabled` | killed | `no_false_arrival`, `mean_dtg_within_tolerance`, `final_poses_within_tolerance` |
| `pose_offset_0m5` | killed | `final_poses_within_tolerance` |
| `inverted_relation` | killed | `no_authority_disagreement`, `success_set_identical`, `mean_dtg_within_tolerance`, `failure_histogram_identical`, `final_poses_within_tolerance` |
| `dropped_detections` | killed | `success_set_identical`, `mean_dtg_within_tolerance`, `failure_histogram_identical`, `final_poses_within_tolerance` |
| `doubled_envelope` | killed | `success_set_identical`, `failure_histogram_identical`, `final_poses_within_tolerance` |

**PANEL PASSED — 6/6, no survivors.**

**It did not pass on the first run, and the two rounds of failure are the most
useful output of this card.**

1. **Three mutants were silently not mutating.** `dropped_detections` patched the
   *defining* module while the name is *bound* in `headless_city`;
   `doubled_envelope` had to patch four modules, not two. A mutation that does
   not mutate reads as a surviving mutant, i.e. a false alarm about harness
   blindness. `doubled_envelope` now raises at construction if its field filter
   matched nothing, and a test asserts every mutation restores what it patched.
2. **`reactive_gate_disabled` was an equivalent mutant, and the reason is a
   coverage finding about NAV_INSTRUCT itself.** Instrumenting
   `apply_reactive_safety` over the whole v2 minival: it modifies the command on
   **exactly three episodes** — `region_goal-D-15` (184/200 ticks),
   `object_goal-B-05` (57/100), `object_goal-D-15` (54/93) — and on **no other
   episode at all**. 22 of 25 NAV_INSTRUCT episodes cannot test the reactive
   safety gate. The panel's episode list now includes one of the three, and the
   selection rationale is in the source and in the report.

That is **coverage selection, not tuning**: no robot parameter was chosen from a
result; the panel needs episodes that reach the code each mutant touches, or it
measures nothing. The same instrumentation pass is why `nav-region_goal-A-00`
(the minival's longest traverse at 184 ticks) is in the list — a 0.5 m pose
error needs distance to accumulate over, and on short episodes `pose_offset_0m5`
moved final poses by 4 cm.

**Not claimed:** the checks are the checks *this panel* names, not every
assertion in the repo; a mutant killed here is a mutant one paired-comparison
harness would catch, not proof that CI would.

---

## Verification

| check | result |
|---|---|
| eval-lane test modules | **130 passed, 7 skipped** (`test_nav_instruct_{scene_gen,episodes_v2,generator,scene_truth,rescoring}`, `test_nav_metamorphic`, `test_arrival_authority_differential`, `test_k0_arrival_authority`) |
| nightly metamorphic tier (`PARCEL_NIGHTLY=1`) | **16 passed, 2 xfailed** (the two pinned equivariance cases) |
| mutation panel | **6/6 killed, 0 survivors** |
| `ruff check` on every file this round touched | **clean** |
| frozen v1 report JSONs | byte-identical (`1871a938…`, `0f6cac9b…`) |
| frozen ledger prefix (9 lines) | byte-identical (`dab60242…`) |
| `scene_truth.json` | byte-identical (`43688b1c…`) |
| frozen v1 minival digest | `cf4d5384…` — unchanged |
| v2 artifacts + bridge table | present (`episodes/v2/`, `results/bridge_v1_v2.json`, `EPISODES_V2_CONTINUITY.md`) |
| watch script | one case run end to end headless, PASSED with metrics |
| new tests | **+47** (`test_nav_instruct_episodes_v2` 18, `test_nav_instruct_scene_gen` 29 incl. the panel's own machinery, `test_nav_metamorphic` 11 default + 8 nightly) |

### The full default suite

`pytest tests/ -q` on the final tree:
**`9 failed, 2737 passed, 14 skipped, 3 xfailed, 1 xpassed` (899 s).**
Every failure triaged individually:

| failure | count | disposition |
|---|---|---|
| `test_nav_instruct_scene_gen.py` | 5 | **mine, fixed.** The run started before the fix landed: an `importlib` load of the panel script that did not register it in `sys.modules` (which breaks dataclass module resolution on 3.14) and a filter test that hunted for a rejection in the sampler's stream instead of building a bad proposal. Both replaced; the module is **29 passed** in isolation and in a combined run with the file below. |
| `test_authority_no_literal_drift.py::test_allowlist_is_not_stale…` | 1 | **not mine** — Lane A's `authority.py`, which was being edited during the run. **Passes now**: 51 passed with `test_nav_instruct_scene_gen.py` in one invocation. |
| `test_duplex_v1.py` ×3 | 3 | **not mine, and reproducible.** `test_nav_regression_pins_post_speed_raise_rows` fails `follow_success '9/9' == '8/9'`: another executor appended two follow-bench rows to `evals/companion_nav/results/ledger.jsonl` and has `evals/companion/duplex_v1/run_duplex_v1.py` modified in the tree. Nothing in this round reads or writes `evals/companion/**` or `evals/companion_nav/**`. |

**One `xpassed`, observed and unattributed.** It is in the live-sim tier and the
run shared the machine with up to eight concurrent `pytest tests/` processes.
Naming an xfail flip off a contended run is exactly the claim this document
exists not to make; it needs a quiet machine.

**Two transient states were hit and are recorded because they will be hit
again.** One full-suite attempt aborted with **79 collection errors**
(`NameError: DEFAULT_SAFETY_ENVELOPE`) and one `test_nav_metamorphic.py` run
died on `NameError: _closest_point_on_segment` in `instructnav/relations.py`.
Both were half-written files from a concurrent editor —
`parcel_robot.authority` imported cleanly 90 s later, and `relations.py` had
been written 50 s before the failure — and both passed on re-run. **Any red in a
full-suite run from this window should be re-measured on a quiet tree before it
is attributed to anyone**, including to this lane.

---

## Files touched

**New (evals):** `evals/nav_instruct/bridge_v1_v2.py`,
`evals/nav_instruct/scene_gen.py`, `evals/nav_instruct/unseen_split.py`,
`evals/nav_instruct/metamorphic.py`,
`evals/nav_instruct/EPISODES_V2_CONTINUITY.md`,
`evals/nav_instruct/episodes/{v1,v2}/` (52 files),
`evals/nav_instruct/results/{bridge_v1_v2,scene_split_baseline,scene_split_candidate,mutation_panel}.json`,
two v2 report JSONs.

**Changed (evals):** `evals/nav_instruct/generator.py` (versioned episode sets;
v1 path byte-frozen), `evals/nav_instruct/runner.py` (arrival rule, `--scene`,
both verdicts per episode), `evals/nav_instruct/run_nav_instruct_v1.py`
(`--episode-version`, `--arrival-rule`, `--scene`, `--scenes`),
`evals/nav_instruct/scene_truth.py` (`derived_landmark_table`,
`V2_LANDMARK_IDS`), `evals/nav_instruct/rescore.py` (`_promoted` →
`promoted_derived_score`, now shared with the runner),
`evals/nav_instruct/README.md`, `evals/nav_instruct/results/ledger.jsonl`
(2 rows appended; prefix untouched).

**New (scripts):** `scripts/watch_nav_evals.py`, `scripts/watch_nav_evals.sh`,
`scripts/mutation_panel.py`.

**New (configs):** `configs/scenes/generated/` — 5 scenes × 3 files.

**New (tests):** `tests/test_nav_instruct_episodes_v2.py`,
`tests/test_nav_instruct_scene_gen.py`, `tests/test_nav_metamorphic.py`.

**Records:** `backlog/UNVERIFIED.md` (U31, U32),
`docs/DEVELOPMENT_STACK.md` (one paragraph on the watch script), this file.

**Not touched:** `src/parcel_robot/**`, `tests/test_voice_nav_e2e.py`,
`tests/test_embodied_plan_eval.py`, `tests/test_authority*`,
`src/parcel_robot/scenes/city_block.xml`, `evals/companion/**`,
`evals/external/**`, `evals/walk_with_me/**`.

---

## Non-claims

1. **The re-freeze is not a capability improvement.** Corrections (a) and (b)
   gained zero episodes in either mode. All the SR movement is (c), which is a
   measurement correction. Nothing about the robot got better this round.
2. **`hold-or-trace-end-v1` still assumes an unobserved hold.** Making it the
   default made the assumption labelled, not verified.
3. **The unseen split's SR gap is noise at n=15.** Only the distance gap is
   readable, and it is one run per cell.
4. **The equivariance violation is measured, not attributed.** The region family
   is where the two same-label instances live; that is a lead, not a diagnosis.
5. **The mutation panel's checks are its own.** Killing a mutant proves a paired
   comparison would notice, not that CI would.
6. **The generated scenes have never been looked at by a human.** They compile,
   they pass four filters, and their semantics sidecars load. Nobody has opened
   one in a viewer to check it looks like a street.
7. **The watch script's windowed path is unverified.** Only `MUJOCO_GL=egl` was
   exercised here.
8. **The `planter_1`/`planter_2` ambiguity is still live** and is the same defect
   class as the two rows v2 fixed. It was left alone on purpose.
9. **The full default suite did not exit clean in this window** — 9 failed, of
   which 5 were mine and are fixed, 1 was a concurrent-edit transient that now
   passes, and 3 belong to another executor's follow-bench work. That triage is
   attribution by re-run, not by assertion, and it was done on a machine running
   up to eight concurrent test processes. A clean-tree re-run is still owed.
