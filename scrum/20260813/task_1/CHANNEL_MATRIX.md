# Channel matrix — every sensor we can possibly record

**Date:** 2026-08-13 · **Hardware:** Go2 **EDU** · add-on Unitree **L2** ·
RealSense **D455** · Jetson **Orin NX** (recording onboard)
**Rewritten by:** card **PS-H** of corrective tranche PS-2, against
[RISK_ASSESSMENT.md](RISK_ASSESSMENT.md) "Channel-matrix corrections".
**Machine-readable twin:** `src/parcel_robot/capture/channels.py`
(`CHANNELS`, `PAYLOAD_FIELDS`) — the two are pinned against each other in both
directions by `tests/test_capture_envelope.py`.

This is the authoritative enumeration behind card **PS-A**. The owner's
directive is *use all the sensors possible*, so the default posture is: **if a
channel exists and costs little to record, record it.** Storage is cheap
relative to a second physical session; an unrecorded channel is gone forever.

---

## ⚠ Everything below is documentation, not measurement

Every row is **documentation-derived**: vendor message definitions, issue
threads, and field reports of *other* Go2 EDUs. **Not one line of it has been
read off our unit.** Each row therefore carries a confidence marker, and each
marker is a statement about the quality of the *source*, never about our
hardware:

| Marker | Means |
|---|---|
| **CONFIRMED** | Multiple independent sources, or a message definition read directly |
| **LIKELY** | One credible source, or a first-hand field report we cannot reproduce |
| **UNVERIFIED** | Inference or a single ambiguous mention, recorded as a guess so it can be falsified |

**The first 45 minutes of the session exists to replace every one of these with
a reading from our unit.** Until then, presence is a prior and never evidence:
a channel is present when, and only when, a message has been received from it
(board rule 3, *unknown = absent*). `channels.py` carries this as
`DECLARATION_BASIS = "documentation_derived"` and
`MEASUREMENT_WINDOW = "session_first_45_minutes"`.

### Status values

| Status | Means | Failure mode it warns about |
|---|---|---|
| **LIVE** | Expected present on the confirmed hardware, produced by sensor firmware | — |
| **VERIFY_IN_SESSION** | The topic is expected to *exist*, but an on-robot **service** fills it. It can carry a publisher and emit nothing | Indistinguishable at the DDS layer from a bad network config; costs session time to triage |
| **CONFIRM_ON_HAND** | In the BOM or the vendor kit; the box may not be in the room | — |
| **AWAITING_HARDWARE** | Known absent today; the slot exists so it drops in without redesign | — |

---

## ⚠ `rt/` — the failure that is completely silent

On the **raw DDS wire** — the vendor SDK or a bare CycloneDDS reader, with no
`rclpy` — every ROS 2 topic name carries ROS's mangling: `rt/lowstate`,
`rt/utlidar/cloud`, `rt/frontvideostream`. **A raw-DDS subscriber on the
unmangled name receives zero messages and raises no error.** It looks exactly
like a robot that is not publishing, and on a one-session day that is hours of
debugging aimed at the wrong layer. `CONFIRMED`.

Every DDS row below therefore states **both** names, and
`channels.py:subscribe_name(channel_id, naming)` **has no default argument** —
a caller must say which stack it is on, and a bare string is refused. A DDS row
whose wire name is not the mangled form of its ROS name cannot be constructed.

Under `rclpy` / `unitree_ros2` (which is what `ros2 bag record -s mcap` uses,
and PS-G makes that the recorder of record) you pass the **ROS** name and the
middleware mangles it for you.

---

## THE COUNT, reconciled

Three numbers were in circulation and each answered a different question:
`README.md:53` said **15**, this matrix had **19 rows**, PS-A built **22
channels**. They are now three named quantities, and every document quotes all
three:

| Quantity | Value | What it counts |
|---|---|---|
| **Channel rows** | **25** | Numbered rows of table A below |
| **Channels** | **28** | The *recording unit*: an independently-arriving, independently-dropping stream, each with its own sequence space |
| **Payload-field rows** | **11** | Table B: fields *inside* a channel's message. **Not channels.** |

