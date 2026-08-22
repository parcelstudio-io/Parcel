# Task 6 — P1-A: real eyes — a physical camera backend and the GPU detector daemon

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(Wave P1/P2 section; the P0 standing rules apply unchanged — prototype not
production, shared tree with disjoint OWNS, Edit-only on existing files,
git read-only, targeted `pytest` + `ruff` for your OWNS only).
**Roadmap:** audit §10 Phase 1, §3 "What to do" items 2 and 6.

> **CORRECTION 2026-08-22 (owner's statement):** no robot hardware is on hand — no Go2, D455, L2 or Orin. Earlier wording in this card that assumes a D455/Go2 'on the bench' inherited a false fact from scrum/20260813/task_1; the only device present is the reSpeaker XVF3800 mic array. Live rows that need a camera wait for a purchase, not a cable.

## Why
Every perception number measured in MuJoCo is structurally unable to mean what
the prototype needs (audit §1: 0/69 → 1/74 person recall in the sim vs 81–93 %
on real photos). The venue must flip to a real camera. The seam exists:
`CameraBackend.capture()` (`camera_channel/channel.py`) returns
`CaptureBuffers` (`camera_channel/backends/synthetic.py`), and the ingress
(`camera_channel/ingress.py`) → GPU OWLv2 path (P0-C: 98 ms p50) is live. What
is missing is a backend that reads pixels from hardware, and a process boundary
so the detector never shares the robot's 10 Hz loop.

**Host fact, measured 2026-08-22 01:56:** no `/dev/video*`, no RealSense on
USB, no `pyrealsense2`/OpenCV in `.parcel`. The D455 is on the bench, not
plugged in. This card therefore BUILDS and CONTRACT-TESTS the path on recorded
frames and declares the live proof **owner-gated on plugging a camera in**
(USB webcam is enough for day one; the D455 adds depth).

## Work
1. **Two backends behind the one protocol:** `camera_channel/backends/uvc.py`
   (any V4L2/UVC webcam via OpenCV, RGB only, intrinsics from a config block)
   and `camera_channel/backends/realsense.py` (D455 via `pyrealsense2` in a
   Python-3.11 sidecar process, RGB + aligned depth). Both produce
   `CaptureBuffers` with a wall-clock capture stamp and
   `EvidenceOrigin.PHYSICAL` (`evidence_origin.py`) — a desk frame must never be
   confusable with a sim frame, anywhere downstream.
2. **The detector daemon:** `perception_daemon/` — a separate process owning the
   GPU detector (OWLv2 cuda_fp16 from P0-C) and the SigLIP-2 encoders, talking
   to the runtime over an AF_UNIX socket (the pattern `parcel_robot.sim` already
   uses), with a typed request/response contract and a health probe. The
   runtime's ingress gets a `DaemonDetector` adapter behind the existing
   `Detector` protocol. Declare the dependencies (`opencv-python-headless`,
   `pyrealsense2` as an optional extra) in `pyproject.toml` — you own only the
   new extra's lines.
3. **Fixtures for CI:** a recorded-frames backend (`backends/recorded.py`) that
   replays a small committed RGB(+depth) clip; the contract tests run against
   it. Seeds RED for: origin stamp missing, capture stamp not monotonic, daemon
   unreachable must degrade to `stale` not crash the loop.
4. **Launcher:** `scripts/launch_detector_daemon.sh` and a `--camera uvc|realsense|recorded`
   switch on the prototype launcher (`scripts/launch_stack.sh`, the P0-A region
   only — re-read before editing).
5. **Pre-register** the live proof rows so they can run the moment a camera is
   plugged in: capture→publish p50 < 300 ms (TTL), 100 consecutive frames with
   `PHYSICAL` origin and zero drops, daemon restart survives without a runtime
   restart.

## Proves (live rows owner-gated on hardware)
Frames from a real camera reach the ingress inside the TTL through the daemon
on the GPU; every frame and every derived record carries `PHYSICAL`. CI proves
the contract on recorded frames today.

OWNS: `camera_channel/backends/{uvc,realsense,recorded}.py`, new
`perception_daemon/` package, `scripts/launch_detector_daemon.sh`, the
`--camera` region of `scripts/launch_stack.sh`, the new optional extra in
`pyproject.toml`, `tests/test_p1a_*.py`, `tests/data/p1a_*`, `task_6/` docs.
MUST NOT TOUCH: `ingress.py` internals beyond adding the adapter import seam
(P1-B owns ingress), `online_map/`, `perception_abstention.py`, safety core.

## Definition of done
Contract tests green on recorded frames; daemon round-trip measured; origin
stamping seeded RED; `P1A_STATUS.md` in the lightweight register with the live
rows listed as OWNER-GATED (hardware) and the exact command to run them.

## Build on P0 (binding — read the P0 status docs first)

* **Prototype-only keys go in the overlays, never in the shipped files:**
  `configs/robot.prototype.yaml` (P0-A, selected by `PARCEL_PROFILE` /
  `launch_stack.sh --prototype`), `configs/navigation/prototype.yaml` (P0-D),
  `configs/realtime.prototype.yaml.example`. The shipped `robot.yaml` stays
  byte-identical to its locked digest.
* **GPU is a given:** `.parcel` carries onnxruntime-gpu 1.29 with CUDA honoured
  (P0-C) — assume `cuda_fp16` for OWLv2 and SigLIP-2; never reintroduce a CPU
  fallback as the default.
* The `--camera` switch extends P0-A's `launch_stack.sh --prototype` and the
  single camera flag P0-A unified — do not add a fourth spelling.
