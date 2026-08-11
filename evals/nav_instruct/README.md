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

## Files

- `generator.py` — seeded episode matrix, both versions. Its landmark table is
  read from `scene_truth.json`, never typed in.
- `scene_truth.py` / `scene_truth.json` — generated scene-truth artifact
  (instrument 6). Regenerate with
  `.parcel/bin/python -m evals.nav_instruct.scene_truth --regenerate`;
  `--check` exits non-zero on drift. Hand edits are a red build.
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
without seeing whether they are comparable. `results/bridge_v1_v2.json`,
`results/scene_split_{mode}.json` and `results/mutation_panel.json` are
diagnostics and are never baselines (`frozen_baseline: false`); so are
`results/bridge_v2_v3.json` and `results/bridge_v3_v4.json`.
