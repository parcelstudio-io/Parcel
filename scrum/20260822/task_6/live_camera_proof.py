#!/usr/bin/env python
"""P1-A live proof — run this the moment a camera is plugged in.

Rows L1-L3 were PRE-REGISTERED in ``PREREGISTRATION.md`` before anything was
built, and were NOT RUN because this host has no camera (measured 2026-08-22:
no ``/dev/video*``, ``rs.context().query_devices()`` → 0 devices).

    # 1. start the detector daemon (own socket, warm models)
    scripts/launch_detector_daemon.sh --background --preload \
        --socket /run/user/$(id -u)/parcel_perception.sock

    # 2. run the three rows against the attached camera
    .parcel/bin/python scrum/20260822/task_6/live_camera_proof.py \
        --camera uvc --frames 100 \
        --socket /run/user/$(id -u)/parcel_perception.sock

    # 3. stop it
    scripts/launch_detector_daemon.sh --stop \
        --socket /run/user/$(id -u)/parcel_perception.sock

Use ``--camera realsense`` for the D455 (adds aligned depth, so L1 also
localizes). ``--record CLIP.npz`` writes the frames out as a replayable clip so
the CI fixture can be replaced by real pixels.

The rows, verbatim from the pre-registration:

  L1  capture→publish p50 < 300 ms (DEFAULT_DETECTION_TTL_NS) over 100 frames
      through the daemon on the GPU
  L2  100/100 consecutive frames carry EvidenceOrigin.PHYSICAL, 0 drops
  L3  the daemon is restarted mid-stream and the capture loop continues with
      NO restart of this process

Every number is printed with the host load beside it: Fable's wave row C-1
measured the detector bound as load-conditional (98 ms p50 idle vs 132-139 ms
under concurrent load), so a latency figure without a load figure is not a
result.
"""

from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "src"))

from parcel_robot.camera_channel.ingress import DEFAULT_DETECTION_TTL_NS
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.perception_daemon import DaemonDetector


def gpu_state() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return out.stdout.strip().replace("\n", " | ")
    except Exception as exc:  # noqa: BLE001
        return f"unavailable ({exc})"


