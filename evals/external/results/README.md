# External evaluation run log

This directory keeps the durable, small provenance ledger for external
evaluations. Detailed per-episode reports under `runs/` remain local because
they grow quickly; each ledger record stores their SHA-256 and byte size.

## Recorded runs

| UTC date | Run ID | Change under evaluation | Scope | Key metrics |
| --- | --- | --- | --- | --- |
| 2026-08-03 08:09:27 | `barn-native-20260803T080927158538Z-a3c0f3d7` | Initial unchanged `DirectiveNavigator` sensor-adapter smoke baseline | BARN public world 0, one trial | success 0%; metric 0; collision 0%; stopped outside 100% |
| 2026-08-03 08:09:56 | `barn-native-20260803T080956133648Z-4c921df8` | Initial unchanged `DirectiveNavigator` fixed PR baseline | 10 BARN public worlds, one trial each | success 10%; metric 0.022779; collision 0%; stopped outside 90% |
| 2026-08-03 08:10:48 | `barn-native-20260803T081048744525Z-854b7783` | Unchanged `DirectiveNavigator` fixed-subset baseline | fixed 50-world proxy subset sampled from 300 public worlds, one trial each | success 2%; metric 0.004556; collision 0%; stopped outside 98% |
| 2026-08-03 08:23:47 | `barn-native-20260803T082347318784Z-7a83e78d` | Unchanged PR baseline with pinned Jackal Melodic UST-10 ray model | 10 BARN public worlds, one trial each, 720 rays | success 10%; metric 0.022779; collision 0%; stopped outside 90% |
| 2026-08-03 08:25:42 | `barn-native-20260803T082542002189Z-3d35d19a` | Canonical unchanged fixed-subset baseline with pinned Jackal Melodic UST-10 ray model | fixed 50-world public proxy subset, one trial each, 720 rays | success 2%; metric 0.004556; collision 0%; stopped outside 98% |
| 2026-08-03 08:50:52 | `barn-ab-20260803T085052814213Z-c725af4e` | Initial rolling-grid/A* candidate under production velocity limits | fixed 10-world PR gate, paired one trial each | success 10% -> 10%; metric 0.022779 -> 0.024239; collision 0% -> 0% |
| 2026-08-03 08:56:28 | `barn-ab-20260803T085628637608Z-11434067` | Development-selected cached A*, route invalidation, 360-ray mapping, bounded scan recovery, and eval-only Jackal-clearance profile | 10 development-only public-asset worlds disjoint from validation subset, paired one trial each | success 0% -> 60%; metric 0 -> 0.142760; collision 0% -> 0% |
| 2026-08-03 08:58:36 | `barn-ab-20260803T085836259527Z-02d34dc6` | Frozen PR validation after development-world selection | fixed 10-world PR gate, paired one trial each | success 10% -> 70%; metric 0.022779 -> 0.171962; collision 0% -> 0% |
| 2026-08-03 09:21:04 | `barn-ab-20260803T092104342162Z-8e02235b` | Fixed-subset validation of the development-selected rolling-grid/A* candidate | fixed 50-world public proxy subset, paired one trial each | success **2% -> 36%**; metric **0.004556 -> 0.088595**; collision **0% -> 0%** |
| 2026-08-03 09:26:11 | `barn-ab-20260803T092611245140Z-e1dbace8` | Development-selected vectorized map integration and safe start-cell egress | same 10 development-only public-asset worlds, paired one trial each | success 0% -> 90%; metric 0 -> 0.214258; collision 0% -> 0% |
| 2026-08-03 09:28:17 | `barn-ab-20260803T092817959279Z-c1f7b9d8` | Frozen PR validation of the vectorized/start-egress candidate | fixed 10-world PR gate, paired one trial each | success **10% -> 90%**; metric **0.022779 -> 0.212213**; collision **0% -> 0%** |
| 2026-08-03 09:32:24 | `barn-ab-20260803T093224170877Z-6b24e34f` | Fixed-subset validation of the development-selected vectorized/start-egress candidate | fixed 50-world public proxy subset, paired one trial each | success **2% -> 44%**; metric **0.004556 -> 0.103698**; collision **0% -> 0%** |
| 2026-08-03 09:41:53 | `barn-ab-20260803T094153771735Z-285c7759` | Dev-only hard-margin/comfort-cost experiment | same 10 development-only public-asset worlds | **rejected**: success 0% -> 90%; metric 0 -> 0.130009; collision 0%; minimum signed clearance 0.029992 m |
| 2026-08-03 09:46:04 | `barn-ab-20260803T094604894530Z-16cf960d` | Dev-only peak-comfort-preserving smoothing and positive-closing speed cap | same 10 development-only public-asset worlds | **rejected**: success 0% -> 90%; metric 0 -> 0.212056; collision 0%; minimum signed clearance 0.029995 m |
| 2026-08-03 09:47:27 | `barn-ab-20260803T094727940248Z-f1853b70` | Dev-only 7.5 cm narrow-passage grid diagnostic | same 10 development-only public-asset worlds | **rejected**: success 0% -> 90%; metric 0 -> 0.211572; collision 0%; minimum signed clearance 0.043649 m |
| 2026-08-03 10:09:47 | `barn-ab-20260803T100947191096Z-6c2f97d7` | Dev-only 24.1 m rolling-window ablation | ten additional development worlds (`2 mod 6` through world 56) | **rejected**: success 0% -> 70%; metric 0 -> 0.180785; collision 0%; exactly tied selected grid behavior while mean controller latency increased from 29.54 ms to 66.08 ms |
| 2026-08-03 10:11:36 | `barn-native-20260803T101136419334Z-04a4db9f` | Selected `grid_v1` reference on the additional development worlds | same ten additional development worlds | success 70%; metric 0.180785; collision 0%; minimum signed clearance 0.080146 m |
| 2026-08-03 10:12:30 | `barn-native-20260803T101230143511Z-feb5edb6` | Dev-only reverse-before-scan recovery ablation | same ten additional development worlds | **rejected**: success 70%; metric 0.180785; collision 0%; converted one watchdog stop to a timeout without a score gain |
| 2026-08-03 10:12:47 | `barn-native-20260803T101247065932Z-30418227` | Existing narrow-clearance candidate on the additional development worlds | same ten additional development worlds | **rejected**: success 90%; metric 0.214356; collision 0%; minimum signed clearance fell to 0.056926 m versus 0.080146 m for selected grid |
| 2026-08-03 10:45:14 | `barn-ab-20260803T104514733116Z-776bc659` | Initial positive-closing projected-speed cap with broad comfort slowdown | same ten additional development worlds, paired against the unchanged directive baseline | **superseded dev intermediate**: candidate success 80%; metric 0.178309; collision 0%; minimum signed clearance 0.082223 m |
| 2026-08-03 10:47:30 | `barn-native-20260803T104730730414Z-58b00977` | Existing total-speed cap control | same ten additional development worlds | **rejected control**: success 80%; metric 0.176800; collision 0%; slower than the selected grid reference despite one additional success |
| 2026-08-03 10:50:25 | `barn-native-20260803T105025947731Z-6a2544fa` | Direction-preserving positive-closing hard cap with legacy-cone comfort slowdown | same ten additional development worlds | **promising dev candidate**: success 70% -> 80%; metric 0.180785 -> 0.203749; collision 0%; minimum signed clearance 0.079364 m |
| 2026-08-03 10:51:09 | `barn-native-20260803T105109307670Z-90229994` | Frozen PR check of the direction-preserving projected cap | fixed 10-world PR gate | exact no-regression tie: success 90%; metric 0.212213; collision 0%; minimum signed clearance 0.080676 m |
| 2026-08-03 11:00:01 | `barn-native-20260803T110001471552Z-d8a245ce` | Held-out fixed-subset check of the direction-preserving projected cap | fixed 50-world public proxy subset | **held, not promoted**: exact episode-level tie at 44% success, 0.103698 metric, 0% collision, and 0.080676 m minimum signed clearance |
| 2026-08-03 11:26:01 | `barn-native-20260803T112601986345Z-fc842e52` | Selected-grid reference for the initial reachable-frontier smoke | first ten worlds from the disjoint `3 mod 6` development partition | success 100%; metric 0.251752; collision 0% |
| 2026-08-03 11:26:18 | `barn-native-20260803T112618922790Z-88f0db2d` | Initial map-edge-only reachable-frontier smoke | same ten development worlds | **no-signal tie**: success 100%; metric 0.251752; collision 0%; branch was not exercised |
| 2026-08-03 11:28:38 | `barn-native-20260803T112838198953Z-5c6514a9` | Selected-grid reference on the full disjoint frontier-development partition | all 50 `3 mod 6` worlds; fixed `0 mod 6` validation excluded | success 52%; metric 0.120829; collision 0% |
| 2026-08-03 11:30:50 | `barn-native-20260803T113050563943Z-51f6a439` | Map-edge-only reachable-frontier candidate | same 50 development worlds | **rejected refinement**: exact behavior/metric tie; no reachable window edge existed in the closed components |
| 2026-08-03 11:34:44 | `barn-native-20260803T113444980455Z-965e9e1f` | First observed-prefix frontier refinement | same 50 development worlds | **rejected refinement**: exact tie; geometry-only path compression still crossed unobserved diagonal side cells |
| 2026-08-03 11:41:02 | `barn-native-20260803T114102333078Z-d36e3107` | Connected known-free scan-frontier candidate selected on development only | same 50 development worlds | success 52%; metric **0.120829 -> 0.122056** (+1.02%); collision 0%; controller mean **38.09 -> 91.93 ms** |
| 2026-08-03 11:42:02 | `barn-native-20260803T114202548951Z-75ded0b8` | Frozen PR paired reference for the frontier candidate | fixed 10-world PR gate | success 90%; metric 0.212213; collision 0% |
| 2026-08-03 11:42:27 | `barn-native-20260803T114227832526Z-06fe0798` | Frozen PR frontier confirmation | fixed 10-world PR gate; no PR tuning | success 90%; metric **0.219766** (+3.56%); collision 0%; controller p99 40.47 ms versus 27.56 ms |
| 2026-08-03 11:44:48 | `barn-native-20260803T114448869884Z-b146644a` | Frozen fixed-subset paired reference for the frontier candidate | fixed 50-world public proxy subset | success 44%; metric 0.103698; collision 0% |
| 2026-08-03 11:53:59 | `barn-native-20260803T115359163923Z-a996ed05` | Frozen fixed-subset frontier confirmation | fixed 50-world public proxy subset; no held-out tuning | **held, not promoted**: success 44%; metric **0.104676** (+0.94%); collision 0%; controller mean **41.57 -> 83.61 ms** |
| 2026-08-03 12:30:50 | `barn-native-20260803T123050073485Z-8ef1c169` | Frontier-v2 reference before the single-search latency hill-climb | all 50 previously unused `4 mod 6` development worlds; frozen `0 mod 6` excluded | success 46%; metric 0.107478; collision 0%; minimum signed clearance 0.077339 m; controller mean/p99 95.97/308.92 ms |
| 2026-08-03 12:31:45 | `barn-native-20260803T123145391476Z-6eca8361` | Single observed-connectivity-search frontier-v3 challenger | same 50 `4 mod 6` development worlds and seeds | **selected for frozen confirmation**: success 46%; metric **0.108647**; collision 0%; minimum signed clearance **0.095032 m**; controller mean/p99 **8.12/61.53 ms** |
| 2026-08-03 12:32:18 | `barn-native-20260803T123218714084Z-1d488bb9` | Frozen PR confirmation of development-selected frontier v3 | fixed 10-world PR gate; no PR tuning | success 90%; metric **0.224887**; collision 0%; minimum signed clearance 0.085900 m; controller mean/p99 9.17/77.08 ms |
| 2026-08-03 12:33:17 | `barn-native-20260803T123317614760Z-4c0dea7e` | Frozen fixed-50 confirmation of development-selected frontier v3 | fixed 50-world public proxy subset; no held-out tuning | **experimental latency promotion only**: success 44%; metric **0.106267**; collision 0%; minimum signed clearance 0.079432 m; controller mean/p99 **8.25/59.46 ms** |
| 2026-08-03 15:54:59 | `barn-ros2-parcel-20260803T155459Z-world0-75f7ff4d` | Calibrated-v2 ROS transport: explicit LiDAR extrinsic, robot self-return invalidation, and scan/odometry synchronization | official ROS 2 evaluator, public world 0, one local cache-only compatibility episode | evaluator row `0 0 0 1 100.0070 0.0000`: success 0%; collision 0%; timeout 100%; metric 0; pre-trial liveness passed |

