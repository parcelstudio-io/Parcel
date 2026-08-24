# EMBODIMENT-KERNEL — VERDICT · 2026-08-24

## Verdict: PARTIALLY CONFIRMED

Parcel has the nucleus of a portable actuation boundary, but not yet a
portable robot stack. K1, K2 and K5 pass; the observation and deployment
refuters K3, K4 and K6 fail exactly where expected.

Keep these seams:

- `GatewayCommandV1` epoch/TTL/state/stop semantics;
- `RobotStateSource`, `TimedVelocitySetpoint` and controller capabilities;
- `BodyIntentV1` plus monotonic capability degradation;
- `PoseProvider` and the output half of `LocalizationUpdate`;
- provider protocols and the durable conversation/memory stores.

Before Follow or physical navigation, introduce two independent body-neutral
boundaries:

1. a sole-writer `MotionGatewayClient` backed by a Unitree Sport driver now
   and a custom whole-body-controller driver later; and
2. an immutable, stamped `NavigationSnapshotV2` assembled from synchronized
   localization, geometry, tracks, owner belief, controller feedback and
   input-health evidence.

High-level navigation, conversation, memory and initiative must import
neither Unitree nor simulator types. Vendor DDS/SDK and credentials belong in
the gateway process. Physical startup must reject truth-pose fallback.

The current implementation sequence should be reordered: observation spine,
gateway client/driver, deployable services, local STOP and real localization
must precede Follow composition. A future custom quadruped should require a
new driver, capability manifest and calibration—not edits to the companion
executive or navigation policies.

The in-progress gateway also needs an adversarial refuter before it can be a
safety boundary: a hung vendor `stop_move()` or `state()` call must not block
the watchdog or prevent an independent stop path.

**Independent Fable cross-review: pending.** Until then this is a Codex
research verdict with reproducible local artifacts, not a Fable finding.
