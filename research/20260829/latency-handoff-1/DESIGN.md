# LHO-1 preregistration: latency-sized committed prefix / revisable tail

Date frozen: 2026-08-29  
Status: **DESIGN FROZEN BEFORE IMPLEMENTATION OR TEST OPEN**  
Evidence tier: deterministic scheduling/kinematic simulation only  
Physical authority: none

## Question

Can a latency-sized, braking-safe committed prefix plus revisable tail reduce
stop-and-go while a slow Model-A planning lane reasons, without executing stale
tail actions after a task revision or weakening local STOP/obstacle dominance?

This is a product-scoped reproduction of the handoff mechanism motivated by
LiveVLN. It does not reproduce that paper's model, dataset, robot, or physical
result and cannot establish navigation competence or Go2 safety.

## Frozen arms

- **B0 blocking:** request a slow-lane update, decelerate to zero, and wait for
  the response before issuing a new trajectory.
- **F0 fixed chunk:** keep executing a fixed 400 ms chunk while the slow lane
  runs; when it expires, hold zero until the response arrives. A response
  replaces the remaining chunk immediately.
- **G0 guarded handoff:** estimate current sense + inference + command latency,
  publish the shortest already-validated prefix whose execution time covers
  that estimate plus a fixed 100 ms margin, and retain the rest as revisable.
  A response may replace only the revisable tail. Prefix duration is capped by
  the currently validated corridor and braking envelope.

All arms use the same 20 Hz tracker, acceleration limits, exogenous latency,
route/revision schedule, obstacle truth, and local safety gate. An emergency
STOP or newly occupied swept volume cancels even a committed prefix on the next
tracker tick. “Committed” means protected from an ordinary planner rewrite,
never protected from safety or STOP.

## Frozen scenario inventory

The evaluator will generate a manifest before running an arm and use exact
paired schedules across arms:

- 12 route families, including straight, S-turn, alternating turn, narrow
  corridor, T-junction, shared-prefix divergence, early divergence, and
  late-divergence revisions;
- 5 test seeds per family;
- ordinary revision at each of 9 path deciles;
- slow-lane base latency in {0.10, 0.25, 0.40, 0.70, 1.10, 1.80} seconds plus
  bounded sense/command jitter;
- latency-estimator error in {-50%, -25%, 0%, +25%, +50%};
- separate emergency-STOP and newly occupied-prefix cases at every revision
  decile; and
- a no-revision control for every family/seed/latency pairing.

The test route family names and parameters are generated into a frozen manifest
and hashed before the evaluator imports or executes policy code. No parameter
may be tuned after aggregate or per-family test metrics are read.

## Independent oracles and definitions

- `authorized_prefix_end_m` is frozen when the prefix is published from route,
  occupancy, speed, braking distance, and the source plan revision.
- `stale_tail_distance_m` counts positive progress under an old plan after the
  lesser of its authorized prefix end and a local invalidation boundary.
- `waiting_time_s` is non-terminal time with desired progress, a clear local
  corridor, and accepted speed below 0.02 m/s because no usable trajectory is
  available. Safety/STOP holds are excluded and reported separately.
- `visible_gap` is a contiguous waiting interval longer than 0.50 s.
- mission success requires reaching the current revised route endpoint before
  timeout with no collision, boundary violation, or post-STOP positive command.
- the collision oracle uses independent continuous swept-volume intersection,
  not the arm's occupancy check.
- a route revision becomes authoritative at its receipt tick. Progress within
  the pre-authorized committed prefix is allowed; progress beyond it is stale.

## Hypotheses and gates

### H1 — fluidity without task loss

Across ordinary/no-revision schedules, G0 must reduce paired waiting time by at
least 30% and visible gaps by at least 50% relative to B0, while mission success
is no more than 2 percentage points lower than the better of B0/F0.

### H2 — revision integrity

Across all ordinary revision schedules, G0 must have zero stale-tail distance,
zero old-revision dispatch beyond the authorized prefix, zero collision, and
zero route-boundary violation. G0 p95 splice acceleration and jerk may not
exceed F0 by more than 10%.

### H3 — STOP and dynamic invalidation dominate

Across every emergency and occupied-prefix case, all arms must issue no positive
translation later than one 20 Hz tracker tick after the local invalidation and
must have zero post-invalidation collision. G0 may not finish its prefix first.

### H4 — estimator robustness and boundedness

For each estimator-error stratum, report wait/gap/SR separately. G0 must preserve
H2/H3 in all strata, detect every underestimated prefix exhaustion explicitly,
and keep queue/prefix storage bounded. No claim is made that G0 eliminates waits
when latency is underestimated or the corridor cap is shorter than latency.

### H5 — reproducibility

Two fresh-process evidence runs must have identical normalized manifest,
episode-trace, and aggregate hash roots. An independent verifier recomputes
the manifest pairing, continuous collision/boundary oracle, wait/gap metrics,
revision legality, STOP timing, hypotheses, and hashes from raw traces. Tamper
tests must alter one trace command, one revision, one aggregate metric, one
source file, and one manifest digest; every alteration must be detected.

## Decision rule and non-claims

`LHO1_MECHANISM_PASS` requires H1–H5. Any collision, stale-tail distance,
post-STOP positive command beyond one tracker tick, missing paired schedule,
unreported prefix exhaustion, hash mismatch, or regression yields
`LHO1_REFUTED`.

Even a pass establishes only the scheduling/transaction value of a guarded
handoff in this authored simulator. It does not establish learned Model A,
camera/LiDAR perception, quadruped dynamics, social acceptability, physical
braking distance, Orin timing, or mount readiness. Production integration
must size the guard from measured target latency and an independently
commissioned braking/corridor envelope.
