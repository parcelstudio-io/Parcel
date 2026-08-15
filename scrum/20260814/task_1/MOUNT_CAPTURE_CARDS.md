# MR cards — mount readiness and stationary capture

These cards are the critical path to physically mounting the sensing rig. They
do not create a physical locomotion path.

## MR-A — complete the recording contract

- **Owner:** Sol
- **Priority:** P0
- **Hardware required:** no

**Starting evidence:** `scripts/parcel_capture/rosbag2.py` records six D455
image/IMU topics but no camera calibration or TF topics; the 20260813 audit did
not test this requirement because it was absent from that board.

### Work

1. Freeze a capture truth table for:

   - D455 color/depth/IR image topics;
   - the profile-matching `CameraInfo` topic for each active optical stream;
   - `/tf` and `/tf_static`, or a machine-readable static-transform snapshot
     when no publisher exists;
   - built-in and add-on LiDAR `PointCloud2` fields, especially timestamp or
     per-point offset fields;
   - IMU frames and source-clock domains;
   - selected D455 width, height, rate, format, distortion and calibration
     digest.

   Model calibration/transform evidence as a separate support-artifact/topic
   class rather than pretending it is one of the 28 payload channels. Preserve
   the original channel budget and make the dependency explicit.

2. Extend the rosbag2 plan without hard-coding documentation-derived names as
   truth. The run-time preflight must reconcile planned topics with
   `ros2 topic list -t` and refuse a required missing/mismatched topic.
3. Bind calibration and transform artifacts into the sidecar by digest. A bag
   cannot be `GO-RECORD` when its active image profile lacks matching
   intrinsics or its sensor transforms are absent/ambiguous.
4. Wire the sync-event fit into the sidecar rather than merely proving
   `sidecar_sync_block()` in isolation.
5. Correct the remaining `VENDOR_VIDEO` dependency declaration: the RTP H.264
   path needs a media stack, not Unitree motion SDK authority.
6. Create a **superseding, run-specific Stage-0 command addendum** under this
   task. It must provide named rows for:

   - T7 RealSense driver launch;
   - T8 add-on L2 driver launch;
   - T9 Unitree ROS overlay/DDS environment;
   - T10 actual `ros2 bag record -s mcap` command and storage config.

   It must also carry the calibration/TF/sync stop gates. Do not edit the
   historical 20260813 templates in place.
7. Generate or validate the run-specific take/disk ledger from
   `budget.py::render_document()` data. The old take script's 84.60 MiB/s,
   297.4 GiB/hour and fallback-profile figures are superseded; no operator
   should recalculate them by hand.
8. Render every run-specific recorder command from
   `Rosbag2Plan(distro=<observed>)` only after `--verify-help` accepts the
   installed recorder's help. Do not copy the historical
   `--disable-keyboard-controls` or assume `--custom-data` exists on Humble.
   Unsupported optional metadata uses the documented `TAKE.txt` fallback.
9. Keep three different facts distinct in the sidecar and run sheet:

   - factory camera intrinsics/distortion;
   - calibrated or validated sensor-to-sensor/base transforms;
   - tape-measured mount geometry with stated uncertainty.

   A tape measurement can seed calibration or diagnose a gross error. It is not
   calibrated TF.

### Required tests

- Every active image stream has a profile-compatible `CameraInfo` or the plan
  refuses.
- A seeded width/height/distortion/calibration mismatch refuses finalization.
- Missing, disconnected, cyclic or ambiguous required TF refuses
  `GO-RECORD`.
- A transient-local `/tf_static` publisher that emitted before recording is
  recovered through the planned snapshot/QoS path or finalization refuses; a
  topic name with zero captured transforms is not evidence.
- A changed transform or calibration byte changes the bound digest.
- A sync fit is present and digest-bound when the run claims recoverable
  cross-device time; absent fit produces an explicit non-certifiable result.
- The planned topic/type set round-trips through rosbag2 sidecar verification.
- Humble command generation remains valid; no motion/publisher token enters
  the capture trees.
- A seeded oracle field cannot cross into the physical sensor artifact.
- The committed/run-specific disk table is generated from the current budget
  model; restoring any stale 84.60 MiB/s-era value reddens a test.
- Every operator recorder argv equals the distro-aware generator output; an
  injected unsupported flag or a help-file mismatch refuses before recording.

### Exit

- Focused tests and Ruff green.
- Full commit gate green.
- `MR_A_STATUS.md` records changed files, commands/results, seeded failures,
  and `does_not_prove`.

### Does not prove

It does not prove any documented ROS topic exists on the actual Orin, that the
factory D455 calibration is accurate after mounting, or that the measured
extrinsics are accurate. MR-B and MR-C replace those assumptions with evidence.

## MR-B — no-dog Orin rehearsal