Rows **7, 14 and 15** each bundle two streams that arrive and drop separately
(`lf/lowstate` + `lf/sportmodestate`; "Infrared ×2"; "accel + gyro", which the
RealSense SDK delivers as two motion streams at two rates), so 25 rows expand
to 28 channels. **PS-A was right to expand them and the rule is kept:**
collapsing a bundled row would reintroduce, at small scale, the exact defect
this tranche exists to fix — a stereo pair sharing one counter cannot say which
eye dropped.

Table B exists because "not a channel" was, in the PS-1 matrix, indistinguishable
from "not recorded" — and four of its rows were missing entirely. A field has no
independent arrival, so minting it as a channel would fabricate a sequence space
and double-count its bytes.

---

## A. Unitree Go2 EDU — via DDS

EDU is the edition that exposes CycloneDDS directly; AIR/PRO would need root or
firmware patching, which `adr/0002-firmware-pin.md` forbids.

| # | Channel | ROS name | raw-DDS name | Rate | Payload clock | Status | Conf |
|---|---|---|---|---|---|---|---|
| 1 | Built-in LiDAR cloud | `utlidar/cloud` | `rt/utlidar/cloud` | ~10 Hz | `header.stamp` | LIVE | CONFIRMED |
| 2 | Built-in LiDAR IMU | `utlidar/imu` | `rt/utlidar/imu` | ~200 Hz | `header.stamp` | **CONFIRM_ON_HAND** | LIKELY |
| 3 | Vendor LiDAR odometry | `utlidar/robot_pose` | `rt/utlidar/robot_pose` | ~10 Hz | `header.stamp` | **VERIFY_IN_SESSION** | LIKELY |
| 4 | Vendor voxel map | `utlidar/voxel_map_compressed` | `rt/utlidar/voxel_map_compressed` | ~1 Hz | **none** | **VERIFY_IN_SESSION** | LIKELY |
| 5 | Sport mode state | `sportmodestate` | `rt/sportmodestate` | ~50 Hz | **`stamp` (TimeSpec)** | **VERIFY_IN_SESSION** | LIKELY |
| 6 | Low state | `lowstate` | `rt/lowstate` | ~500 Hz | **none — `tick` only** | LIVE | CONFIRMED |
| 7 | Low-freq mirrors | `lf/lowstate`, `lf/sportmodestate` | `rt/lf/…` | ~10 Hz | as 6 / as 5 | LIVE / VERIFY_IN_SESSION | LIKELY |
| 8 | Wireless controller | `wirelesscontroller` | `rt/wirelesscontroller` | on change | **none** | LIVE | CONFIRMED |
| 20 | **Built-in LiDAR state / health** | `utlidar/lidar_state` | `rt/utlidar/lidar_state` | ~1 Hz | `stamp` | LIVE | LIKELY |
| 21 | **Deskewed LiDAR cloud** | `utlidar/cloud_deskewed` | `rt/utlidar/cloud_deskewed` | ~10 Hz | `header.stamp` | LIVE | LIKELY |
| 22 | **Vendor odometry with covariance** | `utlidar/robot_odom` | `rt/utlidar/robot_odom` | ~10 Hz | `header.stamp` | **VERIFY_IN_SESSION** | LIKELY |
| 23 | **LiDAR switch — SUBSCRIBE-ONLY** | `utlidar/switch` | `rt/utlidar/switch` | on change | **none** | **VERIFY_IN_SESSION** | LIKELY |
| 25 | **UWB state** | `uwbstate` | `rt/uwbstate` | ~20 Hz | **none** | **CONFIRM_ON_HAND** | LIKELY |

**Rows 3, 4, 5 and 22 are service-gated, and that is a correction.** They are
produced by on-robot **services**, not by sensor firmware. The topic can exist,
advertise a publisher, and emit nothing — and there is a first-hand report of
exactly that on a shipping unit. The PS-1 matrix marked them LIVE, which would
have sent an operator hunting a DDS misconfiguration that was not there.