All rows above except the final calibrated-v2 compatibility episode are
`barn-native-headless-non-official`, not Gazebo or leaderboard scores. The
final row was written by a local copy of the unmodified official ROS 2
evaluator, but remains a one-episode, non-official compatibility result rather
than a public-suite or leaderboard score. The first five rows preserve the
unchanged-policy baseline history; the paired native rows are explicitly
feature-gated experimental policies and do not change Parcel's production
default. The canonical unchanged full run succeeded
only in world 42. The first experimental fixed-subset run succeeded in 18/50
worlds. After the development-diagnosed start-cell egress fix and
semantics-preserving map vectorization, the next frozen fixed-subset run
succeeded in 22/50, had 26 progress-watchdog stops and two timeouts, and
produced 21 paired success gains with no success or collision regressions. Its
minimum signed evaluator clearance remained 0.0807 m beyond the circular
Jackal collision boundary.

The three later clearance experiments remained on the development split and
were not run on PR or the fixed 50-world validation subset. All retained zero
collisions, but none improved development success beyond 90%; each reduced
clearance and/or the metric relative to the selected `grid_v1.1` development
result (90%, 0.214258, 0.105215 m minimum signed clearance). They are preserved
as negative results and were not promoted. Historical immutable descriptions
call these development worlds “non-public”; precisely, they are public BARN
asset worlds disjoint from Parcel's fixed validation subset, not hidden contest
worlds.

