# BARN ROS 2 compatibility evidence

`upstream-mppi-world0-20260803.json` is the integrity manifest for one
headless public-world smoke run. Its sibling `.raw.txt` file is the exact line
written by the pinned evaluator.

This run proves that the cache-only rootfs can build ROS 2 Jazzy, launch Gazebo
Harmonic, start the official evaluator, and complete one public episode. It
does **not** prove any of the following:

- a SingularityCE/SIF compatibility run;
- the documented 500-episode public protocol;
- performance of Parcel's evaluator adapter or production controller;
- an organizer-attested hidden score; or
- top-decile performance.

The evaluated navigation stack was the pinned upstream repository's unchanged
Nav2 MPPI example. The rootfs used Bubblewrap and PRoot only because this host
cannot create Singularity's nested root UID mapping. See
`../../BARN_ROS2_OFFICIAL_COMPATIBILITY.md` for exact commands and the runtime
boundary.

## Parcel hook history and first terminal result

The bounded Parcel world-0 attempt on 2026-08-03 exited before an evaluator row
was written because its launch hook replaced ROS's inherited `PYTHONPATH` and
the child could not import `rclpy`. The defect is corrected and regression
tested in the next content-addressed package.

That corrected package, SHA-256
`ea6904bf4ec5a19b05ad1a147f89d0f09023a135662d5330f24f3c972a4053f2`,
was subsequently used for exactly one bounded world-0 attempt. The Parcel
startup marker and a command-bridge marker appeared, but the evaluator remained
at its pre-trial `Waiting for robot to start moving` state for the 180-second
host bound. It emitted neither `Trial running` nor a terminal row. The ignored
cache log SHA-256 is
`6e74d9e7f7117af0381ce68f17e4710efc96df4f3e431787c3c0b026b9504dbd`
(30,295 bytes).

At that point, this directory contained no Parcel raw row or Parcel evidence
manifest, and the append-only external-eval ledger contained no Parcel ROS 2
entry. A pre-trial liveness stall is not a zero-score episode, and neither
packaging nor startup is a Parcel adapter metric.

The next content-addressed bundle, SHA-256
`5fbccdab524238180c8845e68a3db116d0575b53d7a2d783a1ca6090c4aa8e5f`,
added a 10-second steady-clock pre-trial classifier and was used for exactly
one further world-0 diagnostic. It classified the failure as
`policy_no_translation` after 10.007 seconds: 307 odometry messages, 284 scans,
62 policy commands, 1.052376 rad of yaw response, zero XY response, and zero
forward opportunity. The first policy output was forward `0`, yaw `0.18`, with
`grid_recover_scan status=no_path|obstacle_stop`. This rules out missing sensor
inputs and an unresponsive actuator bridge for that attempt; it localizes the
failure to the policy remaining in rotate-only recovery before the evaluator's
0.1 m start threshold.

The adapter exited `3`, the required-process handler stopped the launch before
`Trial running`, and no evaluator row, result artifact, navigation metric, or
ledger record was created. The read-only ignored-cache launch log is
`.cache/external-evals/runtime/barn-parcel-runs/barn-ros2-parcel-20260803T151036Z-world0-5fbccdab/launch.log`,
SHA-256 `45d2408f437227ee25e7d6ecf77ff7210988b5432249b360e1f1036496fac3e2`
(36,451 bytes). The bundle manifest SHA-256 is
`9a4a17f7a0c0a48465d0d9ab12199dbae59892843659f29eba6a38d214b822de`,
and the liveness node SHA-256 is
`1272462be6eeb0438d0ba4d930b0e5369ca1df1dd6bd11a7449f2326250ac802`.

## Calibrated-v2 world-0 compatibility result

The next evaluator-only transport revision added explicit base-to-LiDAR
calibration, invalidated robot self-returns without treating the occluded space
as free, and bounded scan/odometry synchronization. Exactly one
content-addressed run completed:

- run ID:
  `barn-ros2-parcel-20260803T155459Z-world0-75f7ff4d`;
- bundle SHA-256:
  `75f7ff4dfbf45d36f67cdf3eb3eac6a7e9d05abf48350db449ca23d93b597813`;
- bundle-manifest SHA-256:
  `41256fa28177ddcbdbee294307355cc2af3877f5bf7235ed665057fef7dc26ef`;
- immutable packaged adapter SHA-256:
  `b3a7372c208c47a73553533d1cc3f38b4105e049b4d23ff7db028ad42c60431d`;
- immutable packaged ROS node SHA-256:
  `cae33d3e68339c4b2811a57e4925feed3201730219c0ca024b89d37651e8cf43`;
  and
- ignored-cache launch-log SHA-256:
  `e585c74f1f90d2ce306bbae8547efd0fa1bd2d2e1284bfebe8c03126e5a9ce75`.

The first calibrated scan used LiDAR frame `lidar2d_0_laser`, base frame
`base_link`, scan/odometry stamps `8.825000`/`8.820000`, 720 rays, 686 finite
hits, and 100 invalidated robot self-returns. Its first command was forward
`0.09` m/s and yaw `-0.032552` rad/s with
`grid_track ... status=partial|clear`. Liveness
passed after three commands with 0.038266 m XY response, and the official
runner entered `Trial running`.

The unmodified evaluator wrote the real terminal row stored in
`parcel-world0-20260803T155459Z-75f7ff4d.raw.txt`:

```text
0 0 0 1 100.0070 0.0000
```

Thus, world 0 had zero success, zero collision, one timeout, 100.0070 seconds
elapsed, and metric zero. Evaluator poses moved from approximately
`(-2.25, 3.11)` at trial start to `(-2.66, 5.28)`, then showed no additional
XY progress after about 18 seconds. The sibling result JSON and canonical
append-only ledger record bind the source checkout, package, raw row, runtime,
and negative claims.

This is positive compatibility evidence but negative navigation-quality
evidence. It proves that calibrated transport corrected the self-return root
cause enough to produce a forward command, measurable motion, a trial start,
and an evaluator-owned terminal row. It is only one failed public-world
episode. It is not the public suite or 500-episode protocol, did not use the
upstream-tested Singularity/SIF path, is not organizer-attested, and establishes
no official score, rank, or top-decile result.

A read-only sensor-faithful replay subsequently stalled 0.059 m from the live
terminal pose. The planner still proposed forward `grid_track` motion, but the
packaged legacy 0.8 m full-stop profile suppressed 800 consecutive commands
before the progress watchdog ended the task. This strongly localizes the later
stall to the collision profile, not the earlier LiDAR-self-return defect. It is
post-run diagnostic evidence, not a new episode or score; world 0 remains
consumed and must not be tuned or rerun. See the compatibility report for the
replay contract, thresholds, and disjoint follow-up experiment.

A shutdown-context cleanup guard was added to the working-tree ROS node only
after this result existed. It is deliberately absent from the immutable run
bundle, whose evidence remains pinned to node SHA-256 `cae33d3e...e8cf43`.