**And the free vendor baseline may be mutually exclusive with our own SLAM.**
Running our own SLAM plausibly requires turning the built-in **obstacle
avoidance off** — and that is what drives rows 3, 4 and 22. `LIKELY`. **This is
an open question, not a plan.** It needs one take in each state to settle, and
until it is settled nobody should assume we get both a vendor baseline and our
own SLAM from the same take. Row 5 is gated by the same class of dependency.

**Row 5 is CRITICAL despite being service-gated**, because field rows 1 and 2
live inside it: `range_obstacle[4]` is the only non-LiDAR proximity sensing on
the dog, and `stamp` is the only real source-clock anchor the robot emits. **If
`sportmodestate` is silent, there is no device clock at all** and the bracketed
physical sync ritual becomes the session's only cross-device timing evidence.

**Row 2 is not LIVE, and it is the reason PS-J exists.** The PS-1 matrix
transcribed it as "LIVE if published"; a conditional is not a confirmation.
Worse: **two independent reports have `utlidar/imu` emitting |accel| of order
1e24 m/s²**, which a receipt-count probe attests as *healthy*. A channel is not
healthy because messages arrive. Assert |accel| = 9.81 ± 1 m/s² and |gyro| <
0.05 rad/s at rest before believing any IMU in this rig.

**Row 20 is the cheapest high-value row on the table.** `utlidar/lidar_state`
settles the L1-vs-L2 contradiction **electronically** — firmware, software and
SDK version strings plus the serial number — instead of by squinting at a
sticker, and it carries cloud and IMU **packet-loss rate** and rotation speed,
which turns "the cloud looked thin" into a per-take number. 256 B at 1 Hz.

**Row 23 is the one topic here the vendor stack uses as an INPUT.** Writing
`ON`/`OFF` to `utlidar/switch` toggles the built-in LiDAR. **We subscribe and
never write** — board rule 1, and nothing in `parcel_robot.capture` can write to
a transport at all (pinned by an AST scan over the package). We record it
because it is the only evidence of who toggled the LiDAR mid-session and when,
which otherwise reads in the bag as an unexplained sensor dropout.

**Row 25 and row 18 are two candidate paths to ONE measurement.** Both are
budgeted, because we do not know which works and assuming a channel away is the
permissive error — but a consumer must not treat them as independent
observations of the owner's position.

## B. Go2 front camera — **it IS on the DDS topic set**

| # | Channel | ROS name | raw-DDS name | Payload | Rate | Status | Conf |
|---|---|---|---|---|---|---|---|
| 9 | Front camera | `frontvideostream` | `rt/frontvideostream` | `Go2FrontVideoData_` = `time_frame` + `video720p`/`video360p`/`video180p`, **JPEG per frame** | ~33 Hz | LIVE | CONFIRMED |
| 24 | Front camera H.264 | — **not a topic** — | — | H.264 elementary stream, **RTP over multicast `230.1.1.1:1720`** | unknown | **VERIFY_IN_SESSION** | LIKELY |

**This corrects the PS-1 matrix's central claim about this camera.** It said the
front camera is "not on the DDS topic set" and that "Sol's *record raw camera
via rosbag2* does not work here". **Both are wrong.** `rt/frontvideostream`
carries JPEG frames at ~33 Hz, so a ROS-side recorder reaches it after all. The
H.264 path also exists, but as **RTP over multicast**, which is not a topic and
which a multicast-unfriendly switch or NIC configuration drops silently.

**The cost changed with the correction.** JPEG per frame is roughly an order of
magnitude more bandwidth than the H.264 stream the PS-1 budget assumed for this
channel — see §G. Recording the front camera is now a **decision**, not a free
extra: 720p JPEG, 360p JPEG, or the H.264 path at ~0.5 MiB/s.

`time_frame`'s epoch and units are unread, so its payload clock is
**UNVERIFIED**. Row 24's RTP timestamp is a 90 kHz counter with a random initial
offset: without RTCP sender reports it anchors to nothing.

## C. Add-on Unitree L2 LiDAR — via `unilidar_sdk2`

