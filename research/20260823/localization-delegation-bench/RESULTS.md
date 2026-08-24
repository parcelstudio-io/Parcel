# H7 — localization by delegation · RESULTS (Opus) · 2026-08-23 (files stamped UTC)

Tier: **desktop-sim**. Hosted spend: **$0.00** (no API call, no GPU, no model).
Tree: branch `main` at `0ec1d7c`, working tree not committed.

## What was run

```
.parcel/bin/pip install kiss-icp                      # FAILED, see below
.parcel/bin/pip install --only-binary=:all: open3d    # FAILED, see below
.parcel/bin/pip install --only-binary=:all: small-gicp # small-gicp 1.0.1

cd research/20260823/localization-delegation-bench
.parcel/bin/python bench.py                            # L1-L5, L7, L8 (10 arms)
PYTHONPATH=<repo> .parcel/bin/python run_consumers.py   # L6 (2 passes x ladder)

env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label h7 \
  .parcel/bin/python -m pytest tests/test_h7_localization_contract.py -q   # 6 passed
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label h7 \
  .parcel/bin/python -m pytest tests/test_dec0_debt_ratchet.py \
      tests/test_decig2_import_ratchet.py -q
```

Environment: CPython 3.14.4, numpy 2.5.1, mujoco 3.11.0, small-gicp 1.0.1,
AMD Threadripper PRO 7995WX (192 threads), no GPU used by this hypothesis
(`nvidia-smi` showed 99 % / 31 GB in use by H2/H6 throughout; irrelevant here —
the provider is single-threaded CPU and never touches CUDA). Load average 4-6
during the headline runs; the L7 latency row was re-read from the raw rows
after the fact and is single-threaded wall time inside `localizer.update`.

## The dependency question, answered first

The design named `kiss-icp` and allowed a fallback. Measured:

| package | result on CPython 3.14.4 |
|---|---|
| `kiss-icp` | no wheel; the 1.3.0 sdist fails at the build-requirements step: `ERROR: Use cmake.version instead of cmake.minimum-version with scikit-build-core >= 0.8` |
| `open3d` | `Could not find a version that satisfies the requirement open3d (from versions: none)` |
| `small-gicp` | **1.0.1 installs** (cp314 wheel), imports, runs |

The fallback taken is `small-gicp`, **not** the design's "an ICP in numpy":
writing our own matcher is the one thing the delegation hypothesis is about not
doing. `small-gicp` is the same class of dependency as KISS-ICP — a C++
registration library (voxel downsampling, KdTree correspondences, ICP /
point-to-plane / GICP / VGICP), no ROS, no PCL, no torch. The provider module is
therefore `localization/gicp_provider.py`, not `kiss_icp_provider.py`.

Registration type is `PLANE_ICP`, fixed after a 15 m pilot in one scene and
before any pre-registered row was run. Reason, measured: point-to-point ICP's
Hessian translation block is exactly `N·I` whatever the geometry (verified: a
40 m corridor with no along-track structure still yields `H[3,3] = N`), so it
cannot express the aperture problem and its covariance would be isotropic;
point-to-plane yields `H[3,3] = 0` there, which is correct. GICP's `error` is in
Mahalanobis units, so the residual gate and the covariance scale would both be
dimensionally wrong.

## Pre-registered measurement table

