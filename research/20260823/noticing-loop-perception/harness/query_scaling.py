"""H6 — what an open vocabulary costs per frame, measured through the daemon.

The fused OWLv2 ONNX takes ``(input_ids[Q,16], attention_mask[Q,16],
pixel_values)`` in one graph, so the text tower is re-encoded on EVERY frame:
a 16-phrase batch pays for 16 text encodes 10 times a second to answer with
the same 16 vectors it computed last frame. Whether that matters is a
measurement, not an opinion — this is the measurement, at the loop's own
resolution, over the same daemon the loop uses.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

from parcel_robot.camera_channel.backends.recorded import read_clip

VOCABULARY = (
    "person", "chair", "car", "bicycle", "dog", "bench", "cup", "backpack",
    "umbrella", "traffic light", "bottle", "book", "door", "tree", "bag", "phone",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H6 detect latency vs query-batch size")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--clip", default="photos_640.npz")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--repeats", type=int, default=25)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    from parcel_robot.perception_daemon.client import DaemonClient

    _, color, _ = read_clip(Path(args.corpus) / "clips" / args.clip)
    frames = [np.ascontiguousarray(color[i]) for i in range(min(10, color.shape[0]))]
    client = DaemonClient(args.socket)
    for frame in frames[:3]:
        client.detect(frame, list(VOCABULARY[:4]))

    rows = {}
    for count in (1, 2, 4, 7, 10, 16):
        labels = list(VOCABULARY[:count])
        daemon_ms: list[float] = []
        wall_ms: list[float] = []
        for index in range(args.repeats):
            frame = frames[index % len(frames)]
            started = time.perf_counter()
            response = client.detect(frame, labels)
            wall_ms.append((time.perf_counter() - started) * 1000.0)
            daemon_ms.append(float(response.get("detect_ms", 0.0)))
        rows[str(count)] = {
            "phrases": count,
            "detect_daemon_ms_mean": statistics.fmean(daemon_ms),
            "detect_daemon_ms_median": statistics.median(daemon_ms),
            "wall_ms_median": statistics.median(wall_ms),
            "ipc_overhead_ms_median": statistics.median(
                [w - d for w, d in zip(wall_ms, daemon_ms, strict=True)]
            ),
            "n": len(daemon_ms),
        }
    health = client.health()
    client.close()
    report = {
        "clip": args.clip,
        "resolution": [int(frames[0].shape[1]), int(frames[0].shape[0])],
        "provider_profile": health.get("provider_profile"),
        "execution_providers": health.get("execution_providers"),
        "rows": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
