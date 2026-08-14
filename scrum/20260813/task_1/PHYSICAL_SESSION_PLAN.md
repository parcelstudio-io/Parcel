# Pre-physical-session plan — independent verdict + today's build

**Author:** Fable · **Date:** 2026-08-13 · **Base commit:** `406f9d6`
**Reviewing:** Sol 5.6's physical-readiness recommendation (verbatim copy in
[SOL_5_6_RECOMMENDATION.md](SOL_5_6_RECOMMENDATION.md))
**Evidence:** [RESEARCH_FINDINGS.md](RESEARCH_FINDINGS.md) — 8 agents, 910k
tokens, every claim file:line or URL cited; 3 refute-first panels.

---

## Verdict on Sol 5.6: `ACCEPT_JUDGMENT_REJECT_BUILD_LIST`

**Sol's readiness judgment is right and is adopted.** "Ready for stationary
bring-up, recording, SLAM experiments, shadow navigation, fenced low-speed;
not ready for unsupervised following, streets, stairs, or voice-driven motion
in public" — correct, and it matches the plan's own L0–L8 ladder. The framing
sentence is the best thing in the document and becomes this session's north
star, quoted verbatim on the board:

> the same perception pipeline consumes simulated data, recorded real data,
> and live mounted sensors — and produces timestamped, calibrated,
> uncertainty-aware outputs without owning motion.

**Sol's six-item pre-session build list is rejected for this day.** Five of
the six are code changes to the autonomy stack; none is on the critical path
to a trustworthy dataset, and two are actively dangerous to land the day
before a hardware session. Refute panels were unanimous.

| Sol item | Verdict | Why |
|---|---|---|
| 1. Physical sensor envelope | **PARTIAL — already designed twice** | `bags/schema.py:88-99` mandates 9 envelope keys incl. dual clocks + `calibration_id`; `contracts/v1.py:431-467` carries the same set. Wiring, not design. Day-one need is only the *per-channel* fix (below). |
| 2. TF tree `map→odom→base_link→sensors` | **WRONG for today** | `pose.py:74-78` `Frame` is a 2-member enum with **no transform function anywhere** — this is a new subsystem, not an extension. What is irrecoverable after the bracket is unbolted is the **measured mount extrinsic**, not a TF implementation. Measure today, implement in Wave 1. |
| 3. Physical pose provider replacing `TruthPoseProvider` | **WRONG — dangerous** | Confirmed at `pose.py:945-954`: with no provider attached, `observation_pose` fabricates `PoseEstimate(health=HEALTHY, covariance=ZERO_COVARIANCE, stamp_monotonic_s=0.0)`. A half-wired provider degrades to **confidently wrong**, not fail-closed, and the two gates that would catch it (`pipeline.py` sigma inflation, arrival health) are inert at zero covariance. Multi-day change. |
| 4. Raw recording + deterministic replay | **RIGHT — the whole critical path** | The only item producing artifacts that **cannot be reconstructed after the session ends**. Everything else can be written next week against the bags. This is today. |
| 5. Runtime mode enum (`SENSOR_ONLY`/…) | **WRONG — worst thing to land today** | It would edit `runtime.py` (5,800+ lines, carrying dispatch + health join + collision gate) hours before a hardware session, to solve a problem already solved *harder*: `runtime.py:385-391` refuses any non-`"simulator"` controller from config; `factory.py:111-134` needs four false flags true; **no production code calls `create_control_manager` at all**; and `unitree_sdk2py` is absent from the venv. A Python enum is weaker than an absent SDK. See F-1 below for why building it on the health join would have been actively unsafe. |
| 6. Calibration tooling | **PARTIAL — measure, don't tool** | Intrinsics are recalibrable later from a target. The **mount extrinsic and the clock offset are not** — they exist only while the rig is assembled and powered. Capture those; defer the tools. |

### Sol's external claims — three are wrong, and they matter

- ~~**Go2 front camera is not on the ROS 2 topic set.** Unitree's docs discourage
  DDS for continuous video; the front camera is `/frontvideostream` H.264 /
  VideoClient JPEG / WebRTC. Sol's "record raw camera … using `rosbag2`" does
  not work out of the box.~~ **↑ THIS PARAGRAPH IS WRONG AND SOL WAS RIGHT.**
  Corrected by PS-H against [RISK_ASSESSMENT.md](RISK_ASSESSMENT.md) row 1
  (`CONFIRMED`): the front camera **is** on the DDS topic set, as
  `rt/frontvideostream` carrying `Go2FrontVideoData_` (`time_frame` +
  `video720p`/`video360p`/`video180p`, **JPEG per frame**, ~33 Hz), so a
  `rosbag2` recorder does reach it. The H.264 stream also exists but as RTP over
  multicast `230.1.1.1:1720`, which is not a topic. The D455 remains the clean
  raw-pixel source — that half stands.
