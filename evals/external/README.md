# Offline external navigation evals

This folder is a **separate, offline evaluation surface** for asking:

> Can Parcel’s Go2 mid-level navigation stack be scored with the *success definitions*
> used by Habitat, BARN, 3WE, and related navigation challenges — without downloading
> their full scene datasets?

It does **not** claim official Habitat / BARN / 3WE leaderboard participation.
Those challenges usually require their simulators, embodiments, and datasets.
What we *can* do offline is:

1. Implement the **same metric formulas** (SPL, soft-SPL, BARN score, PSC, …).
2. Run **synthetic episodes** that match each challenge’s *task shape*.
3. Record an honest **compatibility matrix**: what works today vs what is blocked.

```bash
# From the repo root, with .parcel active:
python -m evals.external --episodes 20 --seed 7
python -m evals.external --suite pointnav,barn_clutter,socialnav,objectnav,exploration
```

Detailed results JSON is written under the gitignored
`evals/external/results/runs/`; the compact provenance ledger is tracked.

## Archived Habitat runtime gate

Parcel has now materialized and inventoried the exact 23-layer Habitat 2020
image: 87,944 rootfs entries and 7,925,803,803 regular-file bytes. The preserved
baseline01 initialized one CUDA device but failed at the EGL boundary because a
host GLVND client required GLIBC 2.33. Corrected baseline02 used the archived
GLIBC-compatible clients, initialized one CUDA device and one EGL 1.5 device,
and imported Habitat-Sim 0.1.4 under Python 3.6.10 in 561.432697 ms. Its report
SHA-256 is
`be4a6acba149bee47661936ee5a90947b39e22313a411f02d17eeff839c49424`,
its runner SHA-256 is
`4526fdcc3a66864a5792a188a387c7ef27ebe4c3258f92472113cf945e60607c`,
and its ledger ID is
`habitat20-oci-gpu-import-smoke-20260803T145414Z`.

This is only an exact-image CUDA/EGL/import smoke. It constructed no simulator,
loaded no scene, rendered nothing, executed no GPU kernel or navigation episode,
ran no evaluator, and produced no score or rank. See
[the archived OCI runtime contract](HABITAT_2020_OCI_RUNTIME.md) and
[Habitat evidence](results/habitat2020/README.md) for the immutable failure and
passing artifacts.

## Pinned native BARN gate

For the separate ROS 2 Jazzy container route and the exact boundary between a
public compatibility run and an organizer-attested hidden official result, see
[BARN ROS 2 official compatibility](BARN_ROS2_OFFICIAL_COMPATIBILITY.md). Its
read-only readiness doctor is:

```bash
.parcel/bin/python -m evals.external.barn_official_doctor
```

The tested SingularityCE package can be inspected, or explicitly downloaded
and extracted into the ignored cache without installing system packages:

```bash
.parcel/bin/python -m evals.external.barn_runtime_package
.parcel/bin/python -m evals.external.barn_runtime_package --prepare
```

Extraction is a provenance/staging result, not container-execution readiness;
the doctor keeps those gates separate.

A cache-only Bubblewrap/PRoot diagnostic rootfs has now built the unchanged
ROS 2 Jazzy evaluator and run upstream Nav2 MPPI on public world 0. The exact
row was `0 1 0 0 37.7150 0.1802`: success, no collision/timeout, 37.715 s,
metric 0.1802. Checksum-bound evidence is in
[`results/barn_ros2/`](results/barn_ros2/). This proves one upstream
ROS/Gazebo runtime smoke only. It did not use Parcel's adapter, did not use the
upstream-tested Singularity/SIF launch path, and is neither a Parcel score, a
500-episode public report, an official score, nor top-decile evidence.

The first corrected Parcel submission hook reached the adapter but not the
evaluator's 0.1 m trial-start threshold. A classifier-enabled follow-up
localized that historical stall to `policy_no_translation`: uncalibrated
360-degree LiDAR self-returns sealed the rolling grid around the start.
Calibrated-v2 transport then invalidated those robot returns, synchronized scan
and odometry, and completed exactly one public-world-0 episode. It produced a
0.09 m/s first command, passed liveness after three commands, entered
`Trial running`, and the unmodified evaluator wrote
`0 0 0 1 100.0070 0.0000`: no collision, a timeout, and metric zero. The run
ID is `barn-ros2-parcel-20260803T155459Z-world0-75f7ff4d`; checksum-bound raw
and structured evidence is in
[`results/barn_ros2/`](results/barn_ros2/).