| # | Channel | Path | Rate | Payload clock | Status | Conf |
|---|---|---|---|---|---|---|
| 10 | L2 point cloud | Ethernet/UDP or `/dev/ttyACM0` | ~10–20 Hz | device stamp | LIVE | CONFIRMED |
| 11 | L2 IMU | same | ~200 Hz | device stamp | LIVE | LIKELY |

**Two LiDARs, two SDKs — this is a genuine finding.** `unilidar_sdk2` addresses
the **standalone L2** over its own transport; the **built-in** unit surfaces on
`rt/utlidar/cloud` via the robot's DDS. We have both, so we need both paths —
and the payoff is real: two LiDARs at a measured relative extrinsic is a
**cross-validation asset** for every SLAM candidate.

**PS-F must verify the two FOVs overlap before final torque.** No post-hoc
LiDAR-to-LiDAR calibration tool can recover an extrinsic between two units that
never share a view, and the bracket is unrecoverable once unbolted.

**Unresolved, resolved electronically in-session:** the built-in model. Unitree's
page says L2; `P5_PROCUREMENT_BOM.md:35` says L1. **Read it off row 20**, not off
either document. The L2's factory IP `192.168.1.2` collides conceptually with the
Go2's `192.168.1.7` and with the commonest home subnet — put it on a second NIC.

## D. RealSense D455 — via the RealSense SDK

| # | Channel | Stream | Payload clock | Status | Conf |
|---|---|---|---|---|---|
| 12 | Color | RGB8 | **UNVERIFIED** | LIVE — **the raw-pixel source** | CONFIRMED |
| 13 | Depth | Z16 | **UNVERIFIED** | LIVE | CONFIRMED |
| 14 | Infrared ×2 | Y8 left + right | **UNVERIFIED** | LIVE | CONFIRMED |
| 15 | D455 internal IMU | accel + gyro (BMI055) | **UNVERIFIED** | LIVE | LIKELY |

Resolution/rate/format is a **budget decision**, not a default — see PS-E.
1280×720/30 color+depth ≈ **131.8 MiB/s** ≈ 464 GiB/h; 848×480 ≈ **58.2 MiB/s**
≈ 205 GiB/h. **This arithmetic was independently re-verified and is correct.**

**The IR pair is NOT "nearly free" — that was wrong.** Two Y8 streams equal the
Z16 stream **exactly**: **+40% disk, +50% USB**. `CONFIRMED`. 720p with all
streams enabled is ≈1327 Mb/s, **above Intel's own ~1200 Mb/s USB ceiling** and
≈194 MB/s against rosbag2's observed **~110–120 MB/s recorder ceiling** — two
independent ceilings, both below the ask. Record the IR pair anyway (it is the
only channel that works in the dark and the only independent stereo baseline),
but record it as a **decision with a stated cost**.

**Payload clocks are UNVERIFIED for every D455 stream, and that is a risk to
PS-I.** The `pyrealsense2` pip wheel is reported to cost UVC **per-frame
metadata** — which is exactly the device timestamp the plan calls
non-negotiable. There is no wheel for Python 3.11+; worst case is a 2–3 h source
build. D455-on-Orin-NX also has open unfixed reports of ~80% RGB drop and a dead
IMU. Confirm all of this on the bench tonight, not on the dog.

## E. Platform telemetry — Orin NX

| # | Channel | Source | Payload clock | Status | Conf |
|---|---|---|---|---|---|
| 16 | CPU/GPU load, thermal zones, power rails, NVMe throughput | `tegrastats` | none (host clock only) | LIVE | CONFIRMED |

Not a "sensor", and exactly the evidence the plan defers to Wave 4
(`PLAN:1271`). It costs nothing to log and it is the only way the session can
answer *how long can we run* and *did we thermally throttle mid-take*.

## F. Conditional — confirm on hand at preflight

