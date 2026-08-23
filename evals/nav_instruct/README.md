# NAV_INSTRUCT

Seeded instruction-navigation eval: five families × tiers A–E.

```bash
# the current frozen baseline (episode set v4, 2026-08-11 re-freeze)
.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
  --minival --mode baseline --episode-version v4

# replay a superseded set exactly (v1, v2 and v3 are immutable)
.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
  --minival --mode baseline --episode-version v1
```

Hard gate: freeze a refusal-heavy baseline **before** grounding rewire (N-O2).

## Episode sets

| set | digest | landmark table | class match | definite reference | arrival rule | `next_to` band | `follow_owner` radius |
|---|---|---|---|---|---|---|---|
| `v1` (frozen 2026-08-05/06, **immutable**) | `cf4d5384…` | `transcribed` | substring | fixed instance | `frozen-hold-v1` | anchor **centre** | `1.8` literal |
| `v2` (re-freeze 2026-08-07, **immutable**) | `a17c04db…` | `derived` | word boundary | instance visible from the start pose | `hold-or-trace-end-v1` | anchor **centre** | `1.8` literal |
| `v3` (re-freeze 2026-08-09, **immutable**) | `919a0fea…` | `derived` | word boundary | instance visible from the start pose | `hold-or-trace-end-v1` | anchor **SURFACE** | `1.8` literal |
| `v4` (re-freeze 2026-08-11) | `4113607b…` | `derived` | word boundary | instance visible from the start pose | `hold-or-trace-end-v1` | anchor **SURFACE** | **DERIVED**, 2.13 m |

Every default in `generator.py` still resolves to **v1**; any later set must be
asked for by name. The old→new mappings, the per-episode provenance and the
measured bridges are in [`EPISODES_V2_CONTINUITY.md`](EPISODES_V2_CONTINUITY.md)
and [`EPISODES_V3_CONTINUITY.md`](EPISODES_V3_CONTINUITY.md); v4's are in
`bridge_v3_v4.py` and `scrum/20260809/task_15/E8_V4_REFREEZE_STATUS.md`.

v3 is the first re-freeze triggered by a change in `src/` rather than in the
eval: `NEXT_TO_BAND_M` became a distance to the anchor's **surface**
(`instructnav.scoring.next_to_band_from_centre`), so a `next_to` goal's band is
`(0.4 + R, 1.5 + R)` from the centre. v1/v2 keep the centre-anchored encoding
through `generator._superseded_centre_anchored_next_to_region`, which exists
only to regenerate them byte-identically.

v4 is the first re-freeze triggered by a change in the **authority**. The
owner-authorized person-clearance retune (2026-08-10) raised
`FollowConfig.desired_distance_m` 1.60 → 1.85, so a compliant follow controller
holds out to `1.85 + 0.18 = 2.03 m` from the owner — outside v3's 1.8 m disc.
The controller therefore claimed `at_follow_distance` while K0 said no:
`false_arrival` on three of five `follow_owner` episodes, and the v3 episode was
unsatisfiable by any compliant robot. v4 stops writing the radius as a literal
and derives it from the controller's own hold band,
`(desired_distance_m + distance_deadband_m) + OWNER_STAND_OFF_MARGIN_M` =
**2.13 m**, so the next clearance retune reddens the digest pin instead of
surfacing as a false arrival three lanes later. `circle_owner` stays at 2.2 m:
nothing feeding the orbit ring moved. v1/v2/v3 keep the 1.8 m literal through
`generator.FOLLOW_GOAL_RADIUS_BY_REFERENCE`, so every row ever measured against
them still means what it meant.

## Surface ground truth (artifact v2)

`scene_truth.json` describes every object as a **centre plus a circumscribed
radius**. No RGB-D sensor can measure that. The 2026-08-21 mapping bench
(`scrum/20260821/perception/bench_mapping.md`) built a semantic map from 120
rendered RGB-D frames and found building entries landing **1–3 cm from the
visible facade and 1.2–1.7 m from the geom centre, 6/6** in its oracle arm. A
depth camera sees surfaces, never centroids — so grading a *correct* pipeline
against the centre fails it. This is the same reasoning the v3 re-freeze already
accepted for `next_to` bands (`instructnav.scoring.next_to_band_from_centre`),
carried into the answer key.

