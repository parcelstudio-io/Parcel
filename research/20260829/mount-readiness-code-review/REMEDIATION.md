# Mount-readiness review remediation ledger

**Date:** 2026-08-29  
**Applies to:** the twelve findings in [`REVIEW.md`](REVIEW.md)  
**Current physical-motion verdict:** **NO-GO**

The original review is preserved as the point-in-time independent finding
record. This ledger distinguishes source-level remediation from physical proof;
closing a desktop code defect does not qualify a Go2, Orin, payload, sensor, or
stop distance.

| Original finding | Current disposition | Evidence ceiling / remaining work |
|---|---|---|
| P0 arm/target race | **Source-level fixed** | `ControlManager.arm_with_target()` makes arm plus first target one manager-owned transaction; threaded/fake regression exists. Still unrun on SDK2/Orin/Go2. |
| P0 independent safety STOP absent | **Software seam fixed; physical gate open** | A distinct-UID `parcel-safety` process has only observe and unconditional latched-STOP operations; the gateway refuses that UID lease/command authority. Desktop fake-gateway fault/lifecycle evidence passes. GPIO/serial/robot-remote input, target execution, shared-power/gateway-failure coverage, and a physically independent E-stop remain absent. |
| P0 blocking commissioned state | **Source-level fixed** | Commissioned state is maintained by a bounded background cache instead of doing normal socket round trips inside `latest()`. Target 50 Hz p99, scheduler, TTL, and fault evidence remain unmeasured. |
| P0 duplicate gateway socket takeover | **Source-level fixed** | The gateway now holds a listener singleton lock and refuses a live existing listener instead of unconditionally unlinking it. Target process/boot fault campaign remains open. |
| P1 premature readiness | **Source-level fixed** | Readiness is emitted only after the server/core path is live and notifier outcome is checked. No systemd-on-Orin evidence exists. |
| P1 Orin composition not runnable | **Open** | Gateway and safety entry points exist; runtime, LIO, audio, synchronized physical observation, mounted AEC, and the final target launcher/image are still absent. |
| P1 ineffective start limiting | **Fixed in unit source** | `StartLimitIntervalSec` and `StartLimitBurst` now live under `[Unit]`; target `systemd-analyze verify` and reboot campaign remain open. |
| P1 locally asserted physical identity / legacy writer | **Partly fixed** | Direct in-process Unitree runtime construction is hard-retired and commissioning shares the fixed device lock. Launch hashes still do not authenticate the observed robot or DDS peer. |
| P2 hidden LowState-only change | **Source-level fixed** | The commissioned background cache tracks authoritative state changes without waiting for a Sport-state change. Physical LowState semantics/rates remain uncommissioned. |
| P2 coercive vendor validation | **Fixed** | Vendor sample parsing now preserves strict input types rather than accepting booleans/numeric strings via pre-validation coercion. |
| P2 learning/generalization is scaffolding | **Correct and still open** | Learned policy, affordance, and skill-outcome components remain proposal-only/offline. This is the intended safety boundary until blind-family evidence earns a shadow deployment. |
| P2 discretized grid false arrival | **Fixed in deterministic planner** | A one-cell path no longer overrides the exact metric arrival check. The broader navigation benchmark still has false-arrival failures and remains far below promotion readiness. |

The stop-only software principal was independently exercised in SOS-1.
Subsequent concurrent maintenance exposed and preserved a real
READY-before-signal-handler race plus verifier/oracle defects. After repair,
two parallel and two sequential current-source runs each refused 256 stop-UID
lease attempts and 256 positive commands, admitted 256 runtime lease/refresh
operations, and confirmed 256 safety latches with lease invalidation, exact
zero, and the fake stationary witness. The strengthened verifier and tamper
checks pass. See
[`../stop-only-safety-1/MAINTENANCE_RESULTS.md`](../stop-only-safety-1/MAINTENANCE_RESULTS.md)
and
[`../stop-only-safety-1/MAINTENANCE_VERDICT.md`](../stop-only-safety-1/MAINTENANCE_VERDICT.md).

These remediations narrow software risk but do not change the deployment rung.
The permissible next step remains checklist-reviewed observe-only or
motors-disabled HIL. Motion requires the actual target composition, observed
robot identity, synchronized camera/LiDAR/localization/audio, independent
physical stop, payload/power/thermal evidence, and stationary then tethered
stop/braking qualification.
