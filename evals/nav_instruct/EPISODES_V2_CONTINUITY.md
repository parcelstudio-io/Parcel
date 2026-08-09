# NAV_INSTRUCT episode set v1 → v2 — continuity record

**Date:** 2026-08-07 · **Owner approval:** the bundled re-freeze
("proceed with your plan") · **Scope: exactly three corrections, and no fourth.**

v1 is **immutable and untouched**. Its digest is still
`cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf`, its two
frozen ledger rows are byte-identical, its two report JSONs are byte-identical,
and `evals/nav_instruct/episodes/v1/` is that exact set written out. Every
default in `generator.py` still resolves to v1; v2 has to be asked for by name.

| | v1 | v2 |
|---|---|---|
| episode digest | `cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf` | `a17c04dbec43a1749386c304060fb479a71f27d4b51b8c1b0fbb949753fc563d` |
| episode files | `evals/nav_instruct/episodes/v1/` | `evals/nav_instruct/episodes/v2/` |
| landmark table | `scene_truth.json` → `transcribed` | `scene_truth.json` → `derived` |
| class matching | substring | word boundary |
| definite reference | fixed first instance | instance visible from the start pose |
| arrival rule | `frozen-hold-v1` | `hold-or-trace-end-v1` |
| episode ids | 25 | the **same** 25 |

The id set is unchanged, so the old→new mapping is total and 1:1: every v1 row
has exactly one v2 row with the same id, and `bridge_v1_v2.py` asserts it
(`spec_bridge.id_mapping_is_total`).

## The three corrections

**(a) Derived scene truth.** The generator's landmark table was hand
transcribed from `city_block.xml` and is wrong in seven fields across five
entities (Wave 0, W0-D). The north sidewalk it scored against was
y ∈ [2.4, 3.6] while the sidewalk in the scene is y ∈ [2.2, 4.2] — 0.8 m
narrower, so a robot standing on the sidewalk could be scored "outside" it.
v2 reads the `derived` section: the scene's own geometry, regenerated from the
MJCF and diffed by a PR-tier test.

**(b) Episode spec fixes.** Two rows paired an instruction with a goal anchored
to a different, unobservable entity (Lane D findings 1 and 3). Both are fixed by
*rules*, not by row-level overrides:

- **word-boundary class matching.** `"tree" in "walk towards the streetlight"`
  is `True` — "s\[tree\]tlight". That single substring test is the whole of the
  `nav-object_goal-B-05` defect: the episode asked for a streetlight and scored
  against `tree_1` 5.3 m away. v2 matches `\btree\b`.
- **visible-instance anchoring.** The scene holds two geometrically identical
  trees. `nav-object_goal-D-15` says "walk towards **the** tree" and v1 anchored
  it to `tree_1`, which is not in frame from the start pose, while `tree_2` is.
  v2 resolves a definite object reference to the instance **visible from the
  episode's start pose** — same predicate, same 70° half-FOV and 12 m range the
  world reports observations through, pinned equal to it by test. Ties and
  "nothing visible" fall back to nearest-then-id, deterministically.

  Instance choices that are *deliberate* are not overridden: tier C names the
  far lamppost precisely to force a search, and the rule leaves it alone.

**(c) Arrival rule.** `hold-or-trace-end-v1` (documented in `rescore.py`)
becomes the runner's default: arrived iff the frozen 1.0 s inside-and-stopped
hold accumulates **or** the trace ends inside-and-stopped and was not cut off by
the step limit. The runner terminates one 0.1 s tick after `arrived_verified`,
so under the old rule the hold was *unobservable, not unmet* — that is U31.
Every v2 episode still records `frozen_rule_success`, so the superseded rule is
never hidden.

## Per-episode mapping — every row that moved