This terminal row closes the sensor-compatibility and pre-trial liveness
boundary, not the navigation-quality boundary. The robot stopped making XY
progress after about 18 seconds, well short of the goal. The run used the
cache-only Bubblewrap/PRoot path for one public episode, not the 500-episode
protocol or upstream-tested Singularity/SIF path, and provides no official
score, public-suite result, rank, or top-decile evidence. See
[`BARN_ROS2_OFFICIAL_COMPATIBILITY.md`](BARN_ROS2_OFFICIAL_COMPATIBILITY.md)
for the failed-attempt history, calibration design, and immutable hashes.

A read-only sensor-faithful replay matched the live terminal pose within
0.059 m and reproduced 800 consecutive post-planner collision stops under the
packaged legacy 0.8 m full-stop profile. The planner still proposed forward
tracking. This diagnoses the later timeout without adding a run or score;
consumed world 0 remains excluded from tuning. The compatibility report defines
the exact replay and fresh-corpus one-factor follow-up.

That proposed v7 follow-up is now permanently retired before execution. A
pre-corpus audit found that the globally nearest clustered return could be
tangential while a slightly farther forward return was positive-closing. The
candidate could therefore cross its claimed 0.8 m observed-ray boundary during
one control tick. No v7 corpus, manifest, claim, result, confirmation asset, or
score exists; both entry points authenticate
[`RETIREMENT.json`](development/barn_predictive_shield_v7/RETIREMENT.json) and
fail before writes. IDs 3000--3049 remain reserved. The successor must isolate
the byte-exact historical policy from the candidate source, inspect all 720
normalized rays, account for commanded yaw over the reaction horizon, and
record an independently recomputed certificate for every candidate action.

The terminal ROS 2 row is Parcel's strongest BARN compatibility evidence; the
sensor-only native runner remains the repeatable quality hill-climbing surface.
It loads the actual public world and reference-path assets from a commit-pinned
checkout of the official challenge repository:

```bash
# Fetch all immutable evaluator sources from sources.lock.json.
.parcel/bin/python evals/external/fetch_sources.py

# Fast fixed gate: worlds 0, 6, ..., 54.
.parcel/bin/python -m evals.external.run_barn \
  --worlds pr --trials 1 \
  --description "Describe the exact code/config/model change"

# Fixed 50-world proxy subset sampled from the 300 public worlds.
.parcel/bin/python -m evals.external.run_barn \
  --worlds public --trials 1 --workers 8 \
  --description "Describe the exact code/config/model change"
```

`ParcelBarnAdapter` wraps the unchanged production `DirectiveNavigator`. It
converts only goal, odometry, clock and raw 270-degree LiDAR into Parcel's
observation contract, and converts the returned body command to differential
drive by discarding `vy`. It does not receive SDF geometry, collision truth,
the official path, or optimal path length. Evaluator-owned state alone decides
collision, timeout, success and score.

The runner uses deterministic planar kinematics and a conservative circular
Jackal footprint because Parcel's controller is not yet packaged into the
pinned official Singularity/SIF ROS/Gazebo path. The separate cache-only
upstream-MPPI smoke does not alter this native runner. Every native report is
therefore labeled
`barn-native-headless-non-official`; it is a regression baseline, never a BARN
leaderboard result. Native timing also starts at reset, whereas the pinned
official script starts timing after the first 0.1 m of motion.

`--workers N` parallelizes independent episodes with spawned CPU processes;
the default remains `1`. Episode order, world/trial seeds, policy reset, score
semantics, and latency-sample aggregation are unchanged. Only built-in Parcel
config policies are accepted in parallel mode: arbitrary Python factories fail
closed instead of relying on non-portable lambda pickling. Each worker creates
and closes a fresh policy per episode, while the parent process alone writes
the atomic report and append-only ledger. `compare_barn` accepts the same flag
and applies it independently to both paired arms. More workers improve
throughput on multi-episode suites; they do not turn classical LiDAR ray
casting or kinematics into GPU kernels. GPU-declared policies must use one
worker so model memory is not duplicated and kernels do not contend across
processes.

