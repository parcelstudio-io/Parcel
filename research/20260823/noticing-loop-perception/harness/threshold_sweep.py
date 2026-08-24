"""H6 P6 — the operating point, found through the repo's own detector.

One inference pass per (corpus, provider) at a score floor of 0.005 with the
per-frame cap lifted to 512; every surviving box is written out with its score,
and the thresholds are swept afterwards by FILTERING those rows. That is exact,
not an approximation: ``owlv2_onnx._nms`` is greedy over score-descending boxes
per label, so the survivors above ``t`` are identical to the survivors of a run
whose threshold was ``t`` — provided the cap never binds, which is recorded per
frame (``truncated``) so a reader can check rather than trust. ``--verify``
re-runs a subset at a real threshold and asserts the two agree.

Corpora: the 156 real photos at native size, the 42 city renders at 1280x720,
and the same photos letterboxed to the loop's 640x360 (the loop's own operating
resolution is a different question from the bench's, and both are reported).

The CPU-side share of latency is measured in the same process by timing
``_preprocess_image`` alone over the same frames.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

SCORE_FLOOR = 0.005
MAX_DETECTIONS = 512
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


def _load_frames(corpus: Path, which: str) -> list[tuple[str, np.ndarray]]:
    if which == "photos_native":
        manifest = json.loads((corpus / "photos_gt.json").read_text())
        frames = []
        for record in manifest["records"]:
            bgr = cv2.imread(str(corpus / "photos" / record["file"]), cv2.IMREAD_COLOR)
            frames.append((record["file"], np.ascontiguousarray(bgr[:, :, ::-1])))
        return frames
    if which == "photos_640":
        from parcel_robot.camera_channel.backends.recorded import read_clip

        _, color, _ = read_clip(corpus / "clips" / "photos_640.npz")
        manifest = json.loads((corpus / "photos_gt.json").read_text())
        return [
            (record["file"], np.ascontiguousarray(color[i]))
            for i, record in enumerate(manifest["records"])
        ]
    if which == "renders_1280":
        with np.load(corpus / "renders.npz") as data:
            color = np.ascontiguousarray(data["color"])
        return [(str(i), color[i]) for i in range(color.shape[0])]
    if which == "renders_640":
        from parcel_robot.camera_channel.backends.recorded import read_clip

        _, color, _ = read_clip(corpus / "clips" / "renders_640.npz")
        return [(str(i), np.ascontiguousarray(color[i])) for i in range(color.shape[0])]
    raise SystemExit(f"unknown corpus {which}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H6 threshold sweep (one pass, filtered after)")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--which", required=True,
                        choices=("photos_native", "photos_640", "renders_1280", "renders_640"))
    parser.add_argument("--provider", required=True, choices=("cuda_fp16", "cpu_int8"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--verify-threshold", type=float, default=0.0,
                        help="re-run the first N frames at this real threshold and compare")
    parser.add_argument("--verify-frames", type=int, default=6)
    args = parser.parse_args(argv)

    from parcel_robot.detection_adapter.owlv2_onnx import load_owlv2_detector

    corpus = Path(args.corpus)
    labels = list(PHOTO_LABELS if args.which.startswith("photos") else RENDER_LABELS)
    frames = _load_frames(corpus, args.which)

    detector = load_owlv2_detector(
        require_env=False, threshold=SCORE_FLOOR, requested_provider=args.provider
    )
    if detector is None:
        raise SystemExit(f"detector unavailable for provider {args.provider}")
    detector.max_detections = MAX_DETECTIONS
    detector.guard = None  # the contention guard is H6's P7 row, not this one

    for _, rgb in frames[:3]:
        detector.detect(rgb=rgb, depth=None, seg=None, query=labels)

    rows = []
    latencies: list[float] = []
    for name, rgb in frames:
        started = time.perf_counter()
        detections = detector.detect(rgb=rgb, depth=None, seg=None, query=labels)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latencies.append(elapsed_ms)
        rows.append(
            {
                "frame": name,
                "height": int(rgb.shape[0]), "width": int(rgb.shape[1]),
                "detect_ms": elapsed_ms,
                "truncated": len(detections) >= MAX_DETECTIONS,
                "detections": [
                    {"label": d.label, "score": d.score, "box": list(d.box)} for d in detections
                ],
            }
        )

    preprocess_ms: list[float] = []
    for _, rgb in frames[: min(30, len(frames))]:
        started = time.perf_counter()
        detector._preprocess_image(rgb)
        preprocess_ms.append((time.perf_counter() - started) * 1000.0)

    verification = None
    if args.verify_threshold > 0.0:
        detector.threshold = float(args.verify_threshold)
        detector.max_detections = 64
        agreed = disagreed = 0
        for (name, rgb), row in zip(
            frames[: args.verify_frames], rows[: args.verify_frames], strict=False
        ):
            direct = {
                (d.label, tuple(d.box)) for d in
                detector.detect(rgb=rgb, depth=None, seg=None, query=labels)
            }
            filtered = {
                (d["label"], tuple(d["box"])) for d in row["detections"]
                if d["score"] >= args.verify_threshold
            }
            if direct == filtered:
                agreed += 1
            else:
                disagreed += 1
        verification = {
            "threshold": args.verify_threshold, "frames": args.verify_frames,
            "agreed": agreed, "disagreed": disagreed,
        }

    report = {
        "which": args.which,
        "provider": args.provider,
        "resolution_selected": detector.resolution.describe(),
        "honoured_providers": list(detector.honoured_providers),
        "labels": labels,
        "score_floor": SCORE_FLOOR,
        "frames": len(frames),
        "detect_ms": {
            "p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95),
            "mean": statistics.fmean(latencies), "max": max(latencies),
        },
        "preprocess_ms": {
            "p50": _percentile(preprocess_ms, 0.5), "p95": _percentile(preprocess_ms, 0.95),
            "n": len(preprocess_ms),
        },
        "verification": verification,
        "rows": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report))
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
