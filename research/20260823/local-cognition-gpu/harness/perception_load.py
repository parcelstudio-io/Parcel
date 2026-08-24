"""A 10 Hz OWLv2 + SigLIP-2 load on the GPU, and its own p95 while it runs.

This is the *contention source* for G2 and the *measured subject* for G3. It
runs in a thread: fire a detect at a fixed 10 Hz cadence on synthetic frames,
then one SigLIP-2 image embedding, and record the wall time of each detect.

The frames are synthetic on purpose — H2 is a latency/contention experiment,
not a recall experiment. What OWLv2 *finds* in these frames is H6's question
and is deliberately not claimed here. What matters is that the GPU is doing
the real per-frame work at the real cadence.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np

from parcel_robot.perception_daemon.client import DaemonClient
from parcel_robot.perception_daemon.protocol import DaemonUnavailable

QUERIES = ("a person", "a dog", "a backpack", "a door", "a bench")
FRAME_SHAPE = (480, 640, 3)


def synthetic_frames(count: int = 16, seed: int = 11) -> list[np.ndarray]:
    """A small ring of structured frames. Structured, not noise: pure noise
    makes OWLv2's post-processing trivially short and would understate load."""

    rng = np.random.default_rng(seed)
    frames = []
    for index in range(count):
        frame = np.zeros(FRAME_SHAPE, dtype=np.uint8)
        frame[:, :, 0] = np.linspace(20, 200, FRAME_SHAPE[1], dtype=np.uint8)[None, :]
        frame[:, :, 1] = np.linspace(30, 180, FRAME_SHAPE[0], dtype=np.uint8)[:, None]
        for _ in range(6):
            y0 = int(rng.integers(0, FRAME_SHAPE[0] - 80))
            x0 = int(rng.integers(0, FRAME_SHAPE[1] - 80))
            frame[y0 : y0 + 70, x0 : x0 + 70] = rng.integers(0, 255, (70, 70, 3), dtype=np.uint8)
        frames.append(np.ascontiguousarray(frame))
    return frames


@dataclass
class PerceptionLoad:
    """Drive the daemon at ``hz`` in a background thread and time every call."""

    socket_path: str
    hz: float = 10.0
    detect_ms: list[float] = field(default_factory=list)
    embed_ms: list[float] = field(default_factory=list)
    errors: int = 0
    frames: int = 0
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def probe(self) -> dict[str, object]:
        client = DaemonClient(self.socket_path)
        try:
            return client.health()
        finally:
            client.close()

    def _run(self) -> None:
        client = DaemonClient(self.socket_path, request_timeout_s=30.0)
        ring = synthetic_frames()
        period = 1.0 / self.hz
        index = 0
        next_at = time.perf_counter()
        try:
            while not self._stop.is_set():
                frame = ring[index % len(ring)]
                index += 1
                started = time.perf_counter()
                try:
                    client.detect(frame, QUERIES)
                    self.detect_ms.append((time.perf_counter() - started) * 1000.0)
                    embed_started = time.perf_counter()
                    client.embed_image(frame)
                    self.embed_ms.append((time.perf_counter() - embed_started) * 1000.0)
                    self.frames += 1
                except (DaemonUnavailable, OSError, RuntimeError):
                    self.errors += 1
                next_at += period
                sleep_for = next_at - time.perf_counter()
                if sleep_for > 0:
                    self._stop.wait(sleep_for)
                else:
                    next_at = time.perf_counter()
        finally:
            client.close()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="h2-perception-load", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30.0)
            self._thread = None

    def reset_samples(self) -> None:
        self.detect_ms.clear()
        self.embed_ms.clear()
        self.frames = 0
        self.errors = 0
