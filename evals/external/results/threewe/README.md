# 3WE contract evidence

`threewe-contract-audit-20260803-baseline01.json` is a source-only,
fail-closed audit of the exact 3WE revision pinned by Parcel. It imported no
3WE Python module, started no simulator, executed no Parcel policy, and emitted
no navigation score. Its SHA-256 is
`544fd5c6ac53db6a13244d976ac7797826ff9367bf289bb5fe7e0afb079d78f7`.

The audit found 13 critical contract blockers:

- the documented seeds, resets, and all three task timeouts disagree with the
  runner;
- PointNav does not enforce its documented 0.5 m success radius and supplies
  endpoint displacement, not traveled path length, to SPL;
- ObjectNav samples a category but never presents it to an agent, then sends
  unrelated hidden target coordinates directly to `Robot.move_to`;
- Gazebo/ROS Exploration is explicitly a one-second, no-motion coverage stub,
  while mock Exploration returns perfect coverage;
- the advertised Isaac/GPU backend returns constant observations, ignores
  velocity commands, reports instant goal success, and suppresses missing
  Isaac imports;
- the simulation is a four-wheel holonomic mecanum body, not a Unitree Go2;
- the 20x15 m metadata, positive-coordinate 15x10 m Gazebo enclosure, pose
  manifests, and `empty_world` sensor bridge disagree—15/20 starts and 34/50
  goals lie outside or on the enclosure boundary;
- the benchmark owns its `Robot`/Nav2 behavior rather than exposing an
  immutable external-agent hook;
- the documented and implemented submission schemas disagree, every static
  leaderboard row fails the implemented validator, and `submit` only prints;
- first-party docs, snapshot data, and comparison code publish three different
  office PointNav baselines; and
- the leaderboard snapshot mixes PointNav backends and has only one entry for
  each of ObjectNav and Exploration.

The admission decision is therefore `not_admitted`: do not build a Parcel
adapter or freeze a top-decile threshold against this revision. Doing so would
either change the evaluator boundary, preserve invalid task semantics, or
evaluate the 3WE wheeled navigation stack rather than Parcel's Unitree Go2
embodiment. The three adopted 3WE targets remain explicit portfolio blockers
until an organizer publishes a task-correct, backend-specific, injectable
contract and rankable cohorts.

Run the audit after fetching the locked sources:

```bash
.parcel/bin/python -m evals.external.threewe_contract_audit
```

The public protocol remains documented at the [3WE benchmark
page](https://3we.org/benchmarks) and [leaderboard
documentation](https://docs.3we.org/leaderboard/). Those mutable pages were
rechecked on 2026-08-03; the evidence report itself is bound to source commit
`6073a1bd0a30b6ca1348027ac35b05832b97bfe9` and per-file hashes.