Parallel recipes pin and verify the navigation config, model declaration,
benchmark adapter, and a deterministic SHA-256 over every sorted
`src/parcel_robot/**/*.py` relative path and file body. The source-tree digest
is included in report policy provenance. If any policy source changes after
the parent builds the recipe, a worker aborts the suite and the parent writes
neither a report nor a ledger entry, preventing mixed-code results.

A 2026-08-03 local throughput check on the 96-core Threadripper host used eight
synthetic, 720-ray episodes with 800 non-interfering cylinders. One worker took
17.93 s, four took 5.61 s (3.20x), and eight took 3.22 s (5.56x). All three
runs produced the same ordered seeds, success/metric values, and SHA-256 of
episode semantics after excluding wall-clock latency telemetry
(`78ad2bf7...e48c8`). This is a scheduler microbenchmark, not a BARN quality
score or a guarantee of identical scaling for model-heavy policies.

### Unchanged-controller baseline

| Run ID | Scope | LiDAR rays | Success | Native metric | Collisions | Stopped outside |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `barn-native-20260803T082347318784Z-7a83e78d` | 10-world PR gate | 720 | 10% | 0.02278 | 0% | 90% |
| `barn-native-20260803T082542002189Z-3d35d19a` | fixed 50-world public proxy subset | 720 | **2%** | **0.00456** | **0%** | **98%** |

Only world 42 succeeded in the full run. All 49 failures were stopped by
Parcel's `navigation_no_progress` guard. This points to a missing global route
and recovery policy, rather than controller inference latency or an unsafe
collision policy. See
[the companion-navigation research and improvement plan](../../docs/COMPANION_NAVIGATION_ARCHITECTURE.md).

The ledger also preserves three earlier smoke/downsample runs. The canonical
table above uses the 720-ray, 270-degree, 30 m UST-10 ray model from the pinned
Jackal Melodic dependency; its outcomes matched the earlier 271-ray runs.

### Paired hill-climbing experiments

The baseline is the default and experimental behavior cannot be selected by
accident. A candidate config must be supplied explicitly and requires both a
stable experiment ID and the feature gate:

```bash
.parcel/bin/python -m evals.external.compare_barn \
  --worlds pr --trials 1 --suite-seed 20260803 --workers 8 \
  --candidate-config path/to/eval-only-navigation.yaml \
  --candidate-id lidar-a-star-v1 \
  --enable-experimental \
  --description "Rolling occupancy grid plus A-star; no deployment change"
```

Use the historical `--worlds public` alias for the fixed 50-world proxy subset
`0,6,...,294` sampled from BARN's 300 public worlds. It is not the complete
public corpus. Both arms receive the
same ordered world/trial keys and episode seeds. Each policy instance receives
only goal, odometry, LiDAR and clock; factory APIs have no SDF or reference-path
argument. Candidate policies are marked `deployment_enabled: false`, and the
default arm continues to construct the unchanged `DirectiveNavigator`.

The comparison report records hashes for the adapter, Parcel policy source
tree, candidate config and model declaration; the append-only ledger commits
that whole report by SHA-256. Besides the official score inputs, the runner now
records evaluator-private diagnostics:

- outcome/failure counts;
- closest, net and maximum goal progress;
- progress per traveled metre;
- minimum signed body-to-obstacle clearance;
- traveled/reference-path ratio and successful-route efficiency; and
- paired success, collision and metric gains/regressions.

These diagnostics are calculated after policy actions from evaluator-owned
state and live under `evaluator_diagnostics`. They never enter a
`BarnObservation`. Policy-provided terminal notes are kept separately and are
not treated as evaluator failure labels.

The first development-selected grid/A* stage produced the following paired
results. The development split uses public-asset worlds disjoint from the
fixed validation subset; the PR and fixed-subset gates were used only after
selection. None is a hidden official challenge world.