- **`unilidar_sdk2` is for the standalone L2**, addressed over its own
  Ethernet/UDP or `/dev/ttyACM0` — *not* the dog's built-in unit, which
  surfaces on `utlidar/cloud` via the robot's DDS. Since we have **both** a
  built-in and an add-on L2, we need **both** paths. Compounded by an
  unresolved L1-vs-L2 question on the built-in (Unitree's page says L2,
  `P5_PROCUREMENT_BOM.md:35` says L1) — **read the model off the physical unit**.
- **`point_lio_unilidar` is a ROS 1 Noetic catkin package** (no `ament`, last
  push 2025-06-05). It cannot coexist with Sol's own Ubuntu 22.04 + Humble
  recommendation on one machine without containers. Not day-one work either way.
- **Isaac Sim is a distraction this week.** Isaac Sim 6.0 supports Ubuntu
  22.04/24.04 only; this dev host is **26.04**. A container/second-box project,
  and unbudgeted against the plan's ratified L3a/L3b/L3c rungs.

### What Sol omitted that could have sunk the session

Every one of these is confirmed absent from the repo, and each would have
produced a debugging day instead of a dataset:

1. **No time synchronization anywhere.** `grep chrony|ntp|ptp|phc2sys|time.?sync`
   across `src/ configs/ deploy/ scripts/` → **zero hits**. `received_monotonic_ns`
   has a per-machine arbitrary epoch, so **cross-device timing is permanently
   unrecoverable unless offset triples are recorded live**. This single
   omission would silently ruin every bag.
2. **Storage bandwidth arithmetic never done.** A D455 at 1280×720/30 color
   RGB8 + depth Z16 is ≈132 MiB/s ≈ **464 GiB/hour** uncompressed (≈58 MiB/s
   ≈205 GiB/hour at 848×480). LiDAR is <1 MiB/s by comparison. Undecided
   resolution/rate/compression plus an unmeasured destination = truncated bags
   **indistinguishable from sensor dropouts**.
3. **Network path.** `configs/robot.yaml:128` still carries the placeholder
   `interface: enp3s0  # replace with the dedicated robot Ethernet NIC`;
   `unitree_sport.py:50-53` hard-fails on a missing `/sys/class/net/<iface>`.
4. **Firmware pin as a *security* precondition.** `adr/0002-firmware-pin.md:11-13`
   treats pre-1.1.13 firmware as **RCE-capable on home Wi-Fi** (CVE-2026-27509 /
   27510 class). Day one attaches a computer to that unauthenticated LAN.
5. **Power/thermal bound on session length** — deferred to Wave 4
   (`PLAN:1271`), so nobody has stated how long an Orin + D455 payload runs on
   the Go2 battery. That number decides how many takes we get.
6. **Mechanical hazards of a sensor-only session** — Sol treats the handheld
   stop as an arming-time concern. Today's hazards are a dog standing up with
   an unsecured 1–2 kg payload, cable snag, and pinch during mounting.

### The one thing Sol omitted that is good news

**`P5_COMMISSIONING_CHECKLIST.md:51-61` already *is* this session** — "Stage 0
— Dry-run (motion disabled)": DDS firewall, camera+LiDAR topics publish, bag
recorder writes `parcel.bag.v1`, e-stop ≤300 ms measured, comms-loss damp,
runtime refuses Sport arm — with an evidence/run-header template. **Do not
author a new checklist. Instantiate this one.**

---

## Two confirmed safety findings (filed, not fixed today)

Both spot-checked by me at the source, both **out of scope for today** (they
touch `runtime.py` / `pose.py`), both filed to `backlog/BLOCKED.md`:

- **F-1 — a latched input-health stop still permits yaw.** `runtime.py:5711-5712`:
  when `translation_allowed` is false, the command is rebuilt as
  `VelocityCommand(vyaw=command.vyaw)` — translation is zeroed, **rotation
  survives**. A robot with latched-failed sensor inputs can still spin in
  place. This also refutes Sol item 5 concretely: a `SENSOR_ONLY` mode enforced
  at the health join would have inherited exactly this hole.
