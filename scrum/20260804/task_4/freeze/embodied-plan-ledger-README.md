# Embodied PlanIR v1 result ledger

This append-only ledger indexes immutable runs of the frozen headless
execution gate. “Supported success” excludes cases whose required controller
is explicitly unavailable; an unsupported case is never counted as a pass.

| UTC | Run | Change | Supported success | Unsupported | Physical skills / steps | Collisions / timeouts | Minimum clearance |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2026-08-03 12:51:21 | [`embodied-plan-v1-20260803125121Z-e4678ced`](embodied-plan-v1-20260803-baseline01.json) | First frozen headless execution baseline for admitted Gemma run05 plans | 4/4 | 1 moving-owner `FollowFormation` | 6 / 1,137 | 0 / 0 | 0.883147 m |

The runner dispatches the revalidated plans through `TaskExecutive` and
`SemanticTaskRuntimeAdapter`, then advances the production semantic navigation
and spatial controllers in deterministic MuJoCo city geometry. Evaluator truth
is read only after execution. This establishes neither Unitree contact
dynamics nor an external navigation score.