| Run ID | Selection role | Baseline -> candidate success | Baseline -> candidate native metric | Collision |
| --- | --- | ---: | ---: | ---: |
| `barn-ab-20260803T085628637608Z-11434067` | 10 development-only public-asset worlds | 0% -> 60% | 0 -> 0.142760 | 0% -> 0% |
| `barn-ab-20260803T085836259527Z-02d34dc6` | frozen 10-world PR validation | 10% -> 70% | 0.022779 -> 0.171962 | 0% -> 0% |
| `barn-ab-20260803T092104342162Z-8e02235b` | fixed 50-world proxy-subset validation | **2% -> 36%** | **0.004556 -> 0.088595** | **0% -> 0%** |
| `barn-ab-20260803T092611245140Z-e1dbace8` | next-stage development-only public-asset split | 0% -> 90% | 0 -> 0.214258 | 0% -> 0% |
| `barn-ab-20260803T092817959279Z-c1f7b9d8` | next-stage frozen PR validation | **10% -> 90%** | **0.022779 -> 0.212213** | **0% -> 0%** |
| `barn-ab-20260803T093224170877Z-6b24e34f` | next-stage fixed-subset validation | **2% -> 44%** | **0.004556 -> 0.103698** | **0% -> 0%** |
| `barn-native-20260803T105025947731Z-6a2544fa` | projected-cap candidate vs selected reference on a disjoint development slice | **70% -> 80%** | **0.180785 -> 0.203749** | **0% -> 0%** |
| `barn-native-20260803T105109307670Z-90229994` | projected-cap frozen PR no-regression gate | **90% -> 90%** | **0.212213 -> 0.212213** | **0% -> 0%** |
| `barn-native-20260803T110001471552Z-d8a245ce` | projected-cap fixed 50-world no-regression gate | **44% -> 44%** | **0.103698 -> 0.103698** | **0% -> 0%** |

Across the first fixed-subset run, the candidate gained 17 paired successes, regressed
on none, and retained zero collisions. It stopped outside the goal in 29
worlds and timed out in three, so passage feasibility and recovery remain the
quality bottlenecks. Its controller p50 was 18.5 ms, but full-suite p95/p99
rose to 115.5/122.0 ms and the maximum was 313.8 ms in long, open scans. That
tail latency is a release blocker even though the quality score improved; map
integration must be optimized or moved off the command deadline.

These numbers are native proxy evidence only. They neither meet nor become
eligible for the official top-decile gate, and the 0.6 m/s Go2-compatible
candidate profile must not be conflated with BARN's standardized 2 m/s Jackal
competition profile.

The next development stage fixed a deterministic raster contract defect: A*
already allowed the occupied robot start cell when escaping its inflation
halo, but cached-route visibility rejected that same start cell and scanned
forever. Visibility now exempts only supercover index zero; every later cell
still must be observed and non-inflated. In parallel, LiDAR evidence updates
were vectorized with exact scalar-oracle tests. The same development split
rose from 60% to 90%, and frozen PR validation rose from 70% to 90%, still with
zero collisions. PR controller latency improved to 2.65 ms p50, 16.24 ms p95,
and 26.48 ms p99; the 143.95 ms maximum still motivates asynchronous planning.
Fixed-subset success increased from 36% to 44%, with 21 paired gains, no success
regressions, and no collisions. Its 8-worker wall-latency percentiles include
deliberate CPU contention and are not single-robot deployment measurements.

Execution placement is explicit in every report. The native LiDAR ray caster
and planar kinematics are classical CPU code by design, and each policy records
its separately declared device. The current rolling grid/A* model declares
`device: cpu`; no report should infer GPU use merely because a CUDA GPU is
installed on the host.

The projected-cap rows compare two separately recorded native runs on exactly
the same world keys and deterministic seeds; they are not paired against the
unchanged directive stub. The experimental safety policy scales only the
requested velocity magnitude according to obstacle closing speed. It cannot
invent motion, reverse blindly, consume evaluator geometry, or relax the map
inflation and hard stop margins. The fixed 50-world gate matched the selected
reference episode for episode, so the feature remains deployment-disabled and
is not promoted: the held-out result proves no regression, not a general score
gain.

