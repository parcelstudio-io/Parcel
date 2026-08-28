# Unitree Go2 EDU+ mount-readiness decision

Date: 2026-08-26 (America/New_York)
Target: Unitree Go2 EDU+, AGX Orin 64 GB, camera, Mid-series LiDAR,
microphone/speaker, and custom Starlink modem
Physical hardware used in this review: none

## Executive decision

The prototype is **not ready for motion-enabled mounting**. It is reasonable
to continue desktop development and to prepare a tightly controlled stationary
Stage-0 data-capture mount, but that rung has not been executed and does not
authorize stand, translation, Follow, search, greeting, stairs, or autonomous
navigation.

| rung | present decision | promotion evidence still missing |
|---|---|---|
| Motion seam + disarmed product composition | Accepted at desktop/fake-Sport tier only | native SDK2/DDS and motion-enabled vendor/physical path; close known model/nav failures |
| Stationary zero-motion mount | Conditional | signed runbook, secure mount, independent remote stop, power/thermal/clock/calibration capture |
| Tethered stand/pulse | NO-GO | gateway-compatible real `SportPort`, sole writer, axis/unit/rate checks, measured HOLD/STOP envelope |
| Supervised point navigation | NO-GO | real LIO, independent arrival evidence, zero false arrivals/contacts, typed blocker terminals |
| Follow/search/greet | NO-GO | verified owner identity posterior, crossing/occlusion/reacquisition, social clearance, consent |
| Stairs/rough terrain | NO-GO | elevation/terrain contract, articulated sim transfer, instrumented physical curriculum |
| Unattended autonomy | Out of scope | substantially broader safety case and ODD |

## Claude review

The committed `DEPLOYABLE-MOTION-SEAM` at `2ce919a` is accepted as strong
desktop/bench work. It provides an installable CPython 3.10 gateway, a bounded
typed `MotionGatewayClientV1`, restart/reconnect-disarmed semantics, service/CLI
parity, and containment for hung vendor-state and stop calls.

Its accepted evidence ceiling remains binding. The subsequent P0 tranche closes
one narrow desktop gap but does not raise the physical tier:

- the normal product runtime can now reach `MotionGatewayClientV1` only through
  a permanently disarmed adapter. Desktop tests reach the real Unix gateway
  and fake Sport without `acquire` or `command`; this is not a vendor or robot
  motion path;
- a legacy `UnitreeSportController`/`SportClient` transport exists, but no
  gateway-compatible `UnitreeSportPort` or normal-runtime composition reaches
  it, and gateway `--sport vendor` intentionally refuses;
- a selectable observation-only Go2 backend exists, but it is uncommissioned
  and untested: NIC/extrinsics are unmeasured, pose is odometry rather than
  commissioned MAP/LIO, owner perception is absent, every motion-producing
  method refuses, and stop/emergency-stop are safe no-ops because this backend
  never commands the body;
- Orin service behavior has not run on target; and
- no physical stop, stopping distance, payload/mount, thermal, power, clock,
  extrinsics, LIO, owner identity, or mounted-acoustic evidence exists.

The shared Claude artifact URL returned a Claude `Page not found` page on
2026-08-26. It therefore supplied no reviewable content, and this report makes
no claim about an unseen artifact. An exported artifact can be reviewed later
without changing the present code-path result.

## P0 implementation update

The desktop runtime composition now has an explicit non-motion mode named
`motion_gateway_disarmed`. Its controller declares no body-velocity support,
has no acquire/command call site, rejects direct updates, reconnects disarmed,
and sends emergency stop across the Unix boundary. An ordinary stop may be
elided only with fresh disarmed/stationary evidence; stale stationary feedback
forces a stop request. The integration fixture uses the existing fake Sport
service, while gateway vendor mode still refuses before constructing a backend.

Capability, embodiment, authenticated-receipt, and H2b contracts were also
added, but they do not compose an authorized physical mission. H2b failed its
frozen alias-recovery gate (113/120 versus 114/120), is default-disabled, and
remains outside the navigation pipeline. No physical commissioning record,
Go2/Orin run, native Unitree MuJoCo SDK2/DDS bridge, or measured stop evidence
was produced. The motion-enabled decision therefore remains **NO-GO**.

