# Planner quality v2 result ledger

This append-only summary points to the immutable result artifacts produced by
the frozen five-case `parcel-planner-quality-v2` suite. Latencies are reported
as median / mean / p95-nearest-rank across the five cases. Runs 01--03 retain
per-case metrics; their summaries below are computed from those recorded
values. Runs 04 and later also store the aggregates directly. The explicitly
marked warm-up row contains one case and is not a five-case baseline.

| UTC | Run | Change | Accepted | TTFT ms | Model/usable-plan ms | Physical episodes / success |
| --- | --- | --- | ---: | ---: | ---: | --- |
| 2026-08-03 11:39:25 | [`planner-v2-20260803113925Z-4886b1b8`](planner-v2-20260803-gemma4-cpu-run01.json) | Runner v1, manifest-default prompt, first runtime-routed CPU baseline | 0/5 | 5,179.488 / 5,427.146 / 6,579.134 | 27,695.217 / 27,945.482 / 34,355.460 | 0 / null |
| 2026-08-03 11:44:28 | [`planner-v2-20260803114428Z-dc470c6e`](planner-v2-20260803-gemma4-cpu-run02.json) | Schema/context envelope hints, unchanged prompt and cases | 0/5 | 886.122 / 883.477 / 899.031 | 23,098.741 / 23,424.374 / 29,898.786 | 0 / null |
| 2026-08-03 11:49:09 | [`planner-v2-20260803114909Z-95410d63`](planner-v2-20260803-gemma4-cpu-run03.json) | Runner v2 post-decode trusted context binding | 2/5 | 850.635 / 855.712 / 870.150 | 20,930.396 / 21,810.858 / 27,350.314 | 0 / null |
| 2026-08-03 11:57:15 | [`planner-v2-20260803115715Z-ad65c4ec`](planner-v2-20260803-gemma4-cpu-run04.json) | Generic prompt challenger plus trusted envelope, without contract compiler | 1/5 | 4,789.363 / 5,228.005 / 6,986.235 | 25,093.161 / 25,674.362 / 30,185.103 | 0 / null |
| 2026-08-03 12:03:16 | [`planner-v2-20260803120316Z-6406b694`](planner-v2-20260803-gemma4-cpu-run05.json) | Same generic prompt and trusted envelope plus `semantic-planir-compiler-v1` | **5/5** | **868.039 / 875.043 / 946.657** | **19,664.294 / 20,689.074 / 25,235.046** | **0 / null** |
| 2026-08-03 12:42:04 | [`planner-v2-20260803124204Z-724df04c`](planner-v2-20260803-gemma4-gpu-warmup01.json) | One-case full-CUDA cache warm-up calibration; not a scored baseline | 1/1 | 603.187 / 603.187 / 603.187 | 5,363.156 / 5,363.156 / 5,363.156 | 0 / null |
| 2026-08-03 12:42:55 | [`planner-v2-20260803124255Z-75a84bba`](planner-v2-20260803-gemma4-gpu-run06.json) | Same run-05 semantics on pinned b10236 CUDA OCI, 31/31 layers offloaded, warm cache | **5/5** | **855.379 / 701.293 / 881.942** | **5,657.459 / 5,990.583 / 7,201.283** | **0 / null** |
| 2026-08-03 13:30:28 | [`planner-v2-20260803133028Z-fb46a335`](planner-v2-20260803-ministral8b-instruct-gpu-run01.json) | Development-only Ministral 3 8B Instruct PlanIR challenger on pinned b10236 CUDA OCI; no activation | **3/5** | **382.199 / 387.587 / 426.625** | **6,071.293 / 6,600.955 / 8,297.723** | **0 / null** |

The prompt changed from baseline SHA-256
`4ca75618d5765d4e6812c3d18826dc77ec989969064290d4a336db496896914c`
to generic challenger SHA-256
`52e3636ae1e4f3042d8cbd9839b6cd0b41883ecc7744d223a2b724796743f44e`
in runs 04--06 and the warm-up. The frozen cases remained SHA-256
`6717f2fbda80920133f20f4584630f78748b6146c17222600bf71471e9272d1a`.
All records used the same Gemma artifact SHA-256
`3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d`
Runs 01--05 used CPU with zero GPU layers. The calibration and run 06 used
the pinned official llama.cpp b10236 CUDA 12 OCI runtime on an RTX 5000 Ada;
the retained server log reports all 31/31 layers offloaded. Versus CPU run 05,
run 06 preserved 5/5 acceptance while reducing median usable-plan latency by
71.23% (19,664.294 to 5,657.459 ms). Median TTFT changed from 868.039 to
855.379 ms; one exact cached prefix reached 181.289 ms.

The development-only Ministral row used the exact 5,198,911,904-byte Q4_K_M
artifact at SHA-256
`33e7a72cf5e6e2cfc2f2847075acc013d68bba023e35310cef86b5cf8fdca761`.
A separate verbose load measured 35/35 layers on CUDA. It reduced median TTFT
55.32% relative to Gemma GPU run 06, but increased median complete-plan latency
7.32% and failed two admission cases. For `five_steps_away_then_hold` it
generated an out-of-contract goal envelope (`tolerance_m: 5.0` and
`owner-owner-1` query); for `orbit_then_follow_behind` it emitted numeric
`OrbitOwner.arguments.size: 1.0` where the contract requires a size enum. Both
failed closed with `invalid_argument_value`. Because semantic acceptance fell
from 5/5 to 3/5 with no full-call latency win, Ministral Instruct is rejected as
the PlanIR planner incumbent. This does not evaluate the separately locked,
not-downloaded Ministral Reasoning checkpoint.

The 5/5 result proves only semantic decomposition and admission on the five
selected compound instructions. It does not measure target perception,
navigation, collision avoidance, conversation quality, or Unitree execution.
No row in this ledger may be interpreted as physical-navigation success.
