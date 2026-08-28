"""Non-blocking producer boundary for the local research plane.

Admission runs before enqueue so raw/unknown payloads never enter the worker
queue.  SQLite and gzip work occurs only on the daemon thread.  Queue pressure
is reported as a gap counter and never blocks a conversation or control loop.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from collections.abc import Mapping
from typing import Any

from .admission import admit_candidate
from .pipeline import DisabledResearchPlane, ResearchPlane
from .spool import SpoolDecision


class AsyncResearchSink:
    def __init__(
        self,
        plane: ResearchPlane | DisabledResearchPlane,
        *,
        max_queue_events: int = 8192,
        bundle_every_events: int = 512,
    ) -> None:
        if max_queue_events <= 0 or bundle_every_events <= 0:
            raise ValueError("worker limits must be positive")
        self.plane = plane
        self._max_queue = int(max_queue_events)
        self._bundle_every = int(bundle_every_events)
        self._queue: deque[dict[str, object]] = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._stopping = False
        self._counters: Counter[str] = Counter()

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return True
            if not self.plane.enabled:
                self._counters["start_disabled"] += 1
                return False
            self._running = True
            self._stopping = False
            self._thread = threading.Thread(
                target=self._run,
                name="parcel-research-plane",
                daemon=True,
            )
            self._thread.start()
            return True

    def offer(self, candidate: Mapping[str, object]) -> bool:
        """Validate and queue one event without waiting for storage."""

        admission = admit_candidate(candidate)
        if not admission.accepted or admission.event is None:
            with self._lock:
                self._counters[f"rejected:{admission.reason}"] += 1
            return False
        event = admission.event.as_dict()
        with self._lock:
            if not self._running or self._stopping:
                self._counters["dropped:not_running"] += 1
                return False
            if len(self._queue) >= self._max_queue:
                self._counters["dropped:queue_full"] += 1
                return False
            self._queue.append(event)
            self._counters["queued"] += 1
        self._wake.set()
        return True

    def close(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._stopping = True
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10.0)
        with self._lock:
            if self._running:
                self._counters["worker_join_timeout"] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "stopping": self._stopping,
                "queue_depth": len(self._queue),
                "max_queue_events": self._max_queue,
                "counters": dict(sorted(self._counters.items())),
            }

    def _run(self) -> None:
        stored_since_bundle = 0
        try:
            while True:
                event = self._take()
                if event is None:
                    with self._lock:
                        if self._stopping and not self._queue:
                            break
                    self._wake.wait(timeout=0.5)
                    self._wake.clear()
                    continue
                try:
                    decision, reason = self.plane.emit(event)
                    with self._lock:
                        self._counters[f"emit:{decision.value}:{reason}"] += 1
                    if decision is SpoolDecision.STORED:
                        stored_since_bundle += 1
                    if stored_since_bundle >= self._bundle_every:
                        self._bundle_all()
                        stored_since_bundle = 0
                except Exception as exc:  # noqa: BLE001 - evidence must not stop producers
                    with self._lock:
                        self._counters[f"worker_error:{type(exc).__name__}"] += 1
            try:
                self._bundle_all()
            except Exception as exc:  # noqa: BLE001 - close-time evidence containment
                with self._lock:
                    self._counters[f"worker_error:{type(exc).__name__}"] += 1
        finally:
            with self._lock:
                self._running = False
                self._thread = None

    def _take(self) -> dict[str, object] | None:
        with self._lock:
            return self._queue.popleft() if self._queue else None

    def _bundle_all(self) -> None:
        while True:
            artifact = self.plane.bundle_next()
            if artifact is None:
                return
            with self._lock:
                self._counters["bundled"] += 1