## What “robot-ready validation” means

Robot-ready means the exact production path, at the real process and hardware
boundaries, passes positive missions and adversarial refuters:

```text
owner speech / mission
        |
typed intent + consent + capability manifest
        |
companion executive ---- action receipts ---- dialogue state
        |
metric/relative goal + independent completion authority
        |
local planner + reactive safety + E-stop latch
        |
runtime -> Unix gateway -> sole Unitree SDK2/DDS writer
        |
real Go2 + real sensors + measured physical STOP
```

A valid JSON response, a passing unit test, a high simulator score, or an
installable gateway is useful but insufficient. Every arrow above needs a
positive witness; every bypass, stale-evidence, restart, localization jump,
owner-identity ambiguity, and network loss needs a fail-closed refuter.

## Required promotion sequence

1. **Product-path closure, disarmed (desktop slice implemented):** the normal
   runtime now composes through `MotionGatewayClientV1` → gateway → fake Sport
   without an acquire/command surface. The new slice covers startup,
   reconnect, fresh/stale stationary stop handling, emergency latch, explicit
   disarmed configuration, and backend-bypass refusal. Retain the broader
   gateway death/restart/lease/TTL/clock fault campaigns as release evidence;
   none of this authorizes motion.
2. **Go2 simulator contract:** retain fake Sport as the separate
   gateway-lifecycle tier and retain the already integrated official Go2 MJCF
   assets. Integrate the native `unitree_mujoco` low-level SDK2/DDS simulator
   boundary through a simulated `SportPort` or explicit high-level-to-low-level
   controller bridge, with the gateway still the sole writer. Verify units,
   axes, signs, command age/rate, clamp, HOLD, stop, restart, and state loss.
   Simulator stop distance is not a physical claim.
3. **Real stationary Stage 0:** mechanically secure the robot, disable Sport,
   keep an independent remote stop, and record identity, firmware, clocks,
   calibration/extrinsics, LiDAR/camera/body/audio, dropouts, storage, power,
   thermals, and teardown in MCAP + sidecar.
4. **Replay stationary evidence:** run Stage-0 bags through the exact product
   assembler to validate clocks, freshness/dropout, calibration plumbing, and
   stationary pose stability. Fault-mutated replay exercises software failure
   handling only. Genuine LIO, moved-obstacle R3, kidnapped-pose R4b, and
   arrival evidence require later controlled-motion or dynamic recordings.
5. **Tethered single-axis commissioning:** measure command signs/units/rates,
   clamp, lease loss, HOLD, independent STOP, and stopping envelope on a stand
   or tether. Any unexplained movement ends the rung.
6. **Supervised known points:** low-speed, flat, controlled ODD; zero contacts
   and false arrivals; every non-arrival typed within its budget.
7. **Owner-relative skills:** enroll and evaluate identity, distractors,
   crossing, occlusion, loss, search bounds, and reacquisition before Follow,
   approach, greeting, or owner search can move.
8. **Terrain curriculum:** flat → slope → single step → controlled stair
   fixture. Measure abort/fall/slip/clearance/attitude/stopping/retreat at each
   rung. Ordinary stairs remain disabled until commissioned.

## Hard stop conditions

Physical promotion stops if any of the following is true:

- a localization discontinuity can retain translation/completion authority;
- any frozen safety holdout has a false arrival or human contact;
- an active skill can wait indefinitely without typed progress/terminal state;
- boot, restart, reconnect, or network recovery can re-arm motion;
- any runtime path bypasses the sole gateway/vendor writer;
- owner identity is ambiguous or stale during owner-relative motion;
- independent physical STOP or a measured stopping envelope is missing;
- mounted audio cannot reject self-TTS and recognize STOP under noise; or
- simulator truth, unknown calibration, or unknown clock provenance reaches a
  physical decision.