| # | Channel | Source | Payload clock | Status | Conf |
|---|---|---|---|---|---|
| 17 | GNSS ZED-F9P (NMEA/UBX, NTRIP) | `P5_PROCUREMENT_BOM.md:31` item 4 | **GNSS time — absolute** | CONFIRM_ON_HAND | LIKELY |
| 18 | UWB owner fob (range/bearing), vendor path | BOM optional B; usually ships with Go2 | UNVERIFIED | CONFIRM_ON_HAND | UNVERIFIED |
| 19 | XVF3800 mic array (4-mic + AEC ref) | BOM item 5 | none | AWAITING_HARDWARE — `BLOCKED.md:74-97` B3, in the post | CONFIRMED |

**If the ZED-F9P is on hand it is the best clock in the rig**, because GNSS time
is absolute. PS-I should record it even with no fix, and note whether a PPS line
is wired. PS-D probes for all three and reports honestly.

---

## Table B — payload fields of record

These live **inside** a channel's message. They arrive when their parent
arrives, they cost no extra bandwidth, and they are **never separately
sequenced**. Four of them were missing from the PS-1 matrix entirely; the rest
correct a claim it made.

| F | Field | Inside | Spec | Conf | Why it is here |
|---|---|---|---|---|---|
| 1 | **`range_obstacle[4]`** | row 5 | `float32[4]` | CONFIRMED | **MISSED.** The **only** non-LiDAR proximity sensing on the dog. Free, inside a message we already record, unrecoverable after power-down. Units and modality undocumented — record now, characterise later against LiDAR range |
| 2 | **`stamp`** | row 5 | `TimeSpec` | CONFIRMED | **The only real source-clock anchor the dog emits**, and it arrives on a service-gated channel. All of PS-I's dog↔host offset work rests on this one field |
| 3 | **`tick`** | row 6 | `uint32` ms, **wraps** | CONFIRMED | **CORRECTION.** `LowState` has **no timestamp field at all**. `tick` orders messages within one unwrapped span and is not an absolute time; differencing it across a wrap gives a ~49.7-day jump |
| 4 | **`power_v` / `power_a`** | row 6 | `float32`, `float32` | CONFIRMED | **MISSED.** **The Wave-4 runtime number the plan says nobody has** (`PLAN:1271`) — sitting in a message we were already recording. Also the documented substitute for the pack voltage the BMS does not carry |
| 5 | **`wireless_remote[40]`** | row 6 | `uint8[40]` | CONFIRMED | **MISSED.** A gap-free, time-aligned copy of the handheld at **500 Hz** — strictly better than the event-driven topic for reconstructing *when* an operator acted, and a free take-annotation track. 40 B |
| 6 | `motor_state[20]` | row 6 | `MotorState[20]`, **0–11 actuated, 12–19 padding** | CONFIRMED | **CORRECTION.** The PS-1 matrix said "20× motor". It is a fixed **union** array sized for the largest Unitree platform; **a Go2 has 12 actuated joints**. As written, an analyst would have reported 8 dropped channels. Each entry also carries `mode` and the **`q_raw`/`dq_raw`/`ddq_raw`** triplet beside `q`/`dq`/`ddq`, plus `tau_est`, `temperature`, `lost` |
| 7 | `foot_force[4]` **and** `foot_force_est[4]` | row 6 | `int16[4]` ×2 | CONFIRMED / LIKELY | **CORRECTION.** There are **two** arrays. Record both — their difference is free evidence about which is sensed and which is derived. Both are **raw counts** from an air-pressure contact proxy with **no published units, gain or offset**, so a zero-offset take (all four feet off the ground) at session start is the only thing that makes them interpretable later |
| 8 | `bms_state` | row 6 | `soc, current, cycle, cell_vol[15], bq_ntc[2], mcu_ntc[2]` | CONFIRMED | **CORRECTION.** `BmsState` **has no voltage field**. Pack voltage = `sum(cell_vol[15])`, or more directly `LowState.power_v` (F4). A consumer that reads a voltage field here finds nothing and may substitute a default |
| 9 | `imu_state` | row 6 | quat[4], gyro[3], accel[3], rpy[3], temp | CONFIRMED | The 500 Hz body IMU: the densest inertial channel in the rig, the reference against which row 2's 1e24 m/s² pathology is judged, and where the sync ritual's taps will appear |
| 10 | **`fan_frequency[4]`** | row 6 | `uint16[4]` | LIKELY | **MISSED.** The robot's own statement about its thermal state, 8 B, inside a message we already record — Wave-4 thermal evidence for free |
| 11 | **`temperature_ntc1/2`** | row 6 | two thermistors | LIKELY | **MISSED.** Distinct from the per-motor temperatures in F6 and from the BMS thermistors in F8. Units and placement undocumented |