- **F-2 — the no-provider pose fallback fabricates confidence.** `pose.py:945-954`
  returns `health=HEALTHY`, `covariance=ZERO_COVARIANCE`, `stamp_monotonic_s=0.0`
  built from `observation.position`. Fail-open by construction, and it is the
  fallback a half-wired physical provider lands in.

---

## The plan: one deliverable, `parcel-capture`

> **Everything today serves one sentence: when the dog powers down, we hold a
> dataset that is still trustworthy six months from now.**

A **read-only, multi-channel sensor capture and attestation stack** that runs
on the Orin under Humble, records every available channel to MCAP, and emits a
`parcel.bag.v1` sidecar binding the raw bag into Parcel's evidence world by
digest.

### Why this shape

- **Read-only by construction, not by enum.** The capture process is a separate
  package and a separate process that subscribes and never publishes. It
  imports no motion module, constructs no `ControlManager`, holds no lease.
  Enforced by an **import-graph pin test** (the precedent is
  `evidence_origin.py`'s leaf pin and RM-1's
  `test_place_graph_imports_no_onnx_torch_or_navigation`). This is Sol item 5's
  *intent*, enforced where it actually holds — and it survives F-1, which the
  health-join version would not.
- **It cannot run in the Parcel venv, and that is the point.** Confirmed:
  `rclpy`, `cyclonedds`, `unitree_sdk2py`, `pyrealsense2`, `cv2`, `mcap`,
  `zstandard` are **all absent**; the venv is Python **3.14.4** on Ubuntu
  **26.04**. The Orin's JetPack 6.2.x is Ubuntu 22.04 / Humble native. So
  capture is a **deploy artifact** developed in-repo, tested on the dev box
  against synthetic publishers, and *run* on the Orin. Corollary: **do not
  install the vendor SDK into the Parcel venv** — its absence is today's
  strongest motion guarantee.
- **Not `bags/`.** The existing recorder is unusable for this and must not be
  edited: payloads are JSON (`recorder.py:111`), the manifest is rewritten
  after *every* message (`recorder.py:116`), it refuses to append to a
  non-empty bag with no `fsync` (`recorder.py:40-41`), and `schema.py:17-18`
  self-declares "metadata-first in the sim MVP". Its `sequence` is a **single
  global counter across all topics** (`recorder.py:94-98,114`) — so per-topic
  drops, the exact thing Sol wants detected, are **invisible**. We keep its
  *schema* (`make_manifest`, `source="hardware"` already accepted at
  `schema.py:254`) and replace its *transport* with MCAP.
- **Per-channel sequence + dual clocks are the two non-negotiables.** They are
  what make a drop provable and a cross-device timestamp recoverable. Nothing
  else on this list is irrecoverable after the session.

### All sensors possible — the channel matrix

Full enumeration in [CHANNEL_MATRIX.md](CHANNEL_MATRIX.md). Confirmed hardware:
**Go2 EDU + add-on Unitree L2 + RealSense D455 + Jetson Orin NX (recording
onboard).** **25 channel rows expanding to 28 channels — 16 LIVE, 7
VERIFY_IN_SESSION, 4 CONFIRM_ON_HAND, 1 AWAITING_HARDWARE — plus 11
payload-field rows.**

> **The fifteen-row table that stood here is SUPERSEDED, not deleted.** It is
> preserved in git history at `dd2e857`. Card **PS-H** replaced it because
> fresh external research ([RISK_ASSESSMENT.md](RISK_ASSESSMENT.md)) refuted
> four of its claims outright, and a session run against a refuted table is how
> a one-shot day is lost. Read the matrix, not a summary of it.

The four refuted claims, because they change what happens on the day:

- **The front camera IS on the DDS topic set** — `rt/frontvideostream` carrying
  `Go2FrontVideoData_`, **JPEG per frame**, ~33 Hz. The H.264 path exists but is
  RTP over **multicast 230.1.1.1:1720**, not a topic. `CONFIRMED`.
- **`sportmodestate`, `utlidar/robot_pose` and `utlidar/voxel_map_compressed`
  are service-gated**, not sensor firmware: they can carry a publisher and emit
  nothing. And the "free vendor SLAM baseline" is **plausibly mutually
  exclusive** with running our own SLAM, because that needs the built-in
  obstacle avoidance off. Open question, one take in each state. `LIKELY`.
