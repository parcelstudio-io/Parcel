# H7 — localization by delegation · DESIGN (Fable) · 2026-08-23

## Hypothesis (falsifiable)
A delegated scan-matching localizer (KISS-ICP class; pip-installable,
torch-free) fed with simulated planar/3-D LiDAR from MuJoCo can fill
`PoseProvider`'s **MAP role** and satisfy Parcel's contract — timestamped
`T_map_odom`, covariance, `PoseHealth`, and explicit jump/relocalization
events — with ATE ≤ 0.15 m and yaw RPE ≤ 1°/m over a 60 m sim traverse, a
largest single-update jump (`localization_jump_m`) measured rather than
UNMEASURED, and the navigation consumers (NAV_INSTRUCT v4 episode set)
degrading gracefully (refusals, not false arrivals) across the calibrated
drift ladder. And: the contract is body-neutral — the same provider runs
unchanged for a fake custom quadruped's odometry.

## Why (navigation/SLAM survey 2026-08-23; LOC-1 in the tranche-2 design)
- There is no estimator anywhere (`pose.py:9-12` says so); the seam is
  excellent (MAP/ODOM frames, covariance, HEALTHY/DEGRADED/LOST refusals,
  chance-constrained region membership) and was built precisely so a real
  localizer slots in "with zero consumer changes"
  (`docs/STRATA_GENERALIZATION_PLAN.md` stratum 1). That claim has never
  been exercised.
- The stopping envelope's `localization_jump_m` term is UNMEASURED on
  every host (`bridge/timing.py:~424`); GATE-1 prints it as such. Any
  localizer we choose must publish it.
- The corpus recommends delegating metric SLAM (FAST-LIO2/Point-LIO class
  for the Mid-360) rather than owning a filter; those need ROS/PCL and
  real IMU+LiDAR bags we do not have. KISS-ICP is the honest off-robot
  proxy: same contract, pure scan matching, runs on sim clouds now. The
  ADR choosing the on-robot provider is a milestone decision informed by
  this bench's contract findings, not by this bench's ATE.
- Drift-arming is where on-robot surprises hide: "the localizer got worse"
  vs "the consumer mishandled a refusal" (only one 2-episode `v4d` row exists).

## Objective
Prove the MAP-role contract end-to-end with a real estimator in sim, measure
the jump term, and map where navigation breaks along the pose ladder — so
the milestone design can commit to a provider topology with evidence.

## Experiment
1. **Provider** (`localization/` new package: `contract.py` with
   `LocalizerProvider` Protocol + frozen `LocalizationUpdate(T_map_odom,
   cov, health, jump_m, stamp_ns, source)`; `kiss_icp_provider.py`
   adapting `kiss-icp` (pip) to the Protocol; `pose_adapter.py` composing
   it with the existing `DriftingOdomProvider` as the ODOM role into a
   `PoseProvider`). If `kiss-icp` cannot install into `.parcel`
   (Python 3.14), fall back to an ICP in numpy (`open3d` also acceptable)
   and say so.
2. **Scans**: `simulation/mujoco_lidar.py` (`raycast_planar_scan`,
   `planar_scan_payload`) at 10 Hz along scripted 60 m traverses in
   `city_block.xml` and a second scene; truth pose from the sim.
3. **Contract rows**: health transitions on scan dropout (10 s gap) and on
   a teleport (the sim base teleports — use it as a relocalization
   injection); jump magnitude per update; covariance calibration (NEES).
4. **Consumers**: run `evals/nav_instruct/run_drift_arms.py` (exists) over
   `calibrated_go2 → go2_aggressive → go2_degraded → *_lost` with the
   provider as MAP; record SR, false-arrival count, `authority_disagreement`,
   LOST ticks, reanchor events.
5. **Body-neutral check**: a `FakeQuadrupedOdom` (different wheelbase,
   different drift profile) through the same adapter — the provider code
   must not change.

## Measurements (pre-registered)
| row | metric | criterion |
|---|---|---|
| L1 | ATE (RMSE) over 60 m, two scenes | ≤ 0.15 m |
| L2 | yaw RPE | ≤ 1°/m |
| L3 | largest single-update jump (`localization_jump_m`) | measured, reported per scene |
| L4 | health on dropout / teleport | DEGRADED within 1 s; LOST on teleport; recovery time reported |
| L5 | NEES (covariance calibration) | within [0.5, 2.0] of chi-square expectation, reported |
| L6 | drift-ladder consumer rows | 0 false arrivals; SR per rung reported; refusals classified |
| L7 | provider latency per scan (p50/p95) | ≤ 30 ms p95 on CPU |
| L8 | fake-quadruped run | provider diff = 0 lines |

## What would refute it
L1/L2 miss ⇒ planar sim scans are too poor for ICP (report and try 3-D
clouds); L4 cannot express a teleport as LOST ⇒ the contract needs a jump
detector the provider does not have — that is a design finding; L6 shows
false arrivals ⇒ a consumer reads pose past a refusal (name the file:line).

## Evidence tier / does not prove
`desktop-sim`. Proves the contract and consumer behavior; does not prove
Mid-360 performance, real IMU coupling, loop closure, or outdoor scale.

## OWNS
`research/20260823/localization-delegation-bench/**`, new package
`localization/` (docstring-only `__init__`), one capability test
`tests/test_h7_localization_contract.py`, `pyproject.toml` optional-dependency
group `localization` (kiss-icp / open3d) — installation into `.parcel` is
allowed for the experiment. Must not touch: `pose.py` consumers,
`navigation/`, `bridge/timing.py`, the frozen NAV_INSTRUCT baselines
(read-only replay), the owner's stack.
