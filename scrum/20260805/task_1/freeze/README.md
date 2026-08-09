# NAV_INSTRUCT re-freeze after K0 (goal-calibration)

**Do not rewrite** prior freeze artifacts or ledger rows
(`scrum/20260804/task_6/freeze/nav-instruct-baseline*`, older evals ledgers).
Append a new baseline candidacy after K0 lands.

## Procedure

```bash
# From repo root — minival first (honest, small).
.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
  --minival --mode baseline --freeze \
  --out evals/nav_instruct/results

# Optional full matrix when promoting a replacement baseline.
.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
  --mode baseline \
  --out evals/nav_instruct/results
```

`--freeze` writes **new** files under this directory
(`nav-instruct-baseline-k0.json` + report). It does **not** touch
`scrum/20260804/task_6/freeze/`.

## Required metadata on the new freeze row

| Field | Value |
|---|---|
| `runner_version` | `nav-instruct-v1.1-k0-arrival` (or later) |
| `k0_arrival_authority` | `GoalRegion` shared builders |
| `frozen_baseline` | `true` only after owner accepts the row |
| `supersedes` | prior report id (reference only — do not mutate that file) |
| `does_not_prove` | keep sim≠camera, absent-target open-vocab, VLM/VLA caveats |

## Attribution expectation

Near-goal step expiry must show up under `termination` / L6, not as a pile of
`planning_error` from `navigation_step_limit` alone. If the histogram still
loads planning on near-misses, K0 is incomplete — do not freeze.