| row | criterion | measured | met? |
|---|---|---|---|
| **L1** | ATE (RMSE) over 60 m, two scenes ≤ 0.15 m | **0.0098 m** (city_block) · **0.0160 m** (city_block_b) | **MET** |
| **L2** | yaw RPE ≤ 1 °/m | **0.070 °/m** · **0.117 °/m** | **MET** |
| **L3** | largest single-update jump, reported per scene | **0.053 m** · **0.086 m** nominal; 0.156 / 0.118 m through a 10 s dropout; **7.15 m** on a detected kidnapping; **10.47 m** on a relocalization in the L6 sweep | **MEASURED** |
| **L4** | DEGRADED within 1 s of dropout; LOST on teleport; recovery reported | dropout: DEGRADED at **+0.4 s**, LOST at +2.9 s, recovery **0.1 s** (both scenes) · teleport: LOST **+0.2 s**, recovery **0.4 s** on city_block_b — **never LOST on city_block** | **dropout MET / teleport MISSED (1 of 2 scenes)** |
| **L5** | NEES within [0.5, 2.0] of the chi-square expectation | **ANEES 104.0** (city_block) · **233.9** (city_block_b) | **MISSED by ~50-100x** |
| **L6** | 0 false arrivals; SR per rung reported; refusals classified | **0 false arrivals and 0 collisions on all 5 rungs**; SR falls 17-100 % relative vs the stock pass, entirely into refusals | **MET** (and the SR cost is the finding) |
| **L7** | provider latency ≤ 30 ms p95 on CPU | **p50 0.75 ms, p95 2.25 ms, p99 2.43 ms** over 5 795 tracking updates | **MET** (relocalization ticks are 45-78 ms; n = 5) |
| **L8** | fake-quadruped run, provider diff = 0 lines | ATE **0.0102 / 0.0184 m** with a different odometry implementation; the three `localization/*.py` sha256 are identical across both runs | **MET** |

