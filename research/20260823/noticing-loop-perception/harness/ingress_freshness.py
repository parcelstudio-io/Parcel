"""H6 P3 / P8 — the PRODUCT freshness path, measured, and the RGB-only null result.

``camera_channel.ingress.CameraIngress`` is measured here, not restructured
(the DESIGN forbids touching its control flow). One ``poll_once()`` is one
capture -> detect -> localize -> publish cycle, and the frame it publishes
carries its own clocks, so ``CameraDetectionFrame.publish_latency_ns`` and
``expired_at_publish`` are the product's own verdict on its own freshness —
this harness only reads them.

Three venues:
  ``before``    renders at 1280x720 through the SHIPPING default detector
                (``cpu_int8`` in-process) — the 562 ms / 16-of-16-expired row.
  ``after``     the same scene at 640x360 through the H6 daemon (cuda_fp16).
  ``rgb_only``  the photo clip, which carries no depth at all — P8.

Map writes are counted through the map's own converter
(``online_map.ingest.observations_from_frame``) at ``require_fresh`` both ways:
what the map would take, and what it would take if it refused stale pixels.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from parcel_robot.camera_channel.backends.recorded import open_recorded_backend
from parcel_robot.camera_channel.ingress import CameraIngress
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.online_map.entries import WriterProvenance
from parcel_robot.online_map.ingest import observations_from_frame

PHOTO_LABELS = (
    "person", "chair", "car", "bicycle", "dog", "bench", "cup", "backpack",
    "umbrella", "traffic light",
)
RENDER_LABELS = ("person", "bench", "tree", "building", "lamppost", "planter", "door")


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _detector(kind: str, socket: str) -> Any:
    if kind == "daemon":
        from parcel_robot.perception_daemon.client import DaemonDetector

        return DaemonDetector(socket)
    from parcel_robot.detection_adapter.owlv2_onnx import load_owlv2_detector

    detector = load_owlv2_detector(require_env=False, requested_provider=kind)
    if detector is None:
        raise SystemExit(f"detector unavailable for provider {kind}")
    return detector


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H6 ingress freshness / map-write measurement")
    parser.add_argument("--clip", required=True)
    parser.add_argument("--detector", required=True,
                        help="daemon | cuda_fp16 | cpu_int8")
    parser.add_argument("--socket", default="")
    parser.add_argument("--labels", default="render", choices=("render", "photo"))
    parser.add_argument("--frames", type=int, default=16)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    backend = open_recorded_backend(args.clip, loop=True)
    spec = backend.spec
    detector = _detector(args.detector, args.socket)
    published: list[Any] = []
    ingress = CameraIngress(
        backend=backend,
        detector=detector,
        intrinsics=spec.intrinsics,
        mount=spec.mount,
        origin=EvidenceOrigin.REPLAY.value,
        min_poll_interval_s=0.0,
        on_frame=published.append,
        keep_thumbnails=True,
        keep_depth_patches=True,
    )
    labels = list(RENDER_LABELS if args.labels == "render" else PHOTO_LABELS)
    ingress.set_query(labels)
    ingress.set_pose(0.0, 0.0, 0.0)

    ingress.poll_once()  # warm the session / first-call cost, not measured
    published.clear()
    started = time.monotonic()
    for _ in range(args.frames):
        ingress.poll_once()
    wall_s = time.monotonic() - started

    provenance = WriterProvenance(
        session_id="h6-ingress", seat="owlv2", detector_name=str(getattr(detector, "name", "?")),
        scene_id="h6", origin=EvidenceOrigin.REPLAY.value,
    )
    latencies = [frame.publish_latency_ns / 1e6 for frame in published]
    expired = sum(1 for frame in published if frame.expired_at_publish)
    writes_any = 0
    writes_fresh = 0
    for frame in published:
        writes_any += len(
            observations_from_frame(frame, visit_id="h6", provenance=provenance)
        )
        writes_fresh += len(
            observations_from_frame(
                frame, visit_id="h6", provenance=provenance, require_fresh=True
            )
        )

    report = {
        "run": args.run_name,
        "clip": str(args.clip),
        "clip_has_depth": backend.has_depth,
        "detector": args.detector,
        "detector_name": str(getattr(detector, "name", "?")),
        "resolution": [spec.intrinsics.width_px, spec.intrinsics.height_px],
        "labels": labels,
        "polls": args.frames,
        "frames_published": len(published),
        "wall_s": wall_s,
        "poll_hz": args.frames / wall_s if wall_s else 0.0,
        "detection_ttl_ms": (published[0].detection_ttl_ns / 1e6) if published else None,
        "publish_latency_ms": {
            "p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95),
            "mean": statistics.fmean(latencies) if latencies else 0.0,
            "min": min(latencies, default=0.0), "max": max(latencies, default=0.0),
        },
        "expired_at_publish": expired,
        "expired_fraction": (expired / len(published)) if published else None,
        "map_writes": writes_any,
        "map_writes_fresh_only": writes_fresh,
        "ingress_stats": ingress.stats.as_dict(),
        "latencies_ms": latencies,
        "per_frame": [
            {
                "sequence": frame.sequence,
                "publish_latency_ms": frame.publish_latency_ns / 1e6,
                "expired": frame.expired_at_publish,
                "render_ms": frame.render_ms, "detect_ms": frame.detect_ms,
                "total_ms": frame.total_ms,
                "raw": frame.raw_detections, "localized": frame.localized_detections,
                "kept": len(frame.detections),
                "embedded": frame.embedded_detections,
                "relief": frame.relief_measured_detections,
            }
            for frame in published
        ],
    }
    if hasattr(detector, "close"):
        detector.close()
    backend.close()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items()
                      if k not in {"latencies_ms", "per_frame"}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
