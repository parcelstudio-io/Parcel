# NAV_INSTRUCT_V1 results

Headless instruction-navigation matrix. Ledger rows are append-only in
`ledger.jsonl`. The frozen baseline (pre-N-O2 grounding) lives at
`scrum/20260804/task_6/freeze/nav-instruct-baseline.json`.

## Row kinds

- `kind: "measured_run"` (or absent, on rows written before Wave 0) — a real
  run of the harness. `frozen_baseline: true` marks a baseline row.
- `kind: "derived_rescoring"` — **not a run.** A re-scoring of an existing
  run's persisted traces under a different scoring rule, written by
  `evals/nav_instruct/rescore.py` and linked to its source by `parent_run_id`.
  Derived rows never freeze anything and never replace the row they derive
  from; the measured row above them stays byte-identical.

Today's derived rows apply `hold-or-trace-end-v1` (U31): the frozen 1.0 s
arrival hold **or** a trace that ends inside-the-goal-and-stopped without
hitting the step limit. Read `sr_frozen_rule` vs `sr_derived_rule` on the same
`episode_digest` — the pairing is the point.

Regenerate with:

    .parcel/bin/python -m evals.nav_instruct.rescore --all --append-ledger

## Baseline versions

From 2026-08-07 every `measured_run` row carries `baseline_version`
(`v1` / `v2`) and `arrival_rule`. **Two rows may only be differenced when both
match**, because v2 changed the episode goals *and* the arrival rule. The v2
rows also carry `sr_frozen_rule` — what v1's hold rule would have said about the
same traces — so correction (c) is isolated inside each row.

`v1` rows are historical and immutable: the first nine ledger lines are pinned
by sha256 in `tests/test_nav_instruct_episodes_v2.py`. The per-correction
comparison lives in `bridge_v1_v2.json` and
`../EPISODES_V2_CONTINUITY.md`; it is the only v1-vs-v2 comparison in this repo
whose cells were all measured on one tree.

## Budget policy (`budget_policy`, from 2026-08-09, card budget-honest-minival)

From 2026-08-09 every `measured_run` row carries `budget_policy` and `max_steps`,
and every report *episode* row carries its own effective `max_steps`.

- `budget_policy: "fixed"` — the frozen behaviour every earlier row was run
  under: one flat `--max-steps` for every episode. Rows written **before** this
  field are implicitly `fixed` at whatever `--max-steps` the run used, and that
  budget was **not recorded on the row** — the differencing hazard the two
  diagnostic rows below make concrete.
- `budget_policy: "scaled-path-v1"` — the per-episode budget is scaled by the
  episode's own `shortest_path_m` (floored at `--max-steps`, capped at 1200) so a
  tier-E truncation is attributable to a genuine miss, not to budget starvation.
  Under this policy the tier-E absent targets report `semantic_target_not_found`
  / `semantic_target_unreachable` honestly instead of `navigation_step_limit`.

**Two rows may only be differenced when `budget_policy` AND (for fixed) `max_steps`
match.** A `scaled-path-v1` SR and a `fixed` SR are not comparable.

### The two audit-appended diagnostic rows (2026-08-09, both `frozen_baseline: false`)

Both share the frozen v3 digest `919a0fea…`; they exist only to expose the
budget artifact and must never be quoted as a headline SR:

- `nav-instruct-v1-candidate-v3-20260809T054157Z` — **duplicate-of-repo-run.**
  A bit-for-bit re-run of the repo candidate row `…045529Z` (both `sr 0.12`,
  same digest); confirms reproducibility, adds no new measurement.
- `nav-instruct-v1-candidate-v3-20260809T054430Z` — **long-budget probe.**
  The identical episodes at a much larger flat `--max-steps`, `sr 0.48`. This is
  the audit's "candidate SR 0.12 → 0.48 by raising `--max-steps` alone" artifact:
  a flat budget conflates capability with start distance. Because both rows
  predate the `max_steps` field, they are distinguishable **only** via their
  report files — exactly why the field now exists. `scaled-path-v1` replaces the
  brute flat 1200 with a per-episode budget so a candidate SR is honest.

## Diagnostic artifacts (never baselines, `frozen_baseline: false`)

- `bridge_v1_v2.json` — the re-freeze bridge, per correction.
- `scene_split_{baseline,candidate}.json` — val_seen vs val_unseen
  (instrument 1). The headline is the **gap**, not either side.
- `mutation_panel.json` — the six seeded defects and which harness checks each
  reddened (instrument 6). A surviving mutant fails the panel.

## Scene truth

`../scene_truth.json` is a generated artifact: landmark tables derived from
`src/parcel_robot/scenes/city_block.xml` plus the hand-transcribed table the
frozen episode set was built from, and every difference between them. Do not
hand-edit it — `tests/test_nav_instruct_scene_truth.py` regenerates and diffs.

**Does not prove:** sim GT semantics ≠ camera perception; VLM/VLA policies.
