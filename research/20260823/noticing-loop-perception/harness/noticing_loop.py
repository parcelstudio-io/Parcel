"""H6 harness — the continuous noticing loop, measured end to end.

One frame of the loop is: capture (recorded backend) -> detect (OWLv2 fp16 in
the H6 perception daemon, over its own AF_UNIX socket) -> crop embeddings
(SigLIP-2 fp16 in the same daemon) -> novelty score and the noticing decision
(``perception.noticing``, pure) -> publish. The freshness clock starts at
capture START and stops at publish, exactly as ``CameraDetectionFrame`` defines
it (``publish_latency_ns`` = published - capture_started), so P3's histogram is
measured against the same 300 ms TTL the product path is judged by.

Every raw per-frame and per-detection row is written to JSON; the criteria are
scored by ``analyze.py`` from those rows, never from a number this file prints.

Gate pre-filtering: the size/score gates are applied HERE, before the crop is
embedded, because embedding a 20x14 crop to then discard it is the one cost the
real loop would never pay. The counts are reported separately from
``NoticingLoop.stats`` so nothing is double-counted.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

from parcel_robot.camera_channel.backends.recorded import open_recorded_backend
from parcel_robot.perception.noticing import NoticingGate, NoticingLoop, Observation

WARMUP_FRAMES = 8


class NumpyGallery:
    """A vectorised stand-in for ``noticing.NoveltyGallery`` (same contract).

    The product module is pure Python on purpose (no numpy, testable anywhere),
    and its cosine loop costs O(gallery x dims) per probe: measured here at
    40 ms p50 / 139 ms p95 per frame once the gallery held ~200 SigLIP-2
    vectors, which is a third of the loop's budget spent on arithmetic numpy
    does in microseconds. So the loop rows are measured with this injected
    gallery, and ``tests/test_h6_noticing.py`` pins the two implementations to
    the same scores. The pure/vectorised cost difference is itself reported.
    """

    def __init__(self, limit: int) -> None:
        self._limit = int(limit)
        self._matrix: np.ndarray | None = None
        self._count = 0

    def __len__(self) -> int:
        return self._count

    @property
    def limit(self) -> int:
        return self._limit

    @staticmethod
    def _unit(vector) -> np.ndarray:
        arr = np.asarray(vector, dtype=np.float64).ravel()
        norm = float(np.linalg.norm(arr))
        return arr if norm <= 0.0 else arr / norm

    def add(self, vector) -> None:
        unit = self._unit(vector)
        if not np.any(unit):
            return
        if self._matrix is None:
            self._matrix = np.zeros((self._limit, unit.size), dtype=np.float64)
        self._matrix[self._count % self._limit] = unit
        self._count = min(self._limit, self._count + 1)

    def nearest_cosine(self, vector) -> float:
        unit = self._unit(vector)
        if self._matrix is None or self._count == 0 or not np.any(unit):
            return 0.0
        sims = self._matrix[: self._count] @ unit
        return float(max(0.0, sims.max()))

    def novelty(self, vector) -> float:
        return min(1.0, max(0.0, 1.0 - self.nearest_cosine(vector)))


def smi() -> dict[str, str]:
    """nvidia-smi at a measurement point — recorded, never assumed."""

    def query(fields: str, mode: str) -> str:
        try:
            return subprocess.run(
                ["nvidia-smi", f"--query-{mode}={fields}", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=20, check=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return f"nvidia-smi failed: {exc}"

    return {
        "gpu": query("memory.used,memory.total,utilization.gpu,utilization.memory", "gpu"),
        "procs": query("pid,process_name,used_memory", "compute-apps"),
    }


class ReasonerLoad:
    """Keep a llama.cpp server generating so the GPU is genuinely contended."""

    def __init__(self, url: str, *, max_tokens: int = 256) -> None:
        self._url = url
        self._max_tokens = int(max_tokens)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.completions = 0
        self.errors = 0
        self.tokens = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        body = json.dumps(
            {"prompt": "Describe, in careful detail, a city street at dusk.",
             "max_tokens": self._max_tokens, "temperature": 0.9}
        ).encode()
        while not self._stop.is_set():
            request = urllib.request.Request(
                self._url, data=body, headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    payload = json.load(response)
                self.completions += 1
                self.tokens += int(payload.get("usage", {}).get("completion_tokens", 0))
            except (OSError, ValueError):  # a load-generation failure is data, not a crash
                self.errors += 1
                time.sleep(0.5)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=400)

    def as_dict(self) -> dict[str, Any]:
        return {"url": self._url, "max_tokens": self._max_tokens,
                "completions": self.completions, "tokens": self.tokens, "errors": self.errors}


def _frame_gt(gt_clips: dict, clip_name: str) -> list[list[dict]]:
    for clip in gt_clips["clips"]:
        if clip["clip"] == clip_name:
            return [record["objects"] for record in clip["records"]]
    raise SystemExit(f"no ground truth for clip {clip_name}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    from parcel_robot.perception_daemon.client import DaemonClient

    labels = [phrase.strip() for phrase in args.labels.split(",") if phrase.strip()]
    gt_by_frame = _frame_gt(json.loads(Path(args.gt).read_text()), args.clip_name)
    backend = open_recorded_backend(args.clip, loop=True)
    client = DaemonClient(args.socket)
    health_before = client.health()
    gate = NoticingGate(
        novelty_tau=args.tau, cooldown_s=args.cooldown_s, max_per_minute=args.max_per_minute
    )
    loop = NoticingLoop(
        gate=gate,
        gallery=None if args.pure_gallery else NumpyGallery(gate.gallery_limit),
    )

    for _ in range(WARMUP_FRAMES):
        backend.capture()
        buffers = backend.last_buffers
        assert buffers is not None and buffers.color_rgb8 is not None
        rgb = np.asarray(buffers.color_rgb8)
        client.detect(rgb, labels)
        client.embed_image(rgb[: max(32, rgb.shape[0] // 4), : max(32, rgb.shape[1] // 4)])
    backend.rewind()

    load = None
    if args.contend_url:
        load = ReasonerLoad(args.contend_url, max_tokens=args.contend_tokens)
        load.start()
        time.sleep(args.contend_warmup_s)

    smi_start = smi()
    frames: list[dict[str, Any]] = []
    detections: list[dict[str, Any]] = []
    period_ns = 0 if args.hz <= 0 else int(1e9 / args.hz)
    started_ns = time.monotonic_ns()
    next_tick = started_ns
    index = 0
    smi_mid: dict[str, str] | None = None
    while True:
        elapsed_s = (time.monotonic_ns() - started_ns) / 1e9
        if elapsed_s >= args.duration_s:
            break
        if period_ns:
            now = time.monotonic_ns()
            if now < next_tick:
                time.sleep((next_tick - now) / 1e9)
            next_tick += period_ns
        if smi_mid is None and elapsed_s >= args.duration_s / 2:
            smi_mid = smi()

        capture_started_ns = time.monotonic_ns()
        backend.capture()
        buffers = backend.last_buffers
        assert buffers is not None and buffers.color_rgb8 is not None
        rgb = np.asarray(buffers.color_rgb8)
        capture_done_ns = time.monotonic_ns()

        response = client.detect(rgb, labels)
        detect_done_ns = time.monotonic_ns()
        rows = response.get("detections", [])

        survivors = []
        rejected_score = rejected_size = 0
        for row in rows:
            u0, v0, u1, v1 = (int(v) for v in row["box"])
            if float(row["score"]) < gate.min_score:
                rejected_score += 1
                continue
            if (u1 - u0) * (v1 - v0) < gate.min_box_pixels:
                rejected_size += 1
                continue
            survivors.append((float(row["score"]), str(row["label"]), (u0, v0, u1, v1)))
        survivors.sort(key=lambda item: -item[0])
        truncated = max(0, len(survivors) - args.max_embeds)
        survivors = survivors[: args.max_embeds]

        observations: list[Observation] = []
        for score, label, box in survivors:
            u0, v0, u1, v1 = box
            crop = rgb[v0:v1, u0:u1]
            vector = tuple(float(v) for v in client.embed_image(np.ascontiguousarray(crop)))
            observations.append(
                Observation(label=label, score=score, box=box, embedding=vector,
                            monotonic_ns=time.monotonic_ns(), sequence=index)
            )
        embed_done_ns = time.monotonic_ns()

        # Per-observation, not per-frame: two labels can land on the SAME box
        # (a "person" and a "chair" on one chair-shaped blob), and attributing
        # the decision by box would then credit both with one noticing.
        decisions: list[tuple[float, bool]] = []
        for observation in observations:
            novelty = loop.novelty_of(observation)
            decisions.append((novelty, loop.observe(observation) is not None))
        noticings = [flag for _, flag in decisions if flag]
        published_ns = time.monotonic_ns()

        gt_index = index % len(gt_by_frame)
        for observation, (novelty, noticed) in zip(observations, decisions, strict=True):
            detections.append(
                {
                    "frame": index, "gt_frame": gt_index,
                    "label": observation.label, "score": observation.score,
                    "box": list(observation.box), "novelty": novelty,
                    "noticed": noticed,
                    "monotonic_ns": observation.monotonic_ns,
                }
            )
        frames.append(
            {
                "index": index, "gt_frame": gt_index,
                "capture_started_ns": capture_started_ns,
                "published_ns": published_ns,
                "publish_latency_ms": (published_ns - capture_started_ns) / 1e6,
                "capture_ms": (capture_done_ns - capture_started_ns) / 1e6,
                "detect_wall_ms": (detect_done_ns - capture_done_ns) / 1e6,
                "detect_daemon_ms": float(response.get("detect_ms", 0.0)),
                "embed_ms": (embed_done_ns - detect_done_ns) / 1e6,
                "decide_ms": (published_ns - embed_done_ns) / 1e6,
                "raw_detections": len(rows), "embedded": len(observations),
                "rejected_score": rejected_score, "rejected_size": rejected_size,
                "truncated_embeds": truncated, "noticings": len(noticings),
            }
        )
        index += 1

    wall_s = (time.monotonic_ns() - started_ns) / 1e9
    smi_end = smi()
    if load is not None:
        load.stop()
    health_after = client.health()
    client.close()
    backend.close()

    return {
        "run": args.run_name,
        "clip": args.clip_name,
        "labels": labels,
        "query_phrases": len(labels),
        "resolution": [int(rgb.shape[1]), int(rgb.shape[0])],
        "requested_hz": args.hz,
        "duration_s": wall_s,
        "frames": len(frames),
        "achieved_fps": len(frames) / wall_s if wall_s > 0 else 0.0,
        "gate": {
            "novelty_tau": gate.novelty_tau, "min_score": gate.min_score,
            "min_box_pixels": gate.min_box_pixels, "cooldown_s": gate.cooldown_s,
            "max_per_minute": gate.max_per_minute, "gallery_limit": gate.gallery_limit,
        },
        "max_embeds": args.max_embeds,
        "gallery_impl": "pure" if args.pure_gallery else "numpy",
        "loop_stats": loop.stats.as_dict(),
        "gallery_size": len(loop.gallery),
        "daemon_health_before": health_before,
        "daemon_health_after": health_after,
        "contention": None if load is None else load.as_dict(),
        "smi_start": smi_start, "smi_mid": smi_mid, "smi_end": smi_end,
        "frame_rows": frames,
        "detection_rows": detections,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="H6 noticing-loop measurement")
    parser.add_argument("--clip", required=True)
    parser.add_argument("--clip-name", required=True)
    parser.add_argument("--gt", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--hz", type=float, default=0.0, help="0 = free-run (max rate)")
    parser.add_argument("--duration-s", type=float, default=60.0)
    parser.add_argument("--tau", type=float, default=0.35)
    parser.add_argument("--cooldown-s", type=float, default=5.0)
    parser.add_argument("--max-per-minute", type=int, default=6)
    parser.add_argument("--max-embeds", type=int, default=5)
    parser.add_argument("--contend-url", default="")
    parser.add_argument("--contend-tokens", type=int, default=256)
    parser.add_argument("--contend-warmup-s", type=float, default=3.0)
    parser.add_argument("--pure-gallery", action="store_true",
                        help="use the product module's pure-Python gallery (slower; for the cost row)")
    parser.add_argument("--run-name", default="run")
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(args)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report))
    summary = {k: v for k, v in report.items() if k not in {"frame_rows", "detection_rows"}}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
