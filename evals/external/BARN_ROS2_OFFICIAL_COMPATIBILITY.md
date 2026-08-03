# BARN 2026 ROS 2 official-compatibility path

## Decision

Parcel should use the official ROS 2 Jazzy evaluator as its primary BARN
integration path. It should not install ROS directly on this workstation, and
it should not treat the existing native runner as an official evaluator.

The reasons are concrete:

- The [official 2026 report](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf)
  says the qualifier supported ROS 1 Noetic and introduced ROS 2; five of the
  seventeen 2026 participants used ROS 2.
- The [official ROS 2 repository](https://github.com/Saadmaghani/The-Barn-Challenge-Ros2)
  uses ROS 2 Jazzy, Gazebo Harmonic through `ros_gz`, and a standardized Jackal.
  Its pinned README says SingularityCE 4.3.0 was used successfully.
- ROS 2 Jazzy targets Ubuntu 24.04 and Python 3.12, which satisfies Parcel's
  Python 3.10-or-newer source contract inside the container. The host is Ubuntu
  26.04 with Python 3.14, for which neither Jazzy nor the legacy ROS stacks are
  native supported installations.
- The current ROS 1 challenge source pinned elsewhere in this repository still
  builds `ros:melodic`. That remains useful provenance for the 270-degree UST-10
  native proxy, but it is not the clean production integration for Parcel.

This path preserves two boundaries:

1. Parcel's production controller under `src/parcel_robot` remains unchanged.
2. The organizer's evaluator remains unchanged except for its explicitly
   documented `launch_navigation_stack` submission hook.

## Frozen inputs

The local compatibility contract is frozen in
`targets/barn_ros2_2026_runtime.json`:

| Item | Pin |
| --- | --- |
| Official ROS 2 repository | `d6c575b51e477bd524d634e12cffeb34036fcd1e` |
| SingularityCE version tested upstream | `4.3.0` |
| Noble package version / size | `4.3.0-noble` / `52,091,122` bytes |
| Singularity source archive SHA-256 | `1c881dd269e8420301efb064be5893dd6d73a3bac79f641e3a7878a8f38eada0` |
| Noble `.deb` SHA-256 | `0d165a619a4d7ff094e041c59e1f17490b08c6bd8705378db474c823b0efc0e8` |
| Locally observed `ros:jazzy` manifest | `sha256:31daab66eef9139933379fb67159449944f4e2dcf2e22c2d12cc715f29873e0f` |

The ROS image digest is a local reproducibility pin observed on 2026-08-03. It
does not assert that the organizers' private judge used that exact image.
Official status comes from their hidden evaluation and attestation, not from a
locally selected container digest.

## Current host audit

The workstation has ample compute for local compatibility testing:

- Ubuntu 26.04, Linux 7.0, x86-64;
- 96-core / 192-thread Threadripper PRO 7995WX;
- about 3 TB free on the workspace volume;
- RTX 5000 Ada, 32,760 MiB, driver 595.84;
- unprivileged user namespaces enabled, cgroup v2, and configured subuid/subgid
  ranges.

It currently has no installed Singularity, Apptainer, Docker, Podman, ROS,
Gazebo, CMake, compiler, or Go executable. It does have Bubblewrap 0.11.1,
`unshare`, `dpkg-deb`, `unsquashfs`, and `mksquashfs`. `sudo` is configured but
requires the user's password. No system package was installed.

Run the read-only doctor at any time:

```bash
.parcel/bin/python -m evals.external.barn_official_doctor
.parcel/bin/python -m evals.external.barn_official_doctor --require public
```

The second form exits nonzero until the exact source checkout, tested runtime,
evaluator adapter, built SIF, and validated 500-episode public report are all
ready. No doctor result can grant an official claim; that gate is intentionally
external.

### Provenance-checked user-space runtime staging

The exact 52 MB Noble package has now been downloaded into the ignored Parcel
cache, SHA-256 checked, and extracted without running `dpkg -i`, `apt`, or any
package maintainer script. The extracted `singularity` binary, non-setuid
starter, and configuration are independently checked against hashes frozen in
the runtime manifest. A read-only Bubblewrap probe prints the expected
`4.3.0-noble` version.

This is reproducible with:

```bash
# Default operation is read-only inspection.
.parcel/bin/python -m evals.external.barn_runtime_package

# Explicitly download and extract into .cache; never install a package.
.parcel/bin/python -m evals.external.barn_runtime_package --prepare
```

The helper intentionally reports `container_runtime_claimed_ready: false`.
Printing a version and extracting files are not proof that Singularity can
execute a container or run a definition file's `%post` section.

The deeper user-space probe found the precise boundary on this host:

- `unshare --user true` succeeds, but
  `unshare --user --map-root-user true` fails while writing `uid_map`;
- `kernel.apparmor_restrict_unprivileged_userns=1`;
- the user has valid 65,536-entry subuid/subgid ranges, but `newuidmap` and
  `newgidmap` are absent;
- the extracted runtime can assemble a tiny local-rootfs SIF using the host's
  `mksquashfs`, but cannot execute the SIF or a sandbox; and
- SIF execution first lacks `libfuse.so.2`, then the extraction fallback fails
  when the nested user namespace cannot be mapped.

This matters because the official definition's `%post` must execute `apt`,
`rosdep`, and `colcon` inside the container. SIF assembly alone cannot build the
ROS/Gazebo evaluator. Bubblewrap is therefore a useful diagnostic bootstrap,
not a substitute official-compatible runtime.

The pinned upstream repository currently publishes neither a GitHub release
image nor a GitHub Actions artifact, so there is no provenance-compatible
prebuilt SIF to consume instead.

### Measured cache-only fallback and exact replay

A narrower fallback now works without sudo or host package installation. The
staged Singularity binary assembled the pinned `ros:jazzy` OCI rootfs, whose
index digest is `sha256:31daab66...73e0f` and whose Linux/amd64 child is
`sha256:567b81bc...c30f8`. Bubblewrap performed repository access and package
unpacking; PRoot emulated ownership only for the `dpkg --configure -a` phases.
The pinned evaluator files were then copied exactly as listed in upstream's
`%files` section, `rosdep check` passed, and upstream's plain `colcon build`
completed.

The doctor verifies the PRoot binary, built rootfs, configured ROS packages,
critical evaluator-file hashes, evidence JSON, and raw evaluator row:

```bash
.parcel/bin/python -m evals.external.barn_official_doctor \
  | jq '.rootless_diagnostic'
```

The exact headless replay command for the staged rootfs is:

```bash
parcel_root=/home/jaewoo-jang/Desktop/Projects/Parcel
rootfs="$parcel_root/.cache/external-evals/runtime/barn-current-rootfs"
resolved_rootfs=$(realpath "$rootfs")
test "$resolved_rootfs" = "$rootfs"
test -d "$resolved_rootfs"
test ! -L "$resolved_rootfs"

bwrap \
  --bind "$resolved_rootfs" / \
  --proc /proc \
  --dev /dev \
  --tmpfs /tmp \
  --uid 0 \
  --gid 0 \
  --unshare-pid \
  --unshare-uts \
  --die-with-parent \
  /usr/bin/env \
    HOME=/root \
    ROS_LOCALHOST_ONLY=1 \
    ROS_DOMAIN_ID=177 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    QT_QPA_PLATFORM=offscreen \
    RCUTILS_LOGGING_BUFFERED_STREAM=1 \
  bash -lc '
    source /opt/ros/jazzy/setup.bash
    source /jackal_ws/install/local_setup.bash
    ros2 launch jackal_helper BARN_runner.launch.py \
      world_idx:=0 gui:=false rviz:=false \
      out_file:=rootless_world0_replay.txt
  '
```

Before replay, a non-mutating dependency check is:

```bash
bwrap \
  --ro-bind "$resolved_rootfs" / \
  --proc /proc \
  --dev /dev \
  --ro-bind /run/systemd/resolve/stub-resolv.conf \
    /run/systemd/resolve/stub-resolv.conf \
  --uid 0 \
  --gid 0 \
  --unshare-pid \
  --unshare-uts \
  --die-with-parent \
  /usr/bin/env HOME=/root \
  bash -lc '
    dpkg --audit
    source /opt/ros/jazzy/setup.bash
    cd /jackal_ws
    rosdep check --from-paths . --ignore-src
  '
```

The measured public-world-0 row was:

```text
0 1 0 0 37.7150 0.1802
```

Its immutable evidence manifest and checksum-bound raw row live under
`results/barn_ros2/`. The run used the untouched upstream Nav2 MPPI example,
not Parcel's adapter or controller. It is one episode, used Bubblewrap instead
of the upstream-tested Singularity execution path, forced software rendering,
and isolated ROS discovery with environment variables rather than
Singularity's `--network=none`. Therefore it is runtime compatibility evidence
only: it is not a Parcel score, a 500-episode public report, an official score,
or top-decile evidence. The doctor enforces all four negative claims.

## Evaluator-only adapter

`barn_ros2_adapter.py` is a pure, ROS-independent transport contract.
`barn_ros2_node.py` is its lazily imported ROS executable. The data flow is:

```text
/front/scan + /platform/odom/filtered + sim clock + odom-frame goal
                              |
                              v
                  BarnRos2SensorFrame
                              |
                              v
                 ParcelBarnAdapter
                              |
                              v
             unchanged DirectiveNavigator
                              |
                              v
       forward velocity + yaw rate -> /cmd_vel TwistStamped
```

The adapter cannot represent world SDF, collision truth, reference paths,
optimal path length, or hidden-world identity. It transports no lateral
velocity because the evaluator's Jackal is differential drive. That does not
remove lateral motion from the Go2 production controller.

The node deliberately runs the policy at 10 Hz even if the Gazebo LiDAR emits
more quickly. Parcel's evaluated controller uses a 0.1-second control contract;
executing controller state transitions at the sensor's raw rate would silently
change recovery durations and acceleration behavior.

The ROS executable requires an explicit navigation configuration:

```bash
python3 -m evals.external.barn_ros2_node \
  --navigation-config /opt/parcel/configs/navigation/experiments/barn_grid_v1.yaml \
  --goal-x 10.0 \
  --goal-y 0.0 \
  --ros-args -p use_sim_time:=true
```

This command belongs inside the compatibility image and should be launched
only from the official repository's documented navigation-stack hook.

## Safe preparation and installation boundary

The best execution path remains a Singularity container, not native ROS. The
source and runtime package are now locally staged; system-package installation
still requires the user to enter their sudo password.

Fetch or re-verify the immutable evaluator source:

```bash
.parcel/bin/python evals/external/fetch_sources.py barn_challenge_ros2_2026
```

If the user authorizes system changes, install the build prerequisites listed by the
[SingularityCE 4.3 guide](https://docs.sylabs.io/guides/4.3/admin-guide/installation.html):

```bash
sudo apt-get update
sudo apt-get install -y \
  autoconf automake build-essential cryptsetup fuse2fs fuse \
  libfuse-dev libseccomp-dev libsubid-dev libtool pkg-config runc \
  squashfs-tools squashfs-tools-ng uidmap wget zlib1g-dev golang-go
```

Do **not** currently prefer a non-setuid source build on this Ubuntu 26.04
host. The host lacks its compiler/Go prerequisites, and the measured root-UID
mapping failure means that a successfully compiled binary would still not
have a functional user-namespace execution path. The following source-build
shape becomes viable only after those two doctor gates pass:

```bash
mkdir -p /home/jaewoo-jang/Desktop/Projects/Parcel/.cache/tools/src
cd /home/jaewoo-jang/Desktop/Projects/Parcel/.cache/tools/src
wget https://github.com/sylabs/singularity/releases/download/v4.3.0/singularity-ce-4.3.0.tar.gz
echo "1c881dd269e8420301efb064be5893dd6d73a3bac79f641e3a7878a8f38eada0  singularity-ce-4.3.0.tar.gz" | sha256sum --check
tar -xzf singularity-ce-4.3.0.tar.gz
cd singularity-ce-4.3.0
./mconfig --without-suid \
  --prefix=/home/jaewoo-jang/Desktop/Projects/Parcel/.cache/tools/singularity-ce-4.3.0
make -C builddir
make -C builddir install
```

Then prepend the explicit installation path for that shell and verify it:

```bash
export PATH="/home/jaewoo-jang/Desktop/Projects/Parcel/.cache/tools/singularity-ce-4.3.0/bin:$PATH"
singularity version
```

The expected semantic version is exactly `4.3.0` (`4.3.0-noble` for the pinned
Debian package). A distribution Apptainer, direct Bubblewrap rootfs, or a
different Singularity version may be useful diagnostically, but none is the
upstream-tested 2026 ROS 2 path and none may silently satisfy the readiness
gate.

### Parcel submission-hook package and bounded world-0 attempt

`barn_ros2_submission.py` now generates a content-addressed submission bundle.
It copies the unchanged Parcel controller and evaluator-only sensor adapter,
hashes every packaged file, verifies the exact clean upstream checkout, and
derives a launch overlay from the pinned official bytes. The transformation
replaces only `launch_navigation_stack`; `barn_runner.py` and all evaluator
success, collision, timeout, and metric behavior remain byte-identical.

Preparation is explicit and does not claim a metric:

```bash
PYTHONPATH=src:. .parcel/bin/python \
  -m evals.external.barn_ros2_submission --prepare
```

The first bounded public-world-0 launch did **not** complete an episode. The
failed package was
`d2edf5a714fbf923efd700605b48fdb47d1bd66319ddc6108e3a69252f79e5aa`.
Gazebo, the Jackal, and the official runner started, but the generated
`ExecuteProcess.additional_env` replaced ROS's inherited `PYTHONPATH` with the
Parcel paths. The child therefore failed at `import rclpy` and the required
process handler shut the launch down before the evaluator wrote a row.

The ignored launch log is
`.cache/external-evals/runtime/barn-parcel-runs/barn-ros2-parcel-20260803T135902Z-world0-d2edf5a7/launch.log`;
its SHA-256 is
`ecca710e12151dc8120267743177151a70c038e15321d2b30b7bb98c4a8efd09`
and its size is 37,330 bytes. The exact blocker is covered by a regression
assertion that the hook preserves the inherited ROS `PYTHONPATH`.

The corrected package is
`ea6904bf4ec5a19b05ad1a147f89d0f09023a135662d5330f24f3c972a4053f2`;
its manifest SHA-256 is
`57512f20678ced4a91ef742657e08bda3a0c125a4992ce41a11daa05d00868ea`.
Before its one bounded run, all 114 manifested files, the package hash, the
exact hook-only overlay derivation, the clean upstream commit and four critical
evaluator hashes were reverified. A Bubblewrap preflight also imported ROS,
loaded the message types, and constructed the packaged controller. The harness
result lookup was corrected to match upstream `get_pkg_src_path()`, which
writes under repository-level `The-Barn-Challenge-Ros2/res`; this changed only
the evidence reader, not evaluator or controller behavior.

Exactly one public-world-0 attempt then ran as
`barn-ros2-parcel-20260803T140839Z-world0-ea6904bf`. It reached the Parcel
startup marker, and the Clearpath command bridge reported receiving a stamped
velocity message. However, the official runner remained at `Waiting for robot
to start moving`, never emitted `Trial running`, and never produced a terminal
row. The outer one-episode process bound stopped the launch after 180 seconds.
The ignored launch log is
`.cache/external-evals/runtime/barn-parcel-runs/barn-ros2-parcel-20260803T140839Z-world0-ea6904bf/launch.log`;
its SHA-256 is
`6e74d9e7f7117af0381ce68f17e4710efc96df4f3e431787c3c0b026b9504dbd`
and its size is 30,295 bytes. It contains one startup marker, one command-bridge
marker, no adapter exception, no trial-start marker, and no terminal marker.

This is a pre-trial liveness failure, not an evaluator timeout or a zero-score
episode: the evaluator's 100-second trial clock begins only after it observes
0.1 m of translation. That bundle could not distinguish a sensor callback,
policy-command, mux, or actuator-side stall because it did not log the first
sensor frames or command values.

A third content-addressed bundle,
`5fbccdab524238180c8845e68a3db116d0575b53d7a2d783a1ca6090c4aa8e5f`,
added only the regression-tested evaluator-side startup classifier. Over a
ten-second steady-clock window it counts odometry, scans, and policy commands,
measures forward/yaw opportunity, and anchors XY response after the first
positive-forward command. It either proves causal translation or publishes
zero and exits nonzero as `no_inputs`, `policy_no_translation`, or
`actuator_no_response`; it does not alter navigation commands, evaluator
logic, or production code.

Exactly one bounded world-0 diagnostic ran as
`barn-ros2-parcel-20260803T151036Z-world0-5fbccdab`. It classified
`policy_no_translation` after 10.007 seconds with 307 odometry messages, 284
scans, 62 policy commands, 1.052376 rad of yaw response, zero XY response, and
zero forward opportunity. The first command was forward `0`, yaw `0.18`, with
`grid_recover_scan status=no_path|obstacle_stop`. Sensors and yaw actuation
were therefore live; the policy never offered causal forward translation. The
adapter exited `3`, required-process shutdown occurred before `Trial running`,
and no terminal row was written. The read-only log is
`.cache/external-evals/runtime/barn-parcel-runs/barn-ros2-parcel-20260803T151036Z-world0-5fbccdab/launch.log`,
SHA-256 `45d2408f437227ee25e7d6ecf77ff7210988b5432249b360e1f1036496fac3e2`
(36,451 bytes). The bundle manifest SHA-256 is
`9a4a17f7a0c0a48465d0d9ab12199dbae59892843659f29eba6a38d214b822de`.

### Root cause of `policy_no_translation`

A read-only source/geometry audit and causal replay localize the rotate-only
failure to robot self-returns being mapped as external obstacles. The official
ROS Jackal uses a 360-degree, 720-ray front LiDAR mounted 0.12 m ahead of the
base. A radius-0.05 m center cylinder intersects the sensor plane, so rear rays
can hit the robot at approximately `0.12 - 0.05 = 0.07 m`. The transport
discarded the scan frame and sensor extrinsic, then passed every range as if it
originated at the base center. A 0.07 m endpoint immediately exceeds the
occupancy threshold; hard inflation by the 0.32 m robot radius plus 0.10 m
margin then seals every neighbor around the start. A* clears only the exact
start cell, expands one node, returns `no_path`, and recovery emits the observed
0.18 rad/s yaw command indefinitely. The downstream `obstacle_stop` note
corroborates the near return but is not what zeroed translation—the navigator
had already selected `vx=0`.

The same current controller was replayed offline without another BARN launch.
The clean public world-0 ray geometry had a 2.1013 m nearest hit and produced a
0.09 m/s `grid_track` partial route. Adding only the analytic 0.07 m self arc
reproduced the exact first command and note: forward `0`, yaw `0.18`,
`grid_recover_scan status=no_path|obstacle_stop`, with one expanded A* node.
The goal and rolling-window clip are not causal: the clean frame finds a
partial route. The native proxy did not expose this because its 270-degree scan
origin is the robot center and raycasts only world geometry, never the robot's
own body.

The production-relevant repair belongs at sensor normalization: resolve the
timestamped LiDAR-to-base transform, transform finite hit endpoints into the
body frame, and invalidate endpoints inside a calibrated robot self-mask.
Invalid is intentionally not infinity—an occluded self-ray must not clear
unknown space behind the body. Nearby external obstacles remain valid. Missing
or stale calibration/TF and unsynchronized pose must fail closed. Do not lower
inflation, clear an arbitrary ring, crop all rear rays, or modify the evaluator
robot. The immutable diagnostic log did not retain raw ranges, so the next
authorized smoke was required to record a bounded policy-visible scan summary,
including frame, scan/odometry timestamps, and the filtered count, before treating
the replay as runtime-confirmed. No additional ROS/Gazebo run was made during
the diagnosis itself; the separately authorized run is documented below.

### Calibrated-v2 compatibility episode

The sensor-normalization repair above was then implemented in the
evaluator-only ROS transport: explicit base-to-LiDAR calibration, robot
self-return invalidation, and bounded scan/odometry synchronization. Exactly
one new content-addressed world-0 run completed as
`barn-ros2-parcel-20260803T155459Z-world0-75f7ff4d`. Its immutable package
SHA-256 is
`75f7ff4dfbf45d36f67cdf3eb3eac6a7e9d05abf48350db449ca23d93b597813`
and its package-manifest SHA-256 is
`41256fa28177ddcbdbee294307355cc2af3877f5bf7235ed665057fef7dc26ef`.
The packaged adapter SHA-256 is
`b3a7372c208c47a73553533d1cc3f38b4105e049b4d23ff7db028ad42c60431d`;
the packaged ROS node SHA-256 is
`cae33d3e68339c4b2811a57e4925feed3201730219c0ca024b89d37651e8cf43`.

The runtime scan summary reported frame `lidar2d_0_laser`, base frame
`base_link`, scan/odometry stamps `8.825000`/`8.820000`, 720 rays, 686 finite
hits, and 100 invalidated robot self-returns. The first policy command changed
from the diagnosed rotate-only recovery to forward `0.09` m/s and yaw
`-0.032552` rad/s with `grid_track ... status=partial|clear`. Startup liveness
passed after three commands with 0.038266 m of XY response, and the official
runner emitted `Trial running`.

The local copy of the unmodified official evaluator then owned and wrote this
terminal row:

```text
0 0 0 1 100.0070 0.0000
```

The columns are world, success, collision, timeout, elapsed seconds, and
navigation metric: the episode had no collision, timed out after 100.0070 s,
and scored zero. Logged evaluator poses show translation from approximately
`(-2.25, 3.11)` when the trial began to `(-2.66, 5.28)`, followed by no further
XY progress after about 18 seconds. The launch-log SHA-256 is
`e585c74f1f90d2ce306bbae8547efd0fa1bd2d2e1284bfebe8c03126e5a9ce75`.
The checksum-bound raw row and result JSON are in `results/barn_ros2/`, and a
canonical append-only ledger record now exists for this run.

This closes the specific sensor-compatibility and pre-trial liveness boundary:
calibrated transport enabled a forward command, physical translation, trial
start, and a terminal evaluator row. It does **not** close the navigation-quality
boundary. This is one failed public-world episode in a cache-only
Bubblewrap/PRoot diagnostic runtime using the official Jackal embodiment and
software rendering. It is not the 500-episode public protocol, an
upstream-tested Singularity/SIF run, an organizer-attested official result, a
public-suite score, rank evidence, or top-decile evidence.

### Read-only diagnosis of the mid-episode stop

No second ROS/Gazebo episode was run. A post-run analytic replay used the exact
immutable policy bundle and world-0 SDF, a 360-degree/720-ray scan at the pinned
`+0.12 m` LiDAR extrinsic, the robot self-cylinder, the calibrated normalizer,
and ideal 0.1-second unicycle dynamics. Its first scan closely matched the live
finite/self-return counts (690/99 versus 686/100), and it stalled at
`(-2.6221, 5.2353)`, only 0.059 m from the evaluator's terminal pose.

At replay stall onset, the grid planner still emitted
`grid_track ... status=planned` and requested `vx=0.5647` m/s. The nearest
normalized cluster was 0.8592 m away at 0.8639 rad. The packaged
`barn_grid_v1.yaml` safety profile uses `stop_distance_m: 0.8`, implicit
`predictive_mode: stop`, and `reaction_time_s: 0.12`, so its projected boundary
was `0.8 + 0.5647 * 0.12 = 0.8678 m`. The shield therefore zeroed forward
motion while preserving yaw. Replay produced 800 consecutive `obstacle_stop`
decisions before the progress watchdog emitted `navigation_no_progress` at
step 881; it produced zero planner-recovery commands. The watchdog ended the
deadlock but did not cause its onset.

Evaluator-private geometry, consulted only after the run, places the live final
base 0.811707 m from the nearest obstacle surface, with 0.491707 m signed body
clearance and about 0.0141 m distance from the public reference path. These
facts, plus the 0.059 m terminal-pose match, strongly localize the timeout to a
legacy collision-profile feedback deadlock rather than `no_path`, actuator
failure, or a coordinate-frame error. This remains strong replay evidence, not
a live mid-episode command trace: the immutable node logged only its first
policy command.

Do not tune or rerun consumed world 0. The smallest clean follow-up is a paired,
sensor-faithful experiment on a newly generated, hash-frozen development
corpus: compare the exact packaged `predictive_mode: stop` reference with an
otherwise identical `projected_speed_cap` challenger while retaining the same
0.8 m hard boundary. Predeclare success, timeout, collision, minimum clearance,
stalled duration, and latency gates. Test a 0.38 m Jackal-scale profile only on
another fresh split if that one-factor challenger still deadlocks. A future
live run should sample pre/post-shield commands, nearest range/bearing/closing
fraction, projected boundary, planner/map phase, watchdog state, sensor
freshness, and measured response.

After the row was already written, the working tree added a shutdown-context
guard so cleanup does not publish after `rclpy` has invalidated its context.
That cleanup is not part of this run. The immutable evidence intentionally
continues to pin the packaged node SHA-256 `cae33d3e...e8cf43`; no artifact or
claim above is rewritten to match later source.

## Protocol and upstream discrepancies

The official score is the mean over 50 hidden environments and ten trials per
environment. Success requires entering the one-metre goal region without any
collision before 100 seconds. Each successful episode scores

\[
s_i = \frac{OT_i}{\operatorname{clip}(AT_i, 2OT_i, 8OT_i)},
\qquad OT_i = \frac{\text{shortest path length}_i}{2\ \mathrm{m/s}}.
\]

Two defects exist in the pinned public ROS 2 helper scripts:

- `test.sh` loops from 7 through 49, so it runs only 43 of the documented 50
  public indices.
- `report_test.py` recomputes the historical `4*OT` lower clip even though
  `barn_runner.py` writes the current `2*OT` metric in the sixth output column.

Do not patch evaluator timing, collision, success, or metric behavior. For
local compatibility, invoke the explicit set `0, 6, ..., 294` ten times each
and aggregate the metric already written by `barn_runner.py`. Preserve raw
outputs and report both discrepancies to the upstream maintainers. The
organizer's private pipeline remains the authority for an official result.

## GPU relevance

GPU availability is not a BARN readiness gate. The official 2026 page promises
an Intel Xeon CPU for simulation and explicitly says the physical final has no
GPU. The upstream wrapper contains `--nv`, so this workstation's RTX can be
exposed for a local experiment, but the rolling grid/A-star policy and Gazebo
benchmark should remain CPU-capable. A CUDA-only policy would not be a credible
official or real-Jackal submission. In short: GPU passthrough is optional for
local profiling, no GPU is promised for the official simulation judge, and the
physical final explicitly offers no GPU. The successful world-0 smoke above
used software rendering and no GPU passthrough.

## What remains non-official

All of the following are useful but non-official:

- Parcel's deterministic native planar runner;
- the official public assets run in a locally built container;
- the uniformly sampled public 50-world by ten-trial suite;
- a score produced by correcting or replacing the upstream report script;
- any run without the organizer's hidden worlds and attestation.

The ICRA 2026 hard deadline was 2026-05-08 and the event has concluded.
Therefore, after the public container passes, the remaining official step is to
ask the organizers whether they will accept and attest a post-event hidden
evaluation. Until they confirm and run it, `official_score_available` and
`leaderboard_claim_allowed` remain false by construction.