---

## G. Recording posture and bandwidth

Every channel is recorded with the PS-A `CaptureEnvelope`: **per-channel**
sequence (never global), dual clocks (device source + host monotonic + host
realtime), `frame_id`, `EvidenceOrigin.PHYSICAL`, calibration ref, health.
Per PS-G, `ros2 bag record -s mcap` is the **recorder of record** — it is the
only format the downstream SLAM and calibration tools can open — and
`parcel-capture` is the attestation, clock-discipline and sidecar layer.

**Bandwidth reality, corrected.** The PS-1 matrix claimed the non-D455 channels
"together are a rounding error (<2 MiB/s)" and that "record everything costs
almost nothing beyond the camera decision". Measured against the PS-E budget
model with PS-H's corrections applied:

| Group | Worst-case rate | Verdict |
|---|---|---|
| Every channel that is neither the D455 nor the front camera (20 of 28; 19 budgeted, the mic is absent) | **≈3.0 MiB/s** | Still a rounding error against the D455. The "<2 MiB/s" figure is now false — PS-H added a second point cloud and an `Odometry_` with two covariance blocks |
| Go2 front camera, row 9 (JPEG) | **≈6.6 MiB/s** | **More than twice every other non-D455 channel combined.** No longer free |
| Go2 front camera, row 24 (H.264) | ≈0.5 MiB/s | The cheap alternative, if we can capture multicast RTP |
| D455 @ 1280×720/30 C+D+IR | ≈184.8 MiB/s | Still the dominant term: 94.8% of that profile's total |
| D455 @ 848×480/30 C+D | ≈58.5 MiB/s | 85.3% of that profile's total |

Two ceilings sit **below** the 720p all-streams ask and neither is negotiable on
the day: Intel's ~1200 Mb/s USB budget, and rosbag2's observed ~110–120 MB/s
recorder throughput. The floor of the profile table is now ~108 GiB/h even at
424×240, because the front camera's JPEG load is fixed under every profile.

**What we lose by not recording a channel:** it does not exist. Every other
defect on today's board is fixable next week against the bags; an unrecorded
channel requires another physical session, and there is no second session.

---

## Open questions this document does not settle

1. **Vendor SLAM vs our SLAM.** Whether rows 3/4/22 can coexist with our own
   SLAM, or whether obstacle-avoidance-off makes them mutually exclusive. One
   take in each state.
2. **The built-in LiDAR model.** L1 or L2 — settled electronically from row 20.
3. **Whether the service-gated rows emit anything at all** on our unit.
4. **Whether `Go2FrontVideoData_` populates one resolution or all three**, which
   is a 5× difference in row 9's bandwidth.
5. **Whether the RealSense wheel preserves per-frame device timestamps** on this
   Orin, which decides whether PS-I has a D455 clock to fit at all.
6. **Whether the multicast RTP stream (row 24) reaches the Orin** through the
   session's network path.
7. **`foot_force` units, gain and offset** — undocumented; only a zero-offset
   take makes the numbers interpretable later.
8. **`range_obstacle` units and modality** — undocumented.

## What this document does not prove

It does not prove that any of these channels exists on **our** unit, that any
of them carries what we believe it carries, that any declared rate is the rate
it will publish at, or that any payload clock means what we think it means.
Every row is transcribed from documents and field reports about other robots.
It does not prove the bandwidth model either: the D455 arithmetic was
independently re-verified, but every non-camera figure is a stated worst-case
assumption, and the destination's sustained write rate has been measured only on
the dev host. The session's first 45 minutes is where this document stops being
a hypothesis.
