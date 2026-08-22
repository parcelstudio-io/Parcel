# P1-A — pre-registered acceptance rows

**Written BEFORE any measurement.** Card: `README.md` · Board: `../TASK_BOARD.md`
**Date/time:** 2026-08-22, before the first backend or daemon line was written.

Host facts confirmed at pre-registration time (`ls /dev/video*` → none,
`rs.context().query_devices()` → 0 devices): **no camera is attached.** Rows
marked LIVE are therefore OWNER-GATED and are expected to be recorded as
NOT RUN, not as passes.

## CI rows — measurable today on recorded frames

| # | Row | Bound (pre-registered) |
|---|---|---|
| C1 | Recorded clip replays end-to-end | N frames replayed, **0 drops**, every envelope passes `CameraChannel.validate_envelope` |
| C2 | Replay provenance | **100 %** of replayed frames carry `EvidenceOrigin.REPLAY` — never `PHYSICAL`, never `UNKNOWN` |
| C3 | Physical provenance | `UvcCameraBackend` and `RealSenseCameraBackend` stamp `EvidenceOrigin.PHYSICAL` on **100 %** of frames captured from an injected device double |
| C4 | Capture stamps monotonic | `capture_monotonic_ns` **strictly increasing** across ≥ 100 consecutive captures on all three backends; a non-monotonic stamp is a refusal, not a warning |
| C5 | Daemon round-trip overhead | AF_UNIX request→response overhead for a 640×480×3 uint8 frame with a stub detector: **p50 ≤ 15 ms, p95 ≤ 40 ms** (100 samples) |
| C6 | Daemon unreachable degrades | `DaemonDetector.detect` with no daemon returns `[]`, sets `stale`, **raises nothing**, and `CameraIngress.poll_once` completes |
| C7 | Daemon restart survives | daemon stopped and restarted on the same socket; the SAME `DaemonDetector` instance answers again with **0 client restarts** |
| C8 | Gates | targeted `pytest` green on `tests/test_p1a_*.py`; `ruff check` clean on OWNS |

## Seeded-RED guards (each seeded, watched fail, restored byte-identically)

| # | Guard | What the seed removes |
|---|---|---|
| R1 | origin stamp missing | backend stops declaring `EvidenceOrigin` → the origin test must fail |
| R2 | capture stamp not monotonic | the monotonic check is removed → the stamp test must fail |
| R3 | daemon unreachable must degrade, not crash | the connect-failure handler re-raises → the degrade test must fail |

## LIVE rows — OWNER-GATED on plugging a camera in (expected NOT RUN)

| # | Row | Bound (pre-registered) |
|---|---|---|
| L1 | capture→publish p50 | **< 300 ms** (`DEFAULT_DETECTION_TTL_NS`) over 100 frames through the daemon on the GPU |
| L2 | 100 consecutive PHYSICAL frames | **100/100** frames `EvidenceOrigin.PHYSICAL`, **0 drops** |
| L3 | daemon restart, live | daemon restarted mid-stream; the capture loop continues with **no restart** of the consuming process |

The exact commands for L1–L3 are recorded in `P1A_STATUS.md`.