Artifact v2 therefore adds two sibling sections. `derived`, `transcribed`,
`transcription_deltas` and every frozen digest are **untouched**.

| section | what |
|---|---|
| `surfaces` | per entity: `near`-class places get `parts`, the nearest-surface set (one footprint primitive — `rect` or `circle` — per constituent geom); `inside`-class places get `interior_polygon`, byte-identical to that entity's `derived` polygon |
| `surface_convention` | the versioned rules: what each measure means, the per-class pass rule, and the null-control requirement |

**Which class is measured how** is read from
`parcel_robot.navigation.arrival_semantics.localization_target` — the table that
already owns what arrival means per class — so the answer key and the robot
cannot disagree about what "the building" is. Regions are `interior`; everything
else is `surface`.

**Every localization claim carries a null control.** The same bench disclosed
that its own containment metric was uninformative for large regions: sidewalk
and crosswalk scored **0.00 m against a *random* map** (p=1.00, p=0.52).
`surface_scoring.LocalizationClaim` therefore cannot be constructed without a
`NullControl`, and `verdict` is a property, not a field:

| verdict | meaning |
|---|---|
| `pass` | the statistic passed **and** beat the null at α=0.05 |
| `fail` | the statistic did not pass |
| `uninformative` | the statistic passed but did **not** beat the null — may not be reported as a pass |

Per-class rules:

* **`surface`** — `surface_error_m` = min unsigned distance from the answer point
  to any part's footprint outline; passes at `RECOGNITION_LOCALIZATION_BUDGET_M`
  (0.30 m, imported from `cam_detector.py`, never re-typed). Unsigned: a point
  buried inside a solid is as wrong as one outside it.
* **`interior`** — containment of the answer point (the unchanged R10 arrival
  predicate) **plus** `evidence_inside_fraction ≥ 0.5` over the answering
  entry's own supporting points. The second term is what a random map cannot
  pass; a single point never can, because a random point is inside a large
  region with probability equal to its area share.

`also_satisfied_by` widens both the statistic and the null to the other
instances of the queried class ("the building" is six buildings): a null that
may only hit one acceptable answer understates how easy the question was.

## Files

- `generator.py` — seeded episode matrix, both versions. Its landmark table is
  read from `scene_truth.json`, never typed in.