Raw rows: `results/{nominal,dropout,teleport,teleport_far,fake_quadruped}-{city_block,city_block_b}-*.json`
(600 ticks each, every tick carries truth, MAP, ODOM, health, jump, covariance,
latency and the localizer's own event) and `results/consumers-{stock,localized}-*.json`.

## Row detail

**L1 / L2 — the localizer earns its place.** Over the same 60 m the ODOM source
(`calibrated_go2`) accumulates 0.34 / 0.40 m RMSE and ends 0.56 / 1.25 m from
truth; the MAP frame stays at 0.010 / 0.016 m — a 25-35x reduction. Translational
RPE over 1 m segments is 0.96 % / 1.77 %.

**L3 — `localization_jump_m` has a number.** `bridge/timing.py` has carried this
term as `UNMEASURED` on every host since HW-6. The provider publishes it per
update; the largest nominal single-update value is **0.086 m** (city_block_b).

One correction to how it is computed, made after the first bench run and before
the reported numbers: the naive reading — the translation delta of `T_map_odom`
itself — is origin-dependent, because a pure yaw change in the correction moves
that translation by `|odom translation| · dtheta`. It read **4.42 m** for a
correction that displaced the robot by about 1 m. The published `jump_m` is now
the displacement of the **robot's** MAP pose caused by the correction changing,
evaluated at the current ODOM pose. That is the quantity ISO/TS-15066's `Zr`
and the stopping envelope actually need. The raw `T_map_odom` delta is still
recorded per tick as a diagnostic.

**L4 — dropout passes cleanly; teleport is the finding.**

| arm | scene | displacement | to DEGRADED | to LOST | recovery | post-event ATE |
|---|---|---|---|---|---|---|
| dropout (10 s) | both | — | +0.4 s | +2.9 s | 0.1 s | 0.009 / 0.016 m |
| teleport (pre-reg) | city_block | 6.3 m | never | **never** | — | **8.66 m** |
| teleport (pre-reg) | city_block_b | 3.1 m | +0.2 s | +0.2 s | 0.4 s | 0.020 m |
| teleport_far (post-hoc) | city_block | 7.5 m | +0.2 s | +0.2 s | 0.4 s | 0.009 m |
| teleport_far (post-hoc) | city_block_b | 6.5 m | +0.2 s | +0.2 s | 0.4 s | 0.017 m |

`teleport_far` was added **after** the pre-registered arm produced the miss; it
characterises the detector, it does not stand in for the L4 verdict, which is
the pre-registered row and which **missed on one of two scenes**.

The mechanism, measured at the kidnap tick on `city_block` (a 6.3 m move along a
road flanked by two long parallel facades):

| gate | threshold | value at the kidnap tick | margin |
|---|---|---|---|
| inliers | ≥ 60 | 126 | passed |
| RMS point-to-plane residual | ≤ 0.30 m | **0.2806 m** | passed by 7 % |
| single-tick correction | ≤ 1.00 m | **0.9876 m** | passed by 1 % |

All three passed, so the update was accepted, MAP error went 0.005 m → 7.25 m,
health stayed HEALTHY, and the published sigma_x moved from 1.00 mm to 3.10 mm —
i.e. the covariance said the estimate had got *slightly* less certain while it
had become seven metres wrong. On the very next tick the local map had absorbed
the wrong pose and the matcher reported 519 inliers at 0.037 m RMS: perfectly
healthy tracking of the wrong place, for the remaining 30 s.

Neither health, nor the residual gate, nor the correction gate, nor the
covariance carried the failure. The margins say the detector was three
near-misses from working, which is not a reason to raise thresholds: raising
them trades a missed kidnapping for false LOSTs on ordinary corners.

This reproduces off-MuJoCo, in a different (synthetic, deliberately asymmetric) room:
`tests/test_h7_localization_contract.py::test_a_kidnapping_is_NOT_detected_the_H7_finding`
moves the body 9 m to the opposite side of a mapped circuit and the provider
accepts it as a 0.56 m correction with 714 inliers at 0.23 m RMS. **A kidnapped scan matcher does
not travel to the right answer and report the distance; it converges to the
nearest wrong one.** The design's refutation clause names this outcome exactly:
"the contract needs a jump detector the provider does not have — that is a
design finding."

**L6 — the consumers degrade into refusals, exactly as the hypothesis said, and
that costs success.** The shipped DR-2 ladder was run twice over the frozen
61-cell drift substrate: once as it ships (`consumers-stock-*.json`) and once
with the localizer in the MAP role (`consumers-localized-*.json`). Nothing under
`evals/` was edited; the localized pass binds a runner subclass onto
`run_drift_arms.NavInstructRunner`. In the `*_lost` rungs the scheduled window
withholds the **scan** rather than forcing a health value, so the refusal is
produced by the provider's own staleness logic.

| rung | SR stock | SR localized | false arrivals | collisions | MAP non-healthy ticks | relocalize ok/failed | max jump |
|---|---|---|---|---|---|---|---|
| `calibrated_go2` | 0.1639 | 0.1311 | 0 / 0 | 0 | 215 / 26 663 | 12 / 102 | 0.52 m |
| `go2_aggressive` | 0.0984 | 0.0820 | 0 / 0 | 0 | 179 / 27 501 | 2 / 95 | 0.19 m |
| `go2_degraded` | 0.0656 | 0.0328 | 0 / 0 | 0 | 61 / 28 886 | 0 / 0 | 0.16 m |
| `calibrated_go2_lost` | 0.1475 | 0.0656 | 0 / 0 | 0 | 2 272 / 29 283 | 71 / 506 | **10.47 m** |
| `go2_degraded_lost` | 0.0656 | **0.0000** | 0 / 0 | 0 | 3 085 / 29 626 | 61 / 1 371 | 8.50 m |

Refusals classified: the failure histogram moves out of `none` (success) and
into `planning_error` / `search_error` / `termination`; `false_arrival`,
`control_error` and `grounding_error` stay at **0** on every rung. No consumer
reads a pose past a refusal — `_pose_lost_hold` stops the body and
`_semantic_arrival_verified` declines to claim arrival, which is what turns lost
localization into a lost episode instead of a wrong arrival.

Three things this row says that the bench arms could not. (1) **The
`*_lost` rungs are where the SR goes**: a 3 s scan blackout costs 0.1475 → 0.0656
and 0.0656 → 0.0000, because relocalization from a *partially explored* map
fails far more often than it succeeds (506 failed vs 71 succeeded; 1 371 vs 61)
and each failure holds the body for another tick of a fixed step budget. (2)
**`localization_jump_m` on the eval substrate is 10.47 m**, three orders above the
nominal 0.086 m: a successful relocalization is a large, safety-relevant world
shift, and a stopping envelope that carries this term would have to carry that
number, not the tracking number. (3) One honest RED in the localized pass:
`go2_degraded: 26/27 banded episodes inside [0.21, 93.9]`. That check is on the
ODOM drift injection, not on the localizer, and it moved because the localized
robot walks a different path; it is reported, not suppressed.

**L5 — the covariance is over-confident by an order of magnitude, and the rule
was pre-registered.** `Sigma = sigma_range^2 · inv(H_planar)` (Censi's classical
scan-match covariance), `sigma_range = 0.008 m` taken from the sensor
(`mujoco_lidar.DEFAULT_SCAN_NOISE_STD_M`), `H_planar` the `(tx, ty, rz)`
sub-block of the registration Hessian — conditioning on z/roll/pitch, which are
known for a body on the ground, rather than marginalising them. With ~750
inliers this yields sigma ≈ 0.1-0.2 mm, below the provider's own 1e-6 m² floor,
so the published sigma is the floor's 1 mm against a median error of 6.8 mm.
ANEES is 104 / 234 against a criterion of [0.5, 2.0]. The multiplier that would
make it consistent is **10.2x / 15.3x** in sigma (recorded per arm as
`inflation_to_consistent`); it was measured, not applied.

The reason is not a coding error and is well known: the Censi covariance
describes *range noise given the map*, and here the dominant error is the map's
own accumulated error plus correspondence bias, neither of which a local
registration Hessian can see. Reporting a consistent covariance needs a term
this provider structurally does not have — the same conclusion as L4, from the
other side.

**L7 — latency.** Tracking updates (n = 5 795, single thread): p50 0.75 ms,
p95 2.25 ms, p99 2.43 ms, max 6.76 ms — 13x under the criterion; no-scan ticks
cost 0.01 ms. The five relocalization ticks cost 44.8-78.3 ms (a brute search
over up to 24 keyframe hypotheses, each rebuilding a KdTree): above 30 ms, and
reported separately rather than folded into the p95, because on a robot that
rare path is the one needing its own budget or thread.

**L8 — body-neutral.** `research/.../fake_quadruped.py` is a genuinely different
odometry implementation (0.62 m stride pair vs the Go2's 0.36 m, a 2 % stride
calibration error, a 25 Hz report cadence a 10 Hz consumer reads stale) sharing
nothing with `DriftingOdomProvider` but the two methods the seam uses. Through
the same `LocalizedPoseProvider`, ATE is 0.0102 / 0.0184 m while that body's
own odometry ends 0.73 / 0.99 m out. Zero lines of `src/parcel_robot/localization/`
differ between the two runs; the sha256 of all three modules is recorded in
every result file (`module_sha256`).

## Surprises

1. **The seam took a real localizer with zero product changes, exactly as
   stratum 1 claimed.** `pose.update_provider_from_sim` calls `update_truth`,
   `observation_pose` calls `get_pose`; implementing both was the entire
   integration. `headless_city.py`, `pose.py`, `navigation/` and the eval runner
   are untouched — the L6 pass reaches the shipped `run_drift_arms` by binding a
   runner subclass, not by editing it.
2. **Two contract defects showed up in the first run and were fixed before the
   reported numbers** (both are about the refusal being *observable*, neither
   moves any criterion): (a) relocalization ran on the same tick that detected
   LOST, so a consumer could never see LOST at all; it now runs on the following
   tick. (b) A dropout that reached LOST came back HEALTHY on the first scan
   afterwards, because the tracking streak survived the silence; staleness now
   clears it. Recovery is 0.1 s rather than 0.0 s as a result.
3. **The covariance channel is not a backstop for the health channel.** The one
   place where a wrong pose was catastrophic (L4 city_block), the covariance was
   at its floor. A consumer applying the chance-constrained region test would
   have been *more* confident, not less.

## What this does not prove

The design's own list, unchanged: nothing here speaks to Mid-360 performance,
real IMU coupling, loop closure, or outdoor scale. Added by the run: the scans
are MuJoCo raycasts of hand-built city scenes, so the aliasing that broke L4 is
a property of *these* scenes' geometry as much as of the matcher; the ODOM feed
is a sim-truth-driven error model, not measured leg odometry; and `PLANE_ICP`
against a 12-keyframe local map is a proxy for the FAST-LIO2/Point-LIO class the
corpus recommends, not a measurement of it. No robot hardware exists.

## Product surface added (all flag-off by construction)

`src/parcel_robot/localization/` — `__init__.py` (docstring only), `contract.py`
(194 lines), `gicp_provider.py` (502), `pose_adapter.py` (214). **Nothing in the
runtime imports this package**; it is reached only by the bench and by
`tests/test_h7_localization_contract.py`, which skips when the optional
`localization` extra is absent. `pyproject.toml` gains the `localization`
optional-dependency group. The STRATA anti-goal "no SLAM/EKF in sim (seam only)"
is untouched: installing this changes no runtime behaviour.
