# Unitree Go2 / AGX Orin Mount-Readiness Code Review

**Date:** 2026-08-29  
**Review type:** Read-only production-code and deployment audit

## Scope and evidence boundary

This review covers the dirty-tree production changes relevant to Unitree Go2 EDU+ / AGX Orin mount readiness in `gateway/*`, `src/parcel_robot/bridge`, `src/parcel_robot/control`, `src/parcel_robot/motion/generalized_intent.py`, `src/parcel_robot/navigation/grid_planner.py`, `src/parcel_robot/runtime.py`, the new affordance and learning-loop files, `deploy/orin/services`, and matching tests.

No hardware, live services, sockets, databases, or tests were exercised in this review. Separate targeted tests passed elsewhere in the broader work; those results were not generated or independently validated by this read-only review.

## Review

Verdict: **NO-GO for autonomous physical motion.** The defensible boundary today is desktop fake/replay evaluation plus tethered, disarmed observation commissioning. I performed read-only inspection and did not run tests or services, per the guard.

Severity-ranked findings:

1. **P0 — Commissioned motion has an arm/target race in production threading.** `RobotRuntime` starts the physical manager threaded, whose empty-target tick calls `stop()` and disarms the gateway. There is no atomic manager-owned arm-and-target operation, so an external `arm()` can be invalidated before `set_target()` succeeds. All commissioned composition tests intentionally use `threaded=False`, leaving the production path untested. See `runtime.py:1684,5129`, `control/manager.py:289-376`, and `tests/test_motion_gateway_commissioned_composition.py:290-400`.

2. **P0 — The independent safety STOP path does not exist.** The service design assigns `parcel-safety` final-envelope/STOP authority, but its executable and hardware interfaces are placeholders. Its separate UID also is not admitted to the gateway socket, and an unadmitted peer is simply disconnected rather than causing STOP. A healthy runtime could therefore keep refreshing motion during an external safety hazard. See `deploy/orin/services/README.md:24-30`, `parcel-safety.service:11-54`, `gateway/credentials.py:62-100`, and `gateway/server.py:173-198`.

3. **P0 — The commissioned state source violates the nonblocking control contract.** `latest()` performs synchronous socket I/O despite `RobotStateSource.latest()` being specified nonblocking. The manager invokes it while holding its control lock; controller updates add command and authoritative-state roundtrips, and runtime health joins may query it again. Default timeout can reach seconds, so network jitter can stall a nominal 50 Hz loop and contend with local E-stop handling. See `control/base.py:15-20`, `motion_gateway.py:638-683,930-968,1186-1234,1272-1315`, `factory.py:309-333`, `control/manager.py:289-295`, and `runtime.py:15659-15664`.

4. **P0 — A second gateway can take over the socket path.** `GatewayServerV1.open()` unconditionally unlinks an existing socket, without probing for a live listener or holding an interprocess singleton lock. The Unitree port/lease is acquired before this open, while the existing authority guard is process-local only. A duplicate process can make the original gateway unreachable and violate the sole-writer claim. See `gateway/server.py:121-145`, `gateway/seam/cli.py:736-799`, and `gateway/ports.py:511-527`.

5. **P1 — Readiness can be announced prematurely.** The notifier starts before `GatewayServer.open()`, and readiness checks only path metadata. It can accept a stale socket or race between bind, listen, and core start. The notifier also records itself ready without checking whether `sd_notify` succeeded. See `gateway/seam/cli.py:720-799`, `gateway/server.py:130-146`, and `gateway/notify.py:199-209`.

6. **P1 — The intended Orin production composition is not runnable yet.** `parcel-runtime` and several service executables are absent; no launcher injects `motion_gateway_commissioned`; LIO, sensor-clock/extrinsics, and mounted audio/AEC remain placeholders. The current web-panel live path still directly creates Unitree and Livox handles, contradicting the split-process design. The referenced `parcel.target` is absent. See `parcel-runtime.service:6-43`, `control/factory.py:238-248`, `deploy/orin/services/README.md:9-20,124-143`, `web_panel.py:971-1014`, and `backends/go2.py:457-585`.