- `scene_truth.py` / `scene_truth.json` — generated scene-truth artifact
  (instrument 6). Regenerate with
  `.parcel/bin/python -m evals.nav_instruct.scene_truth --regenerate`;
  `--check` exits non-zero on drift. Hand edits are a red build.
  **Artifact v2** additionally carries `surfaces` + `surface_convention` — see
  [Surface ground truth](#surface-ground-truth-artifact-v2) below.
- `surface_scoring.py` — the per-class perception scoring rules and the
  **required** null control (card PG-2). Pure stdlib; nothing in `src/` imports
  it, and `tests/test_scene_surface_truth.py` reddens if anything starts to.
- `episodes/v1/` … `episodes/v4/` — the frozen episode sets, written out, one
  JSON per episode plus a manifest carrying the digest and the corrections the
  set carries. A file that differs from a fresh generation is a red build.
- `runner.py` — the harness. Every episode records both arrival verdicts
  (`scorer_arrival` / `system_arrival`) and their `authority_category`
  (instrument 5), and both arrival rules (`score.success` under the active rule,
  `frozen_rule_success` under v1's).
- `rescore.py` — derived re-scoring of persisted traces (U31). Writes
  `kind="derived_rescoring"` ledger rows; never touches frozen rows.
  `.parcel/bin/python -m evals.nav_instruct.rescore --all --append-ledger`
- `bridge_v1_v2.py` — the v1→v2 re-freeze bridge: what each of the three
  corrections moved, separately, all cells measured on one tree.
  `.parcel/bin/python -m evals.nav_instruct.bridge_v1_v2 --run`
- `bridge_v2_v3.py` — the v2→v3 bridge. One correction, so no attribution
  problem: it reports which episodes moved (only `object_relative`), the
  measured deltas over four cells in one process, and whether the prior card's
  read-only prediction held.
  `.parcel/bin/python -m evals.nav_instruct.bridge_v2_v3 --run`
- `bridge_v3_v4.py` — the v3→v4 bridge. One correction again, plus the 2x2 that
  separates the DATA axis (the resize) from the CODE axis (what landed in
  `src/` since v3 was frozen): false arrivals must exist only in
  (v3 episodes × new code), and (v3 episodes × old code) must reproduce the
  committed frozen-baseline row bit-for-bit.
  `.parcel/bin/python -m evals.nav_instruct.bridge_v3_v4 --run`
- `scene_gen.py` — procedural block generator for the val_unseen split
  (instrument 1). ProcTHOR-style rejection sampling: round-trip, overlap,
  support, A*-navigability at profile-derived clearance. Emits scene + semantics
  sidecar + scene-truth manifest per seed into `configs/scenes/generated/`.
  `--emit` writes, `--check` diffs against a fresh generation.
- `unseen_split.py` — val_seen vs val_unseen. Same episode logic against each
  scene's derived truth; the headline is the **gap**, not either side.
  `.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 --scenes all`
- `metamorphic.py` — rigid-transform equivariance + detector-dropout
  monotonicity (instrument 3). Driven by `tests/test_nav_metamorphic.py`;
  nightly tier (`PARCEL_NIGHTLY=1`).
- `../../scripts/mutation_panel.py` — the mutation-of-the-evals panel
  (instrument 6): six seeded defects, monkeypatch only, a surviving mutant fails
  the panel.

## Results

`results/ledger.jsonl` is append-only. Every measured row carries
`baseline_version` and `arrival_rule`, so two rows can never be differenced
without seeing whether they are comparable.

**Append on purpose (card GATE-0b, `scrum/20260822/task_30`).** Append-only
also means *every row you add is permanent*, so a run that is not provenance
must say so:

| you are | run it as |
|---|---|
| recording a measurement worth citing | `--minival --mode candidate …` (unchanged; the row lands here) |
| verifying, re-measuring, or running a seeded tree | `--no-ledger` |
| wanting the row, but not in the tracked file | `--ledger <path>` (or `PARCEL_NAV_LEDGER=<path>`; `off` there means `--no-ledger`) |

A run started **from inside pytest** that says none of the above does not
append here: it prints the path it left alone and the flag that would have
recorded it. Nothing refuses — the matrix still runs and the report is still
written — and an explicit `--ledger <this file>` is honoured, because a person
who typed the path is not overruled by a heuristic.

**THE ANNOTATION RULE.** A row that reaches this file from anything other than
an ordinary measured run — an audit re-run, a diagnostic, a re-scoring — is
annotated in `results/README.md` with its `report_id`, who wrote it and why,
in the same pass that writes it. Two rows arrived unannotated on 2026-08-22
from card ROAM-1's verification minivals (one from a tree with `time_s` seeded
out) and had to be identified afterwards by `report_id` and restored by hand
(`scrum/20260822/AUDIT_WEEK1_FABLE.md` §ROAM-1 finding 4). A row nobody can
attribute is worse than no row: it is provenance that lies.
`tests/test_nav_instruct_ledger_guard.py` pins the mechanism; the annotation is
a discipline, and this is where it is written down. `results/bridge_v1_v2.json`,
`results/scene_split_{mode}.json` and `results/mutation_panel.json` are
diagnostics and are never baselines (`frozen_baseline: false`); so are
`results/bridge_v2_v3.json` and `results/bridge_v3_v4.json`.