- **`lowstate` has no timestamp at all** — only `tick`, a `uint32` ms counter
  that wraps. **`SportModeState.stamp` is the only real source-clock anchor the
  dog emits**, and it rides a service-gated channel. `CONFIRMED`.
- **"20 motor states" is wrong**: `MotorState[20]` is a fixed union array and a
  Go2 has **12 actuated joints** (12–19 are padding). BMS has **no voltage
  field**. There are **two** foot-force arrays, `foot_force[4]` *and*
  `foot_force_est[4]`. `CONFIRMED`.

Ten channels and fields the fifteen-row table missed entirely, all free, all
costing a second session to recover: `range_obstacle[4]` (the only non-LiDAR
proximity sensing on the dog), `power_v`/`power_a` (**the Wave-4 runtime number
the plan says nobody has**), `wireless_remote[40]` (a gap-free 500 Hz copy of
the controller), `utlidar/lidar_state` (settles L1-vs-L2 electronically, plus
packet-loss rate), `utlidar/cloud_deskewed`, `utlidar/robot_odom`,
`utlidar/switch`, `uwbstate`, `fan_frequency[4]`, `temperature_ntc1/2`.

XVF3800 audio (BOM item 5) is **in the post** (`BLOCKED.md:74-97 B3`) — the
matrix carries its slot so it drops in without redesign.

Every channel is recorded with: dual clocks (source + host monotonic),
**per-channel** sequence, `frame_id`, `EvidenceOrigin.PHYSICAL`, calibration
ref, and a health/expected-rate assertion. On the raw DDS wire every topic
carries ROS's `rt/` mangling and a subscriber on the unmangled name is
**silently empty**, so the matrix carries both names per channel and the lookup
has no default.

---

## Today's board — tranche `PS-1`

Cards, OWNS, and gates in [README.md](README.md). Six cards, four parallel.

| Card | Title | Owns |
|---|---|---|
| **PS-A** | Channel matrix + `CaptureEnvelope` (stdlib leaf, per-channel sequence) | `src/parcel_robot/capture/` |
| **PS-B** | MCAP recorder + `parcel.bag.v1` sidecar by digest | `scripts/parcel_capture/record.py` |
| **PS-C** | Clock discipline — offset triples, `ClockMapV1` | `scripts/parcel_capture/clockmap.py` |
| **PS-D** | Preflight: channel discovery, attestation, fail-closed | `scripts/parcel_capture/preflight.py` |
| **PS-E** | Budget + synthetic-publisher rehearsal (full stack, no dog) | `scripts/parcel_capture/rehearse.py`, budget doc |
| **PS-F** | Stage 0 run-sheet, mount-geometry sheet, safety brief | `scrum/20260813/task_1/session/` |

### Explicitly NOT on this board

`runtime.py` · `pose.py` · `navigation/**` · the B5/B6 owner-gated surfaces ·
frozen evals · the `bags/` recorder · any vendor-SDK install into the Parcel
venv · any TF implementation · any Isaac Sim work · **anything that arms
anything**. Standing board rule 8 (no physical arming) carries forward intact.

### Sequencing reversal, recorded

The standing owner decision on file is *"hardware last, sim throughout —
hardware procurement moved to the final phase"* (`backlog/NEXT.md:28-39`,
2026-08-05 adjudication), and `P5_PROCUREMENT_BOM.md:8` still reads
**"⛔ DO NOT PURCHASE YET"** with `P5_COMMISSIONING_CHECKLIST.md:7-9` marked
**"DO NOT EXECUTE"**. Hardware is now on hand and a session is imminent. **The
owner has reversed that sequencing**; this document is the superseding record.
The BOM/checklist banners are updated by PS-F to point here rather than being
silently ignored.

## What today proves, and does not

**Proves:** that a multi-channel physical capture can be attested, recorded,
digested, and replayed with per-channel drop detection and recoverable
cross-device time — demonstrated end-to-end against synthetic publishers on
the dev box.

**Does not prove:** anything about real sensor performance, real timing under
load, real thermal or power behaviour, or that any Unitree topic carries what
we believe it carries. Every one of those is a **session** measurement, and
the honest output of today is a rig that *records the evidence to settle them*
— plus a Stage-0 sheet whose failure branch (mount, measure, photograph,
record nothing) is a legitimate outcome, not a failure.
