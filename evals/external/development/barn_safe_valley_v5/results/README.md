# BARN safe-valley v5 generated-development evidence

This directory contains the one-shot development result for the
deployment-disabled `grid_safe_valley_v5` challenger. It is a generated,
deterministic native CPU proxy—not official Gazebo BARN evidence and not a
leaderboard score.

The complete pre-run contract is frozen in `../split.json`. It pins the exact
upstream generator commit and inputs, all 30 generated development world/path
hashes, disjoint IDs `1000–1029`, unchanged reference and challenger configs,
the Parcel policy-source tree, the relevant evaluator dependency closure, and
every promotion gate. Confirmation IDs `1030–1049` have only a deterministic
generation recipe: their geometry was not generated, opened, or evaluated.

## Development run

| Run | Reference | Challenger | Paired change | Decision |
| --- | --- | --- | --- | --- |
| `barn-safe-valley-v5-dev-20260803-run01` | cached frontier v3: 12/30 success, metric 0.092208, 0 collisions, 0 timeouts, 0.095222 m clearance floor, 64.274 ms p99 | safe valley v5: 13/30 success, metric 0.099212, 0 collisions, 2 timeouts, 0.072034 m clearance floor, 65.077 ms p99 | +1 success, no success regression, +0.007004 metric; 1,432 micro-advance ticks | Rejected; confirmation unauthorized |

The branch was exercised and rescued generated world 1012. It also retained
zero collisions and passed both latency gates (65.077 ms absolute p99 and
1.0125× reference). It failed the frozen requirement of at least two paired
success gains, increased timeout rate from 0% to 6.67%, missed the 0.075 m
clearance floor by 0.00297 m, and regressed that floor by 0.02319 m versus the
reference. A positive proxy-score delta therefore does not justify promotion.

The compact machine-readable result is
`barn-safe-valley-v5-dev-20260803-run01-summary.json`. The immutable ledger
record pins the ignored full report at SHA-256
`b17030c3792739afcd62308eb0bb67b293d14e20f2e0e6e6ca89a09e83cf8d49`.
The challenger remains deployment-disabled, and there is deliberately no
confirmation command in the runner.