### Frozen BARN top-decile target

`targets/barn_2026_top_decile.json` freezes Table I from the official
[2026 BARN report](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf).
The top-decile cutoff is rank 2 and an official mean score of **0.4880**: top
`ceil(10% * 17) = 2` registered ranks, which also matches the nearest-rank 90th
percentile cutoff among the 12 published numeric scores.

That threshold can only pass after the standardized 50 unseen worlds x 10
Gazebo trials. Native reports expose a numerical gap for hill-climbing, but
always return `official_gate_eligible: false`, `official_gate_pass: false`, and
`leaderboard_claim_allowed: false` regardless of proxy score.

### Append-only run ledger

Every `run_barn` invocation writes a detailed report and automatically creates
an immutable record under `results/ledger/runs/`, plus an append-only
`runs.jsonl` index. The small ledger is tracked; large per-step reports remain
local and are protected by their SHA-256 in the record.

Each record includes UTC date, run ID, human change description, benchmark URL
and commit, Parcel commit/dirty state, adapter/config/model identifiers and
hashes, aggregate metrics, and report checksum/size. Inspect it with:

```bash
.parcel/bin/python -m evals.external.ledger list --limit 10
```

The ledger CLI can record another external evaluator as well:

```bash
.parcel/bin/python -m evals.external.ledger record \
  --benchmark-id example-v1 \
  --benchmark-source https://example.test/evaluator \
  --benchmark-source-commit 0123456789abcdef \
  --description "Initial adapter baseline" \
  --report path/to/report.json
```

---

## Compatibility matrix

