# Risk assessment — PS-1 plan vs fresh external research

**Author:** Fable · **Date:** 2026-08-13 · **Evidence:** 7 agents, 721k tokens,
5 external-research briefs + 2 refute-first assessors, every external claim
URL-cited. In-repo claims re-verified by me at source before being recorded here.

## Headline: the plan's diagnosis holds; its deliverable set was mis-scoped. Two defects are mine.

The four "unrecoverable after power-down" quantities I identified — cross-device
clock offsets, mount extrinsics, per-channel drop provenance, unrecorded
channels — are the right four, and the research strengthens rather than
weakens that framing. But the board I wrote has **two structural defects that
would have produced a bad session**, and both are planning errors, not
execution errors.

### D-1 (mine, blocking): no card owns the ingest layer

`scripts/parcel_capture/record.py:1488` — `resolve_live_source()` raises
`LiveSourceUnavailableError` for **every** transport ("There is no live backend
on this card"). `preflight.py:974` defaults to `unavailable_reader_factory`.
**Verified by me at source.** The executors did exactly what their cards said;
the cards never assigned the DDS subscriber, the RealSense loop, or the L2
reader to anyone. PS-1 as scoped produces a recorder with nothing to record.

Consequence if unfixed: the morning of the session is spent writing brand-new
subscriber code against a live, battery-limited robot. That is the single most
likely way the day yields no usable data — not a driver failure, a
**missing-component** failure.

### D-2 (mine, blocking): the bag format is unreadable by everything downstream

`record.py:152-158` writes `MCAP_PROFILE = "parcel-capture"` and
`message_encoding = "parcel.capture.envelope.v1+raw"` with a JSON schema
record. **Verified at source.** No tool in the next milestone — GLIM, FAST-LIO2,
Point-LIO-ROS2, KISS-ICP, Multi-LiCa, ros2_calib, direct_visual_lidar_calibration
— can open that. We would spend a physical session recording data that only
Parcel can read, to feed a pipeline made entirely of tools that read `rosbag2`.

**The fix for both is the same and it is cheap:** make
`ros2 bag record -s mcap` the **primary** recorder (zero new ingest code,
readable by every downstream tool), and demote `parcel-capture` to the
**attestation + clock-discipline + sidecar** layer, which is where its value
actually is and where it is genuinely good. `sidecar.py` gains an adapter that
consumes a rosbag2 MCAP and takes per-channel counts from `ros2 bag info`
(today `record.py:794` refuses any non-Parcel encoding).

---

## Channel-matrix corrections (external, cited)

My matrix was written from general platform knowledge and one verification
pass. Fresh research corrects it substantially. Confidence marked per item.

| # | I claimed | Actually | Conf |
|---|---|---|---|
| 1 | Front camera "not on the DDS topic set" | **It is**: `rt/frontvideostream`, `Go2FrontVideoData_` = `time_frame` + `video720p`/`video360p`/`video180p`, **JPEG per frame**, ~33 Hz. H.264 exists too but as RTP-over-**multicast 230.1.1.1:1720**, not a topic | CONFIRMED |
| 2 | `sportmodestate`, `utlidar/robot_pose`, `utlidar/voxel_map_compressed` = LIVE | **Service-gated.** Topic exists with a publisher and emits nothing if the service is down — indistinguishable from a bad DDS config. First-hand report of exactly this on a shipping unit | LIKELY |
| 3 | Vendor odometry + voxel map are a "free SLAM baseline" | **Plausibly mutually exclusive with our own SLAM**: running your own SLAM requires turning the built-in obstacle avoidance **off**, and that is what drives the `utlidar` SLAM outputs. Needs one take in each state to settle | LIKELY |
| 4 | Topic names as listed | On the **raw DDS wire** (no rclpy) every name carries ROS 2's `rt/` mangling — `rt/lowstate`, `rt/utlidar/cloud`. A raw-DDS subscriber on the unmangled name gets **zero messages and no error** | CONFIRMED |
| 5 | "20 motor states" | `MotorState[20]` is a fixed union array; **a Go2 has 12 actuated joints**. Indices 12–19 are padding — as written, someone would read 8 dropped channels | CONFIRMED |
| 6 | BMS carries voltage | **`BmsState` has no voltage field.** Pack voltage = `sum(cell_vol[15])` or `LowState.power_v` | CONFIRMED |
| 7 | 4 foot-force sensors | **Two arrays**: `foot_force[4]` *and* `foot_force_est[4]`. Record both — their difference is free evidence about which is sensed. And they are `int16` **raw counts**, an air-pressure contact proxy with no published units, gain, or offset | CONFIRMED / LIKELY |
| 8 | `lowstate` has a usable timestamp | **It has no timestamp field at all** — only `tick`, a `uint32` ms counter that **wraps**. `SportModeState.stamp` (a device `TimeSpec`) is the only real source-clock anchor | CONFIRMED |
| 9 | IR pair is "nearly free" | **Wrong.** Two Y8 streams equal the Z16 stream exactly: **+40% disk, +50% USB**. 720p all-streams ≈1327 Mbps, above Intel's own ~1200 Mbps ceiling, ≈194 MB/s vs rosbag2's observed ~110–120 MB/s recorder ceiling | CONFIRMED |
| 10 | (bandwidth arithmetic) | **Correct** — 720p RGB8+Z16 = 131.8 MiB/s, 848×480 = 58.2 MiB/s, independently recomputed | CONFIRMED |

**Channels I missed entirely, all free, all costing a second session to recover:**
`range_obstacle[4]` inside `SportModeState` (the **only** non-LiDAR proximity
sensing on the dog); `power_v` / `power_a` in `LowState` (**the Wave-4 runtime
number the plan says nobody has** — a field in a message we were already
recording); `wireless_remote[40]` in `LowState` (a time-aligned **500 Hz**
gap-free copy of the controller — free annotation track);
`utlidar/lidar_state` (settles L1-vs-L2 **electronically**, plus packet-loss
rate and firmware strings — a per-take health record); `utlidar/cloud_deskewed`;
`utlidar/robot_odom`; `uwbstate`; `fan_frequency[4]`, `temperature_ntc1/2`, and
the `q_raw`/`dq_raw`/`ddq_raw` motor triplet.

---

## The clock card needs redesign

PS-C is the card I called highest-value, and the research says its **mechanism
cannot work for the dog**. `clockmap.py:438 ClockSample` requires non-null
`device_source_ns` **and** `round_trip_ns` — but the Go2 exposes no queryable
clock and no round-trip primitive, and its highest-value channel (`lowstate`,
500 Hz IMU) carries no timestamp at all. **ClockMapV1 cannot be populated for
the dog.**

The replacement is not software. It is a **physical sync ritual**, bracketed at
session start and end, visible simultaneously in multiple sensors:

- controller button press (lands in `wireless_remote[40]` at 500 Hz *and* `wirelesscontroller`)
- 10 s still–twist–still hand-held rotation about all three axes (every IMU + both LiDARs)
- 3 sharp taps on the payload (IMU spikes)
- 5 torch flashes at uneven intervals — 1, 2, 1, 3 s — white **and** 850 nm (D455 color + IR)

Bracketing it start-and-end is the only way to get a **drift slope** and a
residual. Two published quadruped-dataset teams (CEAR, M-SEVIQ) do exactly
this. It costs ten seconds per take and is unrecoverable if skipped.

PS-C's fitting/uncertainty machinery stays valuable — it just gets fed by
ritual-derived events rather than by a protocol that does not exist.

---

## Platform risks, ranked by (probability × cost), all resolvable tonight without the dog

1. **JetPack may not be 6.2/Humble.** The plan asserts it; nobody has read
   `/etc/nv_tegra_release`. If it is 5.1.1/Foxy, the entire ROS assumption
   moves. **5 minutes to check.**
2. **RealSense on aarch64.** `pip install pyrealsense2` is a real wheel on
   Python **3.10/3.12** — but **no wheel for 3.11+**, and the wheel costs UVC
   per-frame metadata, which is exactly the `device_source` timestamp the plan
   calls non-negotiable. Worst case is a 2–3 h source build. D455-on-Orin-NX
   also has open unfixed reports of ~80% RGB drop and a dead IMU.
3. **`usbfs_memory_mb` defaults to 16 MB**, which kills dual-IR streaming; the
   fix requires editing `/boot/extlinux/extlinux.conf` and **rebooting**.
4. **DRAM-less NVMe sustained write** can fall below 100 MB/s after SLC cache
   exhaustion — right at the 720p rate. Measure with `fio` and read the **tail**
   throughput, not the peak.
5. **CycloneDDS bound to the wrong NIC** is the classic "zero topics visible"
   failure. `configs/robot.yaml:128` still carries the `enp3s0` placeholder.
6. **L2 factory IP 192.168.1.2** collides conceptually with the Go2's own
   192.168.1.7 and with the commonest home subnet. Put it on a second NIC.

---

## What I am changing

1. **New card PS-G — ingest adapters + rosbag2 primary path** (the hole). Make
   `ros2 bag record -s mcap` the recorder of record; write the sidecar adapter
   for rosbag2 MCAP; keep `parcel-capture` as attestation + clock + sidecar.
2. **PS-A matrix rewrite** against the corrections above: fix `rt/` prefixes,
   12-not-20 joints, both foot-force arrays, no BMS voltage; add the eight
   missed channels; re-mark the three service-gated rows as `VERIFY_IN_SESSION`.
3. **PS-C redesign** around bracketed physical sync events.
4. **PS-D physical-plausibility gate**: a channel is not healthy because
   messages arrive. Assert `|accel|` = 9.81 ± 1 m/s² at rest and `|gyro|` <
   0.05 rad/s per IMU — `utlidar/imu` has two independent reports of emitting
   ~1e24 m/s², which today's receipt-count probe would attest as healthy.
5. **PS-F run-sheet**: add the non-skippable 30-minute irreversible block
   (SYNC-OPEN, foot-force zero-offset takes, 15 min static, SYNC-CLOSE) plus
   the full take script, and the **verify-LiDAR-FOV-overlap-before-final-torque**
   step — no post-hoc LiDAR-to-LiDAR calibration tool can recover an extrinsic
   between two units that do not share a view.
6. **Tonight's no-dog checklist** (N0–N7) becomes a first-class artifact:
   Orin identity dump, `usbfs_memory_mb` + reboot, RealSense 10-minute
   all-stream frame count, `rs-motion`, `fio` tail throughput, rosbag2-mcap
   install + 10-minute synthetic recording through the exact command line, L2
   bench test, network pinning.

## What this assessment does not prove

Every external claim here is documentation, issue threads, or field reports —
**not our hardware**. The `rt/` prefix, the service-gating, the JPEG camera
payload, and the foot-force units are all "true of Go2 EDUs described online",
and the first 45 minutes of the session exists precisely to replace each with a
measurement from **our** unit. The in-repo defects (D-1, D-2, the ClockSample
requirement) are verified at source and are not in doubt.