The next disjoint development slice ruled out two tempting explanations for
the remaining failures. Expanding the rolling window from 16.1 m to 24.1 m
produced the same episode outcomes and trajectories while more than doubling
mean controller time, so loss of the nominal 10 m goal from the window was not
the bottleneck. Blind reverse recovery likewise produced no score gain and is
not suitable for the production 270-degree LiDAR contract. The narrow-clearance
candidate again improved success, but only by reducing the observed clearance
floor; it therefore remains a diagnostic rather than a promoted controller.

The next sensor-only recovery experiment addressed a different failure mode.
In world 14 the selected route remained valid, but the legacy predictive stop
repeatedly zeroed the full cruise command because one reaction horizon could
cross the stop boundary. A projected cap instead limits translational speed by
the LiDAR return's positive closing component, preserving the requested
direction and tangential progress. It never creates reverse or lateral motion,
and it retains the same 0.10 m map inflation, 0.38 m hard stop boundary, and
Go2-compatible velocity limits. On the disjoint development slice it converted
world 14 from a watchdog stop at 5.094 m progress into a 26.3 s success; the
other seven successful episodes were unchanged. Success rose from 70% to 80%
and the metric from 0.180785 to 0.203749 (+12.7%), with zero collisions. The
frozen PR gate was an exact aggregate tie. The held-out fixed 50-world proxy
was also an exact episode-level tie: all outcomes, simulated elapsed times,
distances, metrics, and evaluator diagnostics matched the selected reference.
That establishes no regression on this gate but no broad quality gain, so the
candidate is held as deployment-disabled and is not the selected baseline.
Production defaults and `grid_v1` remain unchanged.