9 of 25 rows moved; 16 are unchanged. Attribution is exact because the bridge
generates a third, intermediate set (`v1a-scene-truth-only` = correction (a)
with v1's spec logic) and diffs v1 → v1a → v2.

| episode id | instruction | moved by | v1 anchor → v2 anchor | what changed |
|---|---|---|---|---|
| `nav-region_goal-A-00-1c735162` | go to the sidewalk | (a) | sidewalk → sidewalk | polygon y ∈ [2.4, 3.6] → [2.2, 4.2] |
| `nav-region_goal-B-05-586317e4` | walk onto the sidewalk | (a) | sidewalk → sidewalk | same polygon |
| `nav-region_goal-C-10-138643ba` | go to the pavement | (a) | sidewalk_south → sidewalk_south | polygon y ∈ [−3.6, −2.4] → [−3.75, −2.25] |
| `nav-region_goal-D-15-1b8b2361` | go to the crosswalk | (a) | crosswalk → crosswalk | polygon x ∈ [2.3, 3.9] → [2.35, 3.85] |
| `nav-object_relative-A-00-3efbba45` | sit next to the bench | (a) | bench_1 → bench_1 | centre (−2.5, 3.0) → (−2.5, 3.045); footprint 0.7 → 0.733757 m |
| `nav-object_relative-B-05-7d441aee` | wait by the bench | (a) | bench_1 → bench_1 | same |
| `nav-object_relative-C-10-0d3f5ebd` | stand next to the seat | (a) | bench_1 → bench_1 | same |
| `nav-object_goal-B-05-0ee314d5` | walk towards the **streetlight** | (b) | **tree_1 → lamp_post_1** | centre (−5.0, 3.15) → (0.2, 3.15); L 7.5 → 3.5 m |
| `nav-object_goal-D-15-109547e2` | walk towards the **tree** | (b) | **tree_1 → tree_2** | centre (−5.0, 3.15) → (5.0, 3.1); L 7.5 → 7.0 m |

Rows that (a) did **not** move, and why: `lamp_post_1`, `lamp_post_2` and
`planter_1` are byte-equal between the transcribed and derived tables (that
equality is what proves the derivation path is real, not a rewrite);
`tree_1`'s radius delta (0.45 → 0.58 m) does not reach any goal because the
`towards` band is anchor-position-only; tier E goals are off-map discs by
construction; `follow_owner`/`circle_owner` goals are owner-anchored discs with
no landmark input.

## Bridge — what each correction actually moved, measured

`evals/nav_instruct/results/bridge_v1_v2.json` (regenerate:
`.parcel/bin/python -m evals.nav_instruct.bridge_v1_v2 --run`).

All six cells (2 modes × 3 versions) were measured **on today's tree, in one
pass**. This is deliberate: the frozen v1 rows were measured on 2026-08-05/06
code and four lanes have landed since (Lane D alone moved mean dtg by
−0.027 m), so differencing a fresh v2 run against a stale v1 row would charge
four lanes of work to the re-freeze. The historical rows are carried in the
artifact, labelled `historic_v1_rows_for_context_only`, and are not differenced.

(a) and (b) are read with **both sides under the frozen hold rule**, so neither
can borrow credit from (c). (c) is read **inside the v2 run** — same traces,
two rules.

| mode | correction | SR before | SR after | Δ SR | Δ mean dtg (m) |
|---|---|---|---|---|---|
| baseline | (a) derived scene truth | 0.04 | 0.04 | 0.00 | −0.0075 |
| baseline | (b) episode spec fixes | 0.04 | 0.04 | 0.00 | −0.4156 |
| baseline | (c) arrival rule | 0.04 | **0.16** | **+0.12** | — |
| baseline | **total v1 → v2** | 0.04 | **0.16** | **+0.12** | −0.4231 |
| candidate | (a) derived scene truth | 0.04 | 0.04 | 0.00 | −0.0005 |
| candidate | (b) episode spec fixes | 0.04 | 0.04 | 0.00 | −0.2123 |
| candidate | (c) arrival rule | 0.04 | **0.08** | **+0.04** | — |
| candidate | **total v1 → v2** | 0.04 | **0.08** | **+0.04** | −0.2128 |

Read honestly:

- **(a) and (b) change no success.** Not one episode is gained or lost by
  either. They move geometry (mean dtg) and they move *what a row means*; they
  do not move the headline. Anyone hoping the re-freeze would raise SR should
  read the (a) and (b) rows twice.
- **All of the SR movement is (c)**, and (c) is a measurement correction, not a
  capability gain. The baseline's +0.12 is three episodes whose 1.0 s hold the
  runner never gave them a chance to accumulate.
- **The candidate's derived SR is 0.08 here, against 0.16 in the Wave 0
  re-scoring of the v1 traces.** These are different measurements: W0 re-scored
  *2026-08-06 traces*; this is a *fresh run on today's code*. The difference is
  four lanes of behaviour change, not the re-freeze.
- The baseline now scores 0.16 against the candidate's 0.08. That is a real
  ordering inversion on today's tree and it is **not** explained by anything in
  this document. It belongs to whoever owns the candidate's recovery path.

### What (b) did to the `false_arrival` class — the point of the whole exercise

Lane D's finding was that `false_arrival` was "not currently a measurement of
arrival honesty at all", because both rows it contained were mis-specified
episodes. Under v2 that is fixed, and the class immediately reports something
real:

| run | `false_arrival` rows | reading |
|---|---|---|
| baseline v1 (today's code) | 2 — `object_goal-B-05`, `object_goal-D-15` | both eval-spec defects |
| baseline v2 | **1 — `object_goal-B-05`** | **a genuine one.** The episode now asks for a lamppost and is scored against a lamppost; the mission still claims `arrived_verified` at **dtg 0.3164 m** outside the towards band. |
| candidate v1 (today's code) | 1 | spec defect |
| candidate v2 | **1 — `object_goal-D-15`** | **a genuine one.** "The tree" is now anchored to the tree in frame; the candidate claims `arrived_verified` at **dtg 2.9178 m**, i.e. it walked to the *other* tree and verified against it. |

And `nav-object_goal-D-15` under the **baseline** goes the other way: with the
goal anchored to the tree the robot can see, it arrives, dtg **0.0**, and is a
genuine success. One row moved from "false arrival" to "success" purely by
being asked the question it was supposed to be asked.

**The plan's stratum-2 gate ("zero `false_arrival` rows at T0/T1") is now a
measurable gate.** It reads 1 on each mode, and both rows are real.

## Protocol compliance

| requirement | evidence |
|---|---|
| old frozen rows byte-identical | ledger first 9 lines sha256 `dab60242975a86f26e0518571158c3f3bd8191f16623f8f51cc8b80c7f1f2fe0`, before and after |
| old report JSONs immutable | `nav-instruct-v1-baseline-20260805T070524Z.json` `1871a938…`, `nav-instruct-v1-candidate-20260806T070335Z.json` `0f6cac9b…` — unchanged |
| v1 episode set immutable | digest `cf4d5384…`, pinned in two tests |
| v2 is a new versioned artifact | digest `a17c04db…`, own directory, own manifest with provenance |
| new rows marked | `baseline_version: "v2"`, `arrival_rule: "hold-or-trace-end-v1"` on both ledger rows |
| eval-integrity tests pass against v2 | `tests/test_nav_instruct_episodes_v2.py` — regeneration diff over the checked-in v2 episode files, oracle isolation (the v2 table *is* the derived section, not a copy), visibility-constant pin |
| no other frozen artifact moved | embodied (1250), duplex mirrors and BARN were not read or written by anything in this round |

## What this re-freeze does NOT claim

1. **It is not a capability improvement.** Corrections (a) and (b) gained zero
   episodes. (c) is a measurement fix. Nothing about the robot got better.
2. **`hold-or-trace-end-v1` still assumes an unobserved hold.** Branch (b) of
   the rule credits a robot that was stopped inside the goal when the recording
   ended with the remaining 0.9 s it never demonstrated. The honest fix is still
   the runner change (keep stepping after a terminal stop); this re-freeze makes
   the assumption the *default* and labelled, not verified.
3. **`planter_1`/`planter_2` is the same defect and is still open.**
   "go next to the planter" (`nav-object_relative-D-15`) is as definite and as
   plural as "the tree", and `planter_1` is equally not in frame from that
   episode's start pose. It is not fixed here because `planter_2` was
   deliberately left out of the v2 landmark id set — this re-freeze carries the
   three approved corrections and no fourth. Recorded in `backlog/UNVERIFIED.md`.
4. **v1 and v2 numbers are not comparable to each other by subtraction** unless
   both were measured on the same tree. The bridge is the only comparison in
   this repo that satisfies that; anything else is a category error.
5. **The bridge measured n = 1 per cell.** The runner is deterministic (Lane D
   proved byte-identical repeat runs), so a repeat adds nothing — but it is one
   run, not a distribution.
