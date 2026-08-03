# BARN safe-valley guard v6 development evidence

This directory records the one-shot development decision for the
deployment-disabled `grid_safe_valley_guard_v6` ablation. This is a generated,
deterministic native CPU proxy—not official Gazebo BARN evidence and not a
leaderboard score.

## Predeclared experiment

V5 had produced a `0.0720344003 m` clearance floor and two timeouts on its own
development corpus. V6 tested one narrow hypothesis on a new, disjoint corpus:
add exactly half the diagonal of a `0.10 m` occupancy cell
(`0.07071067811865475 m`) to both raw-LiDAR valley admission and the observed
swept-body envelope. No scan-sweep, attempt limit, velocity, global planner,
safety shield, reverse, or lateral-motion behavior changed.

The original pre-run contract is content-addressed in `../split.json` (SHA-256
`47dddf6b54a8cc6b962f6bb4b16912a2d72266187126e13c6559af0f0949cd63`).
It pins 30 newly generated development IDs `2000–2029`, corpus SHA-256
`fd587ef042b8fae124c4b0b2779548023d0b374eaf5d4bd9759ea4b0d00ff579`,
the controller/config/source closure, paired protocol, and every gate. Reserved
confirmation IDs `2030–2049` remain a deterministic recipe only; their geometry
was not generated, opened, or evaluated.

## Failed preflight and repair

Run01 aborted at the comparison metadata boundary because both arms had been
classified as experimental candidates. The harness raised
`ValueError: baseline_spec must not be experimental` before `run_barn_suite`,
so it executed zero episodes and wrote no metric, report, or ledger record. The
immutable failure record is under `preflight/`.

The repaired manifest `../split-run02.json` (SHA-256
`821e70935c447007614e1a6b939c9a1d0769443cebdf7f5028e4bdcf348e13a5`)
links to the predecessor and failure record. The only experiment repair marks
the byte-identical, deployment-disabled v5 arm as the immutable comparison
reference. It also content-addresses an authorized concurrent compatibility-
table prose update that is not imported by the paired BARN runner. Corpus,
policy source, controller/config/model artifacts, hypothesis, protocol, and
gates did not change.

## Development result

Run: `barn-safe-valley-guard-v6-dev-20260803-run02` at
`2026-08-03T15:28:46.145378Z`.

| Metric | V5 reference | V6 guard | Candidate minus reference |
| --- | ---: | ---: | ---: |
| Success | 15/30 (`0.500000`) | 15/30 (`0.500000`) | `0` |
| Navigation metric | `0.12029362925349155` | `0.12029362925349155` | `0.0` |
| Collision rate | `0.0` | `0.0` | `0.0` |
| Timeout rate | 4/30 (`0.13333333333333333`) | 4/30 (`0.13333333333333333`) | `0.0` |
| Stopped outside goal | 11/30 | 11/30 | `0` |
| Clearance floor | `0.08321989283057797 m` | `0.08321989283057797 m` | `0.0 m` |
| Mean episode-minimum clearance | `0.20186451539855668 m` | `0.21225791734453028 m` | `+0.010393401945973631 m` |
| Mean final goal distance | `3.9729999846833652 m` | `4.037494672155199 m` | `+0.06449468747183351 m` |
| Controller p99 | `83.354964 ms` | `84.3841 ms` | `1.0123464273×` ratio |

The guarded branch was genuinely exercised for 964 advance ticks and changed
10 paired episodes. It maintained zero collisions, met the `0.075 m` clearance
floor, improved mean per-episode minimum clearance, produced no success or
navigation-metric regression, and passed both CPU latency gates. However, the
extra conservatism reduced mean maximum goal progress by
`0.06449468747183307 m`. It exchanged one timeout for another (v5 timed out on
world 2019 while v6 timed out on world 2028) and left four total candidate
timeouts.

## Decision

**Reject v6 and do not consume confirmation.** Eleven of twelve frozen gates
passed; `zero_candidate_timeout_rate` failed. The causal prediction that the
guard would remove timeouts was therefore false on development, even though
its clearance behavior improved. V6 is not selected for confirmation, no
confirmation command is authorized or implemented, and deployment remains
disabled.

The compact result is
`barn-safe-valley-guard-v6-dev-20260803-run02-summary.json`. The immutable ledger
record pins the ignored full report at SHA-256
`6d2e31366e1d8318ad3bba37aea834fcbb96fab4247568421d2ba51433ebe319`;
the compact summary itself has SHA-256
`0453abc5e900c5c8f76453a0e30661eb63e0d10ddd4d2ba969db889ce344ebb9`.

This result isolates the next research direction: clearance padding alone is
not a liveness mechanism. Any subsequent experiment should use another new,
predeclared development split and target the bounded recovery/scan policy,
without reopening v5 or v6 observed worlds or weakening the downstream safety
shield.