## Reachable-frontier experiment and decision

The selected fixed-50 run had 28 failures: 26 progress-watchdog stops and two
timeouts, with no collisions. All 28 failures spent most of their ticks
in `grid_recover_scan`; six (`120`, `138`, `162`, `180`, `204`, and `252`)
never translated despite evaluator-private minimum clearance of 1.781 m, and
worlds `282` and `288` moved less than 0.14 m. The policy-visible trace was a
repeating `partial`/`no_path` plan followed by rotation. Inspection through the
policy boundary showed the root mismatch: global A* deliberately admitted
penalized unknown cells, while the closed-loop waypoint follower correctly
refused an unobserved compressed segment. Rotating in place did not change that
admission decision.

`grid_frontier_v2` is one feature-gated response to that failure class. It
searches the LiDAR-built, hard-inflated connected component for an observed
free/unknown boundary that makes metric-goal progress, drives a normal
forward-preferred A* route only to that frontier, and requires a new scan before
continuing. If the clipped rolling-horizon target is disconnected, it may also
choose a reachable map-edge subgoal. It receives only goal, odometry, 270-degree
LiDAR, and clock. It cannot access SDF cylinders or the evaluator reference
path; it does not reverse, strafe, weaken map inflation, change the collision
brake, or alter the unicycle evaluator. The implementation defaults to off;
only `configs/navigation/experiments/barn_grid_frontier_v2.yaml` enables it.

