# Evaluation target portfolio

`portfolio.json` turns “top 10% across all evals” into a versioned,
conjunctive objective. Every adopted ranked evaluator must independently meet
its target; a strong result on one benchmark cannot average away a weak result
on another.

| Target class | Meaning | Can establish a top-decile claim? |
| --- | --- | --- |
| `official_ranked` | Frozen cohort, rank cutoff, metric and exact official protocol | Yes, with eligible official evidence and rank confirmation |
| `proxy_development_gate` | Reproducible local hill-climbing signal | No |
| `internal_pass_fail` | Product relevance and Unitree safety regression gate | No, but failure blocks promotion |
| `unresolved_top_decile` | Adopted benchmark without a defensible frozen cohort | No; it blocks the portfolio claim until resolved |

## Frozen official references

The [official Habitat Challenge 2020 page](https://aihabitat.org/challenge/2020/)
publishes six final rows for each leaderboard, sorted by SPL. Applying
`ceil(10% × 6)` gives a rank-1 cutoff: displayed SPL `0.21` for PointNav and
`0.10` for ObjectNav. Those are planning references, not substitutes for an
official rank. In particular, ObjectNav ranks 1 and 2 both display `0.10`, so
rank confirmation is required rather than inferring rank from a rounded score.
The historical challenge is closed, and Parcel's synthetic tasks are not
eligible evidence.

The BARN entry references `barn_2026_top_decile.json`, which freezes the
official report cohort and the rank-2 score of `0.4880`. The native headless
runner remains explicitly non-official even if its numeric score reaches that
reference.

The best recorded native result as of 2026-08-03 is the feature-gated
rolling-grid/A* run `barn-ab-20260803T093224170877Z-6b24e34f`: 44% success,
0.103698 native metric, and zero collisions over the fixed 50-world proxy
subset sampled from BARN's 300 public worlds, versus
2%, 0.004556, and zero collisions for the unchanged baseline. It is useful
hill-climbing evidence but remains `official_gate_eligible: false`; it records
no portfolio achievement.

The [3WE benchmark page](https://3we.org/benchmarks) specifies three tasks,
100-episode evaluations, metrics, and separate simulation/real-hardware
tracking, but its served leaderboard table does not expose a frozen numeric
cohort. Parcel's source audit found that the pinned alpha runner also disagrees
with the documented seed/reset/timeout contract, computes PointNav path length
as endpoint displacement, gives ObjectNav hidden target coordinates to
`Robot.move_to`, and implements Gazebo Exploration as a no-motion one-second
stub. The Isaac/GPU backend is also a constant-observation, instant-success
stub; the shipped simulator is a holonomic mecanum robot rather than a Go2;
and most declared office poses do not fit the Gazebo enclosure. The
report/submission schemas diverge, all static rows fail the implemented
validator, `submit` does not upload, and no immutable external-agent hook
exists. PointNav, ObjectNav, and Exploration therefore remain separate,
claim-blocking unresolved targets. Resolve each only with a task-correct,
organizer-confirmed evaluator release plus a primary task-and-backend
leaderboard snapshot whose cohort, ranking metric, tie rule, cutoff, and
threshold can be frozen.

`portfolio.json` records no achievement. Model-run evidence belongs in the
evaluation ledger; use `portfolio_targets.py` to validate the target manifest
without converting proxy numbers into leaderboard claims.

## Execution-device audit

Run the read-only, machine-readable audit in the same Python environment used
for an evaluation:

```bash
.parcel/bin/python -m evals.external.device_capabilities
```

The 2026-08-03 desktop audit found an NVIDIA RTX 5000 Ada Generation with
32,760 MiB, driver 595.84, and compute capability 8.9. The `.parcel`
environment had NumPy, but no PyTorch, CuPy, JAX, Habitat-Sim, or Isaac Sim.
The audit checks `torch.cuda.is_available()` in an isolated subprocess when
PyTorch exists; package presence or a CPU-only wheel cannot satisfy CUDA.
Consequently:

- native BARN, rolling grid/A*, and the synthetic external suite run on CPU by
  design; this is not a missed GPU optimization or a GPU result;
- CityWalker, NaVILA, ViNT, and NoMaD declare CUDA, but cannot execute here
  until their framework and runtime adapters are installed;
- official Habitat and Isaac paths are blocked on simulator stacks, assets,
  adapters, and platform validation despite the capable GPU hardware; and
- 3WE remains backend-dependent until a specific official backend is frozen.

The utility separates `device_ready` from `evaluator_ready` and provides
`require_declared_device()`, which fails closed rather than silently moving a
CUDA-declared workload to CPU. This audit installs nothing and does not claim
that any learned or official evaluator ran on the GPU.