| Benchmark | Official run on Parcel Go2? | Offline proxy here? | Embodiment / sensor mismatch | Success definition used |
| --- | --- | --- | --- | --- |
| [Habitat Challenge 2020 PointNav](https://aihabitat.org/challenge/2020/) | **No** — exact runtime now loads a public non-gated test scene/navmesh and renders/actions on GPU, but no Gibson/evaluator episode ran | **Yes** — contract proxy plus exact archived-image GPU scene/action smoke; no PointNav goal or SPL | Habitat is wheeled indoor RGB-D; Parcel is Go2 + pose/LiDAR mid-level | STOP within success radius; report SR + SPL + soft-SPL |
| Habitat 2020 ObjectNav | **No** — Matterport3D + RGB-D + category detector | **Partial** — semantic category goals against in-repo labels / synthetic objects | No MP3D, no real vision | Within radius of *any* instance + oracle visibility proxy |
| [BARN](https://www.cs.utexas.edu/~xiao/BARN/BARN.html) / [BARN Challenge](https://github.com/Daffan/the-barn-challenge) | **Not officially yet** — official runtime is Jackal + Gazebo + 2D Hokuyo + ROS | **Yes** — actual public assets through the sensor-only native runner; synthetic formula tests also remain | Native circular footprint/kinematics ≠ official Gazebo Jackal | Collision-free goal reach; \(s_i = 1_{success}\cdot OT / \mathrm{clip}(AT, 2OT, 8OT)\) |
| [3WE benchmarks](https://3we.org/benchmarks) | **Not admitted** — pinned source audit found task-semantic and evaluator-boundary defects | **Yes** — synthetic PointNav / ObjectNav / Exploration metric shapes only | Different wheeled robot; runner owns `Robot`/Nav2, ObjectNav leaks target coordinates, Exploration is a stub | No eligible score until an organizer-confirmed corrected contract exists |
| Social-HM3D / Falcon SocialNav | **No** — Habitat + ORCA humans on HM3D/MP3D | **Partial** — synthetic pedestrians + PSC / H-coll | Compact seeded agents, not ORCA photo-real crowds | SR, SPL, personal-space compliance, human collision rate |
| MetaUrban / SocialNav city (Parcel docs) | **Stub** — `use_metaurban=True` still `NotImplementedError` | **Yes** — kinematic social PointNav already in Parcel | True MetaUrban needs separate Py3.9 env | Arrival + collision / clearance (existing `social_nav_reward`) |

### Bottom line for a Go2 companion stack

| Question | Answer |
| --- | --- |
| Can we score with Habitat/BARN/3WE **math** today? | **Yes** (this folder). |
| Can we submit to those **leaderboards** today? | **No** without their sim + embodiment + datasets + adapters. |
| What is Parcel actually good at evaluating offline? | Mid-level `(vx,vy,vyaw)` navigation with pose + sparse LiDAR/proximity, on kinematic or MuJoCo city geometry. |
| Biggest blockers for official Habitat | Licensed Gibson scene absent; no PointNav goal/STOP/evaluator episode or Parcel RGB-D policy run; GPS-free visual localization not implemented; different embodiment. The exact archived runtime has now passed CUDA/EGL, simulator construction, public test-scene/navmesh load, RGB-D rendering, and three discrete actions. |
| Biggest blockers for official BARN | Calibrated transport now passes pre-trial liveness and has one evaluator-owned public-world row, but the controller stopped progressing after about 18 seconds and timed out with metric zero. Navigation quality, the 500-episode protocol, the unavailable upstream-tested Singularity/SIF path, organizer attestation, and rank/top-decile evidence remain. |
| Biggest blockers for official 3WE | The pinned alpha contract is not task-correct or injectable: seed/reset/timeouts disagree, PointNav SPL uses displacement, ObjectNav receives hidden coordinates, Exploration does not move, Isaac is a stub, office poses/world disagree, schemas diverge, and backend-specific cohorts are not rankable. Its wheeled holonomic body is not a Go2. A Parcel adapter would not fix those evaluator defects. |
| Closest “real” Parcel eval already in-tree | `HeadlessCityQualityHarness` + stub navigator + living-city collision/TTC gates. |

---

## How success is evaluated (canonical formulas)

### PointNav (Habitat-style)

- **Success** \(S_i = 1\) iff the agent issues STOP (or equivalent halt) within distance \(d_{success}\) of the goal.
  - Habitat 2020 PointNav used \(d_{success} = 0.36\,\mathrm{m}\) (2× agent radius for their LoCoBot-sized body).
  - For Go2 we default to a **configurable** radius (default `0.80 m`) that matches Parcel stub arrival, and also report Habitat’s `0.36 m` as a sensitivity column.
- **SPL** (Anderson et al.):

\[
\mathrm{SPL} = \frac{1}{N}\sum_i S_i \frac{l_i}{\max(p_i, l_i)}
\]

where \(l_i\) is the shortest-path (or Euclidean lower bound when no map) length and \(p_i\) is the agent path length.
- **soft-SPL**: replaces hard \(S_i\) with progress toward the goal (Habitat challenge reports this too).

### ObjectNav (Habitat-style)

- Success if STOP within **1.0 m** of *any* instance of the target category **and** an oracle could see it from that pose without translating (turn-in-place / look allowed).
- SPL uses the shortest path to the **closest** instance from the start (finding a far instance still counts as success but hurts SPL).

### BARN / BARN Challenge score

For environment \(i\):

\[
s_i = 1^{\mathrm{success}} \times \frac{\mathrm{OT}_i}{\mathrm{clip}(\mathrm{AT}_i,\ 2\,\mathrm{OT}_i,\ 8\,\mathrm{OT}_i)}
\]

\[
\mathrm{OT}_i = \frac{\mathrm{PathLength}_i}{v_{\max}}
\]

- Success = reach goal **with zero collisions**.
- \(\mathrm{AT}\) = actual traversal time.
- Challenge Jackal \(v_{\max} = 2\,\mathrm{m/s}\); for Go2 we use Parcel’s configured max forward speed (default `0.6 m/s`) so OT stays meaningful for this body.

### 3WE tasks

- **PointNav / ObjectNav**: SR + SPL over ≥100 episodes for official submissions; we run fewer offline by default.
- **Exploration**: coverage % of free space within a time budget + efficiency (coverage / path length or time).

### SocialNav extras

- **H-coll**: fraction of episodes (or timesteps) with human–robot collision.
- **PSC**: fraction of timesteps with distance to all humans ≥ threshold (commonly ~1.0 m in Social-HM3D; we expose the threshold).

---

## What this folder contains

| Path | Role |
| --- | --- |
| `compatibility.py` | Machine-readable fit records for each benchmark |
| `metrics.py` | SPL, soft-SPL, BARN score, PSC, aggregates |
| `episodes.py` | Synthetic offline episode generators (no downloads) |
| `agents.py` | Baseline agents (straight-line / stub-style) for smoke scoring |
| `runner.py` | Episode loop + JSON report |
| `__main__.py` | CLI entry |
| `schemas/result.schema.json` | Result document shape |
| `sources.lock.json`, `fetch_sources.py` | Immutable contest revisions plus direct Jackal runtime dependencies and reproducible checkout |
| `barn_native.py` | Actual BARN asset loader, native LiDAR/collision runner, and exact score formula |
| `parcel_barn_adapter.py` | Sensor/action adapter around unchanged Parcel navigation behavior |
| `run_barn.py` | Public-world CLI, aggregate latency metrics, report and automatic ledger write |
| `barn_policy_specs.py` | Feature-gated baseline/candidate factories and component provenance |
| `compare_barn.py` | Deterministic paired PR/public experiment runner and ledger integration |
| `generate_safe_valley_v5_corpus.py`, `run_safe_valley_v5.py` | One-shot disjoint generated-corpus freeze and deployment-disabled safe-valley v5 development gate; no confirmation execution mode |
| `generate_safe_valley_guard_v6_corpus.py`, `run_safe_valley_guard_v6.py`, `development/barn_safe_valley_guard_v6/` | Fresh-corpus clearance-guard ablation, failed-preflight provenance, paired result, and rejected frozen decision; confirmation absent |
| `barn_targets.py`, `targets/` | Frozen official target and official-vs-proxy gate evaluation |
| `habitat2020_test_assets.py`, `habitat2020_scene_smoke_py36.py`, `HABITAT_TEST_ASSET_SMOKE.md` | Hash-bound public non-gated test-asset preparation and isolated GPU simulator/render/action compatibility gate; never a Habitat 2020 score |
| `threewe_contract_audit.py`, `results/threewe/` | Fail-closed audit of the pinned 3WE contract; records why no adapter, score, or percentile is currently admitted |
| `ledger.py` | Immutable per-run provenance record and append-only JSONL index |

Optional bridge (not required to run this suite): Parcel’s
`MetaUrbanNavEnv(use_metaurban=False)`, `StubNavigator`, and
`HeadlessCityQualityHarness` remain the in-product evals. This folder stays
import-light so CI can score **metric + protocol correctness** even when MuJoCo
city scenes are not the focus.

---

## Recommended roadmap

1. **Keep using this suite** for metric regression (SPL/BARN/PSC formulas + synthetic hard cases).
2. **Use the pinned native BARN gate** for unchanged-baseline and experimental-config comparisons; never tune from its private evaluator state.
3. **Add rolling LiDAR occupancy mapping, A*/D* Lite, a clearance-aware local planner and bounded recovery**, then ledger each ablation.
4. **Install the pinned official ROS/Gazebo runtime** and reproduce the 50-world × 10-trial protocol before claiming an official BARN result.
5. **Habitat**: the exact archived runtime now passes a public non-gated
   test-scene/navmesh, RGB-D render, and discrete-action GPU smoke. Next wire
   Parcel's RGB-D adapter through a bounded non-challenge test task; pursue
   official-code public validation only after a visual localization stack and
   user-supplied licensed Gibson data exist. Its wheeled/indoor embodiment
   remains different from the outdoor Go2.
6. **3WE**: retain the three targets as explicit unresolved portfolio blockers,
   but do not implement an adapter against the audited alpha revision. Revisit
   only after an organizer publishes a task-correct external-agent interface,
   authoritative episode semantics, and backend-specific rankable cohorts.

---

## References

- Habitat Challenge 2020: https://aihabitat.org/challenge/2020/
- Anderson et al., *On evaluation of embodied navigation agents*, arXiv:1807.06757
- BARN: https://www.cs.utexas.edu/~xiao/BARN/BARN.html
- BARN Challenge 2026 report: https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf
- 3WE benchmarks: https://3we.org/benchmarks
- Social-HM3D / Falcon SocialNav metrics: https://zeying-gong.github.io/projects/falcon/
