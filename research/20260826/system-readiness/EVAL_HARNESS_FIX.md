# Scene-split output routing — pre-fix contract

The 2026-08-24 audit disclosed that NAV_INSTRUCT's `--scenes` branch ignores
the CLI's `--out` argument and always writes
`evals/nav_instruct/results/scene_split_<mode>.json`. That makes an otherwise
read-only research remeasurement overwrite a tracked diagnostic.

This change is evaluation plumbing only. Before editing:

- `_run_scene_split` must pass
  `<args.out>/scene_split_<mode>.json` to the existing `write_report` function;
- a seed test must replace `run_split` and `write_report`, call the real CLI
  branch, and assert the exact routed path;
- split generation, aggregation, scorer, seeds, scene files, and navigation
  product code must not change;
- the tracked diagnostic's pre/post SHA-256 must remain identical when the
  actual unseen split is run with a research `--out` directory.

Acceptance: the focused test passes, the real report lands only under
`research/20260826/system-readiness/scene_split/`, and the tracked file hash is
unchanged.