7. **P1 — Gateway crash-loop protection is ineffective.** `StartLimitIntervalSec` and `StartLimitBurst` are under `[Service]`; systemd expects them under `[Unit]`. The existing tests only search text and would not catch the invalid placement. See `parcel-gateway.service:100-101` and `tests/test_gateway_socket_credentials.py:223-243`.

8. **P1 — “Physical” evidence is locally asserted, not robot-authenticated.** Hashes validate launch compatibility, but do not bind evidence to a robot serial, firmware, or authenticated DDS peer. The direct legacy Unitree builder also remains registered and can bypass the gateway’s LowState/SOC/timestamp fences when explicitly injected. See `deploy/orin/services/README.md:99-128` and `control/factory.py:89-175`.

9. **P2 — LowState-only health changes can remain hidden.** The commissioned source returns its prior object whenever the Sport sequence is unchanged, even if battery, thermal, or LowState sequence advanced. Gateway enforcement remains fail-closed, but runtime telemetry can lag until another Sport sample. See `motion_gateway.py:930-968,1340-1363`.

10. **P2 — Strict sample validation is weakened by pre-validation coercion.** `read_sport_sample()` converts values with `float()`, allowing booleans or numeric strings that the strict dataclass validator is meant to reject. See `gateway/ports.py:276-317`.

11. **P2 — New learning/generalization code is safe scaffolding, not an integrated capability.** Generalized intent, affordance planning, and skill outcomes are proposal-only and appropriately deny motion authority, but are not connected to the runtime, executive, simulator loop, or authenticated outcome ingestion. They currently support offline experiments only. See `motion/generalized_intent.py:1-18,257-706`, `affordance_planner.py:1-14,457-723`, and `skill_outcomes.py:1-15,237-555`.

12. **P2 — Grid planning still has a possible false-arrival edge case.** A one-cell path may return `at_goal` based on discretized goal-cell membership even after the exact metric tolerance check failed. This is pre-existing rather than a dirty-tree regression; the current refactor adds no pedestrian prediction, semantic crosswalk/elevator reasoning, or targeted regression test. See `navigation/grid_planner.py:864-917`.

Concrete strengths worth preserving:

- Boot-disarmed, stop-first gateway behavior with TTL, sequence/hash/UID checks, exact-zero advancing witnesses, bounded SDK cleanup, LowState/SOC gating, and explicit admission-vs-motion-proof semantics.
- Kernel credential enforcement and separate socket principals.
- Additive protocol V2 with V1 compatibility and conservative unknown handling.
- Commissioned adapter checks for boot epoch, writer ownership, freshness, source integrity, and physical evidence.
- Runtime backend lifecycle ordering and rollback are materially improved.
- Generalized intent and learning modules remain categorical, proposal-only, and structurally unable to emit velocities, joints, torques, or dispatch commands.

Promotion boundary:

1. Add manager-owned atomic arm-plus-target handling and threaded race tests.
2. Replace socket-backed `latest()` with a bounded background poller/cache; prove 50 Hz p99 latency, TTL continuity, and stop bounds under delayed/dropped IPC.
3. Implement an independent stop-only safety principal and executable with physical E-stop/remote-stop tests.
4. Add an interprocess gateway lock, live-socket probing, and readiness emitted only after listen plus core start.
5. Build the actual Orin launcher/service composition and validate units with `systemd-analyze verify`.
6. Bind commissioning evidence to observed robot/firmware identity.
7. Qualify progressively: disarmed telemetry, jack-stand motion, then fenced low-speed walking with runtime crash, gateway crash, link loss, stale feedback, low SOC, obstacle, and E-stop cases.

Until those are complete, do not grant autonomous body-motion authority on the physical Go2.
