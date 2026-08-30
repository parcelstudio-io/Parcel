# Task 2 · MOUNT-GATE-1 — disarmed Go2/Orin shadow commissioning

**Date:** 2026-08-30
**Priority:** P0 before any powered autonomous motion
**Owner goal:** turn the desktop/simulator prototype into an evidence-producing,
motors-disabled installation on the exact companion-dog hardware.

## Why this is today's recommendation

Claude's local work substantially improved software safety boundaries, simulator
coverage, dynamic-person recovery, and deployment scaffolding. The independent
review still found that the repository has never ingested a synchronized physical
observation, run its service graph on the target Orin, driven the commissioned Go2
gateway, measured stop distance, or exercised an independent actuator-disable
chain. More simulator features cannot close those interface unknowns. The next
highest-information step is therefore a permanently disarmed shadow install—not
autonomous walking.

Controlling reviews:

- [`SOL_METHODICAL_ASSESSMENT.md`](../../../research/20260829/SOL_METHODICAL_ASSESSMENT.md)
- [`CLAUDE_TASK2_REVIEW.md`](../../../research/20260829/CLAUDE_TASK2_REVIEW.md)
- [`SOL_ULTRA_FINAL_AUDIT.md`](../../../research/20260829/SOL_ULTRA_FINAL_AUDIT.md)
- [`SOL_ULTRA_POSTFIX_AUDIT.md`](../../../research/20260829/SOL_ULTRA_POSTFIX_AUDIT.md)
- [`POST_ULTRA_REMEDIATION.md`](../../../research/20260829/POST_ULTRA_REMEDIATION.md)

## Deliverable

Produce a signed, reproducible commissioning bundle from the exact frozen bill of
materials: Go2 serial/firmware, AGX Orin 64 GB (or an explicitly revised compute
choice), Mid-360, depth/RGB camera, microphone array, speaker, network interfaces,
power topology, mounts, and measured transforms. Install the pinned aarch64 build
and `parcel.target`, but physically prevent actuator authority throughout this
task. Replay and simulator inputs must be visibly distinguishable from physical
sensor provenance.

## Work

1. Freeze the BOM, power/thermal budget, device identities, firmware, mount
   drawing, center-of-mass impact, cable routing, and network/DDS topology.
2. Implement the physical observation adapter and time-align LiDAR, camera/depth,
   IMU, body feedback, localization, audio, and gateway state. Record clock-domain
   mappings, measured extrinsics, sequence/loss/CRC evidence, freshness, and
   explicit missingness.
3. Build and install pinned aarch64 runtime/LIO/audio/gateway artifacts; exercise
   boot, shutdown, restart, watchdog, degraded service, full-disk, thermal, and
   network-loss behavior with motion physically disabled. Install
   `parcel.target`, the `go2_edu_plus` overlay, and their digests explicitly;
   neither is currently delivered by a target-image installer.
4. Add an independently powered, normally closed E-stop/actuator-disable path and
   retain the Unitree remote. Demonstrate stop authority under gateway hang, Orin
   crash, vendor SDK hang, shared-network loss, and shared-power loss before a
   later powered test is proposed.
5. Run synchronized shadow scenarios for stationary owner dialogue, owner
   identification, disappearing obstacles, sidewalk passers-by, a crosswalk mock,
   and a tight elevator mock. Compare physical observations and shadow commands to
   the same scenario in simulation; feed discrepancies into the governed research
   store without promoting a learned policy.

## Acceptance gates

- exact BOM and robot identity are cryptographically bound to configuration,
  calibration, installed artifacts, and service-unit digests;
- boot remains disarmed and no test process can obtain actuator authority;
- every required modality has measured clock error, age, loss, coverage, and
  calibration bounds; missing or stale inputs yield HOLD/STOP rather than motion;
- LiDAR travel-sector coverage is contiguous and qualified—not merely one
  populated angular bin—and camera/person-channel health is explicit;
- target concurrency, latency tails, memory, temperature, power, and disk behavior
  remain within declared limits during a minimum four-hour shadow soak;
- local STOP reaches the separate stop principal without cloud/model dependence;
- the independent hardware stop works under the injected single-point failures;
- logs contain no raw owner audio/images by default, are permission-restricted and
  encrypted when consented capture is enabled, and support verified deletion;
- long-lived API/device secrets use systemd credentials or equivalently narrow
  file descriptors rather than process-environment values; and
- an independent reviewer signs the evidence bundle. Any missing gate preserves
  **NO-GO** for powered autonomous movement.

## Exit and next rung

Passing this task authorizes only a separately reviewed, tethered, low-speed,
empty-area commissioning proposal. It does not authorize sidewalks, pedestrians,
crosswalks, elevators, stairs, owner following, or autonomous physical motion.
