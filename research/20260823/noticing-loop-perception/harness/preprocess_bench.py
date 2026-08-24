"""H6 — the CPU-side share of OWLv2 latency, measured without a GPU session.

The 2026-08-21 bench's highest-leverage claim was "73 % of OWLv2's latency is
CPU-side preprocessing, and it scales with SOURCE resolution though the model
always sees 960x960". That claim decides whether the loop's budget is spent on
the GPU we are trying to justify or on a numpy resize — so it is measured here
directly, at the two resolutions H6 cares about, INTERLEAVED in one process so
that a host under someone else's 48-thread load perturbs both arms equally and
the RATIO survives. No ONNX session is built (an ``object.__new__`` shell, the
same idiom ``tests/test_owlv2_detector.py`` uses), so this needs no weights, no
VRAM, and cannot disturb anyone else's GPU measurement.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

from parcel_robot.detection_adapter.owlv2_onnx import OWLV2_IMAGE_SIZE, OwlV2Detector


def _shell() -> OwlV2Detector:
    detector = object.__new__(OwlV2Detector)
    detector._np = np
    detector._img_h = OWLV2_IMAGE_SIZE
    detector._img_w = OWLV2_IMAGE_SIZE
    detector._img_mean = np.asarray([0.5, 0.5, 0.5], dtype=np.float32)
    detector._img_std = np.asarray([0.5, 0.5, 0.5], dtype=np.float32)
    detector._rescale = 1.0 / 255.0
    detector._pad_value = 0.5
    detector.fast_preprocess = True
    detector.source_max_edge = 0
    return detector


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H6 preprocessing cost vs source resolution")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--repeats", type=int, default=40)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    from parcel_robot.camera_channel.backends.recorded import read_clip

    corpus = Path(args.corpus)
    _, big, _ = read_clip(corpus / "clips" / "renders_1280.npz")
    _, small, _ = read_clip(corpus / "clips" / "renders_640.npz")
    detector = _shell()
    frames = {
        "1280x720": [np.ascontiguousarray(big[i]) for i in range(8)],
        "640x360": [np.ascontiguousarray(small[i]) for i in range(8)],
    }
    for batch in frames.values():
        for frame in batch[:2]:
            detector._preprocess_image(frame)

    samples: dict[str, list[float]] = {name: [] for name in frames}
    for index in range(args.repeats):
        for name, batch in frames.items():  # interleaved: same load on both arms
            frame = batch[index % len(batch)]
            started = time.perf_counter()
            detector._preprocess_image(frame)
            samples[name].append((time.perf_counter() - started) * 1000.0)

    def fast_path_used(frame: np.ndarray) -> bool:
        height, width = int(frame.shape[0]), int(frame.shape[1])
        side = max(height, width)
        return bool(
            detector._seam_is_clean(
                height, width, side,
                OWLV2_IMAGE_SIZE * height // side, OWLV2_IMAGE_SIZE * width // side,
            )
        )

    report = {
        "repeats": args.repeats,
        "loadavg": list(__import__("os").getloadavg()),
        "fast_preprocess": detector.fast_preprocess,
        "arms": {
            name: {
                "median_ms": statistics.median(values),
                "mean_ms": statistics.fmean(values),
                "min_ms": min(values),
                "n": len(values),
                "fast_path_used": fast_path_used(frames[name][0]),
            }
            for name, values in samples.items()
        },
    }
    report["ratio_1280_over_640_median"] = (
        report["arms"]["1280x720"]["median_ms"] / report["arms"]["640x360"]["median_ms"]
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
