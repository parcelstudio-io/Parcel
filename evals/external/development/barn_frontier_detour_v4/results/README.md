# BARN frontier-detour v4 development ledger

This directory contains only development evidence for the deployment-disabled
`grid_frontier_detour_v4` challenger. It is not an official Gazebo result and
cannot support a leaderboard or top-decile claim.

The split was frozen in `../split.json` before any `5 mod 6` world was run. A
SHA-256-ranked 30-world subset was opened for development; the remaining 20
worlds are sealed, have not been run or inspected, and are not authorized for
use because the candidate missed its predeclared promotion gate.

## Runs

| Run | Policy | Development result | Decision |
| --- | --- | --- | --- |
| `barn-v4-dev-reference-frontier-v3-20260803-run01` | frontier cached v3 | 14/30 success, metric 0.111928, zero collisions | Initial reference |
| `barn-v4-dev-candidate-frontier-detour-v4-20260803-run01` | detour v4.0 | Exact outcome/trajectory tie; 115 detour-align and zero detour-track steps | Negative diagnostic: periodic replanning discarded the target during alignment |
| `barn-v4-dev-reference-frontier-v3-20260803-run02` | frontier cached v3 | 14/30 success, metric 0.111928, zero collisions | Paired reference after the feature-gated implementation refinement |
| `barn-v4-dev-candidate-frontier-detour-v4-1-20260803-run02` | detour v4.1 | 14/30 success, metric 0.111928, zero collisions; 185 detour-align and 75 detour-track steps | Rejected; no success or metric gain |

Run 02 proves that the bounded detour can translate rather than merely rotate,
and it retained the 0.094266 m global signed-clearance floor. It nevertheless
rescued zero failures, converted one watchdog stop into a timeout, increased
mean final goal distance by 0.0394 m, and reduced mean episode-minimum clearance
by 0.0322 m. Mean controller latency changed by -0.56% and p99 by +0.70%, both
inside the frozen 20% budget.

The machine-readable paired result and gate decision are in
`paired-run02-summary.json`. Immutable ledger records under `ledger/` retain the
date, run ID, change description, configuration/model hashes, aggregate metrics,
and full-report hashes. Full per-episode reports stay local under ignored
`runs/`, matching the repository's external-evaluation storage convention.

No sealed-confirmation command is recorded because the candidate did not earn
promotion. Production defaults and `grid_v1` are unchanged.