Every tuning iteration used the `3 mod 6` development partition, disjoint from
the frozen `0 mod 6` PR/fixed-50 partition. The first ten-world smoke was a
ceiling/no-signal tie and was retained. On the full development partition, the
edge-only and first prefix variants were exact ties and were rejected. The
known-component refinement was frozen only after its native metric improved
from 0.12082860465725213 to 0.12205620634833510, with unchanged 52% success and
zero collisions. It improved mean closest-goal distance by 0.0792 m, but six
episodes improved their metric while nine regressed and mean controller time
rose from 38.0916 ms to 91.9329 ms (p99 126.5508 to 288.7445 ms).

Frozen PR kept 90% success and zero collisions while the metric rose from
0.21221261633254654 to 0.21976646338647504. Frozen fixed-50 kept 44% success and
zero collisions while the metric rose from 0.10369789463625331 to
0.10467639591585230. It rescued none of the 28 failures; the two timeouts became
watchdog stops, mean maximum goal progress improved by 0.1879 m, and mean final
goal distance improved by 0.1948 m. Six successful episodes improved metric,
11 regressed, and 33 tied. Mean episode-minimum clearance decreased by 0.0644 m
(the global minimum changed from 0.080676 m to 0.077735 m), while controller
mean/p99 latency rose from 41.5681/158.6952 ms to 83.6100/314.9232 ms.

The candidate therefore fails the promotion bar: it has no success gain, its
small aggregate metric gain is driven by timing changes among already-successful
episodes, more paired metrics regress than improve, clearance declines, and CPU
latency roughly doubles. It remains an experimental diagnostic, disabled for
deployment; `grid_v1` and production defaults are unchanged. A future attempt
should reuse the primary search state or cache frontier connectivity to remove
the second full-grid traversal, and must be selected on a new development split
before another frozen evaluation.

## Single-search frontier-v3 experiment and decision

`grid_frontier_cached_v3` implements the bounded follow-up above without
changing v2 or `grid_v1`. Under its separate eval-only profile, one Dijkstra
traversal of the currently observed, hard-inflated connected component records
parents and path costs while collecting three ordered outcomes: a reachable
goal cell, a goal-progressing observed scan frontier, or a reachable rolling-map
edge. It therefore never computes the v2 unknown-admitting A* hypothesis that
the observed-only follower cannot execute, and it does not repeat connectivity
search after rejecting that hypothesis. Every route cell and diagonal side
cell must still be observed and outside hard inflation. The policy inputs remain
goal, odometry, 270-degree LiDAR, and clock; the projected collision brake,
0.10 m map margin, 0.6 m/s cap, forward-preferred zero-`vy` tracking, and zero
blind reverse are unchanged.

Selection was frozen before inspecting a previously unused development slice:
all fifty `4 mod 6` worlds, disjoint from the earlier `1`, `2`, and `3 mod 6`
development slices and the frozen `0 mod 6` PR/fixed-50 gates. The challenger
had to retain aggregate and episode-level success, aggregate metric, zero
collisions, and the global clearance floor while reducing both mean and p99
controller latency by at least 20% relative to v2. It passed: success tied at
46% with no paired success changes, metric rose from 0.10747846344051369 to
0.10864666562915955, nine episode metrics improved versus three regressions,
and the clearance floor rose from 0.0773387 to 0.0950320 m. Controller mean/p99
fell from 95.9711/308.9183 ms to 8.1160/61.5328 ms (-91.5%/-80.1%). One former
watchdog stop (world 64) ran to timeout, but it did not change success or
collision status.

The selected challenger was then run exactly once on each frozen proxy gate.
Against the historical same-world/same-seed v2 record, PR retained 90% success
and zero collisions while the metric rose from 0.2197665 to 0.2248872 and the
clearance floor rose from 0.0792551 to 0.0859004 m. Its mean/p99 controller
latency was 9.1723/77.0772 ms versus 8.5321/40.4714 ms for that older ten-world
v2 run, so the small PR sample does not establish a latency improvement. On
fixed-50, v3 retained 44% success and zero collisions while the metric rose
from 0.1046764 to 0.1062673; nine episode metrics improved, six regressed, and
35 tied. The clearance floor rose from 0.0777351 to 0.0794321 m, although mean
episode-minimum clearance fell from 0.4070295 to 0.3986020 m. Controller
mean/p99 fell from 83.6100/314.9232 ms to 8.2483/59.4613 ms
(-90.1%/-81.1%). One v2 watchdog stop (world 264) became a timeout, again
without a success or collision change.