- **Owner:** Operator, assisted by Sol
- **Priority:** P0
- **Depends on:** MR-A

**Hardware required:** Orin, D455 and add-on L2; Go2 is not needed for the first
half and must not be commandable.

### Preconditions

- Back up the only Orin before a persistent change.
- Record JetPack, Ubuntu, ROS, Python, package and kernel identity.
- Record the target disk/device and free capacity.
- Resolve whether package installation is permitted on this non-sacrificial
  dock. If not, stop and record the missing deployment environment.

### Work, cheapest disconfirmation first

1. Verify package candidates and the real Humble `ros2 bag record --help`.
2. Verify the MCAP storage plugin opens both selected profiles.
3. Bring up D455 directly over USB 3 without a hub; discover actual topic
   names, types, QoS, rates, timestamps and `CameraInfo`.
4. Bring up L2 on its dedicated interface; discover cloud/IMU fields, rates,
   frames and QoS.
5. Build/inspect Unitree message interfaces without issuing or importing a
   motion client. Record offered QoS for every later robot topic.
6. Measure sustained write on the actual destination long enough to expose
   cache exhaustion, then record the real driver topics for at least 60 s.
7. Run the full-rate synthetic rehearsal with drop, stale clock, process kill
   and disk-pressure cases.
8. Freeze the D455 profile that passes the measured USB and recorder limits.

### Evidence bundle

Create `evidence/<run_id>/` under this task or an external immutable store and
record paths/digests here. It contains:

- environment inventory and package versions;
- `ros2 topic list -t` and `ros2 topic info -v` outputs;
- driver launch arguments and logs;
- disk and rosbag throughput results;
- generated storage config and actual recorder help;
- D455/L2 serials and firmware;
- rehearsal bag, sidecar, clock/sync result and verification report;
- a non-empty `does_not_prove`.

Large bags do not enter Git; only manifests, hashes and small reports do.

### Stop conditions

- Any required stream delivers under 90% or has implausible measurements.
- Required `CameraInfo` or transform evidence is absent or mismatched.
- Offered/requested QoS is incompatible.
- Sustained throughput is below the required rate plus declared reserve.
- Recorder flags/config do not match the installed Humble version.
- The only available route would require installing a motion-capable SDK into
  `.parcel`.

### Exit

`MR_B_STATUS.md` says exactly one of `PASS`, `DEGRADED` or `NOT RUN`, with the
measured reason. Only `PASS` admits MR-C recording.

## MR-C — next-session stationary physical Stage 0

- **Owner:** Operator
- **Safety observer:** a second named human whose only job is stop authority
- **Priority:** P0 when hardware/staff are present
- **Depends on:** MR-A and MR-B green

**Today:** planning/preparation only. Do not execute this card on 2026-08-14
after the engineering and no-dog rehearsal day.

### Authorized envelope

- Dog off for mounting, geometry measurement and photographs.
- Dog powered but seated for topic discovery and stationary capture.
- No stand, gait, walking, autonomous motion, stairs, ramps, owner following or
  voice-driven locomotion. A separately authorized later session may use the
  existing vendor-handheld stand/sit gate; this card does not.

### Order

1. Copy the blank 20260813 session templates into a run-specific evidence
   directory; never fill the historical template in place.
2. Name operator, safety observer, devices, serials, firmware and run ID.
3. Mount while powered off; measure all sensor offsets/orientations from a
   reproducible `base_link` datum; photograph before final torque.
4. Verify payload mass/COM, pull security, cable strain relief, pinch sweep,
   thermal path and sensor self-occlusion.
5. Verify independent stop availability and the seated, stationary safety
   envelope without commanding a stand or gait.
6. Run preflight/attestation. Firmware below the pin is a hard stop.
7. Start clock/sync evidence and the raw recorder before the first valuable
   take.
8. Capture the non-skippable synchronization, force-zero, static and closing
   synchronization takes, plus profile-matched calibration data.
9. Finalize and verify MCAP, sidecar, attestation, clock/sync and
   calibration/transform digests.
10. Offload and verify a second copy before loosening any bolt; repeat mount
    geometry measurements at teardown.

### Exit artifacts

- signed run sheet and safety brief;
- mount geometry and photographs;
- physical MCAP and verified sidecar;
- hardware attestation;
- clock/sync report;
- calibration/transform bundle;
- manifest containing Git SHA, configs, driver/firmware versions and every
  digest;
- explicit `does_not_prove`.

If any entry gate fails, take `DEGRADE-MMP`: mount, measure, photograph, record
nothing. That is an acceptable close and must not be relabelled a failed
recording.

### Scheduling gate

Schedule MR-C as a separate session with rested participants, a named operator
and safety observer, the frozen MR-B environment/profile, and enough time to
verify/offload the dataset before teardown. A late-day green rehearsal is not
permission to begin MR-C immediately.