def build_backend(kind: str, device: str, width: int, height: int):
    if kind == "uvc":
        from parcel_robot.camera_channel.backends.uvc import UvcCameraBackend

        dev: int | str = int(device) if device.isdigit() else device
        return UvcCameraBackend(dev, width_px=width, height_px=height)
    if kind == "realsense":
        from parcel_robot.camera_channel.backends.realsense import (
            RealSenseCameraBackend,
            connected_devices,
        )

        serials = connected_devices()
        print(f"RealSense devices on the bus: {serials or 'NONE'}")
        return RealSenseCameraBackend(width_px=width, height_px=height)
    raise SystemExit(f"live proof needs a physical venue, not {kind!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P1-A owner-gated live camera proof")
    parser.add_argument("--camera", choices=["uvc", "realsense"], default="uvc")
    parser.add_argument("--device", default="0", help="V4L2 index or /dev/videoN (uvc only)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--socket", default=None, help="detector daemon socket")
    parser.add_argument(
        "--query",
        default="person,chair,laptop",
        help="comma-separated open-vocab batch (<= 16 phrases)",
    )
    parser.add_argument("--record", default=None, help="also write the frames to a clip")
    parser.add_argument(
        "--restart-at",
        type=int,
        default=None,
        help="row L3: stop the daemon at this frame index and restart it "
        "(needs scripts/launch_detector_daemon.sh on PATH semantics)",
    )
    args = parser.parse_args(argv)

    queries = [q.strip() for q in args.query.split(",") if q.strip()]
    print(f"host load: {os.getloadavg()} | gpu: {gpu_state()}")

    backend = build_backend(args.camera, args.device, args.width, args.height)
    detector = DaemonDetector(args.socket, request_timeout_s=120.0)
    health = detector.health()
    if health is None:
        raise SystemExit(
            "the perception daemon is not reachable; start it first:\n"
            "  scripts/launch_detector_daemon.sh --background --preload"
        )
    print(f"daemon: provider={health['provider_profile']} eps={health['execution_providers']}")

    backend.open()
    print(f"camera: {backend.origin_label} spec={backend.spec.intrinsics.as_dict()}")

    latencies: list[float] = []
    origins: list[EvidenceOrigin] = []
    drops = 0
    detections = 0
    stale_frames = 0
    frames: list = []

    for index in range(args.frames):
        if args.restart_at is not None and index == args.restart_at:
            print(f"--- row L3: restarting the daemon at frame {index} ---")
            subprocess.run(
                [os.path.join(REPO, "scripts", "launch_detector_daemon.sh"), "--stop"]
                + (["--socket", args.socket] if args.socket else []),
                check=False,
            )
            time.sleep(1.0)
            subprocess.run(
                [
                    os.path.join(REPO, "scripts", "launch_detector_daemon.sh"),
                    "--background",
                    "--preload",
                ]
                + (["--socket", args.socket] if args.socket else []),
                check=False,
            )

        started = time.monotonic_ns()
        try:
            backend.capture()
        except Exception as exc:  # noqa: BLE001
            drops += 1
            print(f"frame {index}: capture failed ({type(exc).__name__}: {exc})")
            continue
        buffers = backend.last_buffers
        origins.append(buffers.origin)
        rows = detector.detect(
            rgb=buffers.color_rgb8, depth=buffers.depth_m_f32, seg=None, query=queries
        )
        detections += len(rows)
        if detector.stale:
            stale_frames += 1
        latencies.append((time.monotonic_ns() - started) / 1e6)
        if args.record is not None:
            frames.append(buffers)

    backend.close()
    detector.close()

    ordered = sorted(latencies)
    p50 = statistics.median(latencies) if latencies else float("nan")
    p95 = ordered[int(0.95 * (len(ordered) - 1))] if ordered else float("nan")
    ttl_ms = DEFAULT_DETECTION_TTL_NS / 1e6
    physical = sum(1 for o in origins if o is EvidenceOrigin.PHYSICAL)

    print()
    print(f"host load: {os.getloadavg()} | gpu: {gpu_state()}")
    print(f"L1 capture→publish  p50={p50:.1f} ms  p95={p95:.1f} ms   "
          f"bound < {ttl_ms:.0f} ms  -> {'MET' if p50 < ttl_ms else 'MISS'}")
    print(f"L2 PHYSICAL origin  {physical}/{args.frames}  drops={drops}   "
          f"bound 100/100 and 0 drops  -> "
          f"{'MET' if physical == args.frames and drops == 0 else 'MISS'}")
    if args.restart_at is not None:
        print(f"L3 daemon restart   stale frames={stale_frames}, process restarts=0  -> "
              f"{'MET' if physical == args.frames else 'MISS'} "
              "(the loop kept running through the restart)")
    print(f"detections returned: {detections}")

    if args.record is not None and frames:
        import numpy as np

        from parcel_robot.camera_channel.backends.recorded import write_clip

        colors = [np.asarray(f.color_rgb8) for f in frames]
        depths = [np.asarray(f.depth_m_f32) for f in frames if f.depth_m_f32 is not None]
        manifest = write_clip(
            args.record,
            colors,
            clip_id=f"p1a-desk-{args.camera}",
            captured_origin=backend.origin,
            captured_label=backend.origin_label,
            depths=depths or None,
            fps=backend.spec.rgb_fps,
            notes="Real desk pixels, recorded by scrum/20260822/task_6/live_camera_proof.py.",
            intrinsics={
                "fx": backend.spec.intrinsics.fx,
                "fy": backend.spec.intrinsics.fy,
                "cx": backend.spec.intrinsics.cx,
                "cy": backend.spec.intrinsics.cy,
                "calibration_id": backend.spec.intrinsics.calibration_id,
            },
        )
        print(f"wrote {args.record}: {manifest.frames} frames, "
              f"captured_origin={manifest.captured_origin.value} (it will REPLAY as 'replay')")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