The decision is deliberately narrow: v3 supersedes v2 as the useful
deployment-disabled frontier diagnostic because it removes the duplicated
search burden and improves the native metric without losing a success. It does
not replace `grid_v1` in production. Relative to the selected grid reference,
fixed-50 still has the same 44% success, rescues none of the 28 failures, lowers
the clearance floor slightly (0.0806764 to 0.0794321 m), and converts one of two
timeouts rather than solving the recovery deadlock. The official top-decile
claim therefore remains unproven, and no official or leaderboard score is
claimed.

One initial fixed-50 candidate invocation produced no result and no run ID: the
spawn-worker source hash guard detected a concurrent `src/parcel_robot` edit
(`16c6c90b...` expected, `53a06103...` observed) and aborted before the durable
report/ledger write. This is retained here as an invalidated run, not a metric.
After source edits were paused, retry run
`barn-native-20260803T115359163923Z-a996ed05` completed from a stable hash.

The latest 22.8x native metric improvement is broad regression evidence, but it is
not evidence that the official 0.4880 top-decile target has been reached. Only
the standardized unseen-world, 50 x 10 ROS/Gazebo protocol is eligible for
that claim. The development-selected candidate also retains Parcel's 0.6 m/s
Go2-compatible cap, whereas official BARN standardizes a 2 m/s Jackal; those
embodiment profiles must remain separate.

The canonical baseline and paired validation rows use the pinned Jackal
simulation's 720-ray, 270-degree, 30 m UST-10 model. The first three records
remain as immutable smoke/downsample history.

## ROS 2 runtime compatibility results

Run `barn-ros2-upstream-mppi-20260803T133200Z-world0-01` exercised the pinned
official ROS 2 source in the cache-only Bubblewrap/PRoot diagnostic rootfs. The
unchanged upstream Nav2 MPPI example succeeded on public world 0 in 37.7150 s
with metric 0.1802, zero collision, and zero timeout. The checksum-bound raw row
and integrity manifest are in `barn_ros2/`.

This row is deliberately excluded from Parcel policy comparisons: the Parcel
adapter was not exercised, only one public episode ran, the launch did not use
Singularity/SIF, and no organizer attested it. It is neither a Parcel score nor
official/top-decile evidence.

Run `barn-ros2-parcel-20260803T155459Z-world0-75f7ff4d` then exercised Parcel's
unchanged `grid_v1` controller through the calibrated-v2 ROS adapter. The
official runner entered the trial after the adapter invalidated 100 robot
self-returns and produced a 0.09 m/s first forward command. It moved from
approximately `(-2.25, 3.11)` to `(-2.66, 5.28)`, stopped making XY progress
after about 18 seconds, and the evaluator wrote
`0 0 0 1 100.0070 0.0000`: no collision, timeout, and metric zero. The bundle
SHA-256 is
`75f7ff4dfbf45d36f67cdf3eb3eac6a7e9d05abf48350db449ca23d93b597813`
and its manifest SHA-256 is
`41256fa28177ddcbdbee294307355cc2af3877f5bf7235ed665057fef7dc26ef`.
Checksum-bound result details are in `barn_ros2/`.

This proves that the calibrated sensor transport fixed the prior
`policy_no_translation` compatibility failure; it also proves that the current
controller did not solve this episode. One local public-world timeout is not
the 500-episode public protocol, an official score, rank evidence, or a
top-decile result.

A later read-only, sensor-faithful replay matched the live final pose within
0.059 m and reproduced the stall as 800 consecutive collision-shield stops
while the planner retained a valid forward route. That localizes the new
failure to the packaged legacy 0.8 m full-stop safety profile strongly enough
to define a disjoint experiment, but creates no additional run or metric and
does not authorize tuning or rerunning world 0.

Canonical machine-readable records are in `ledger/runs/`; `ledger/runs.jsonl`
is the append-only analysis index. New `run_barn` CLI invocations add both
automatically. List recent runs from the repository root with:

```bash
.parcel/bin/python -m evals.external.ledger list --limit 10
```

Do not edit an existing record. Run IDs are unique and canonical records are
installed atomically without replacement.
