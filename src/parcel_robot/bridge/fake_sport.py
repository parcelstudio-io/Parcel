"""Deterministic high-level Sport fake with explicitly seeded fault modes.

The fake models only the high-level effects N24 needs to refute gateway
claims.  It is not a Unitree SDK emulator and does not establish firmware or
robot compatibility.
"""

from __future__ import annotations

import json
import math
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class EventSink(Protocol):
    def __call__(self, event: dict[str, object]) -> None: ...


class NonBlockingEventSinkV1:
    """Bounded best-effort observer that can never block the control caller.

    This is intentionally tiny N24 fake-process plumbing, not N42's shared
    causal recorder.  Sink exceptions are counted and swallowed on a daemon
    worker; a full queue drops evidence with accounting rather than delaying a
    stop.  Control truth is never reconstructed from this observer.
    """

    def __init__(self, sink: EventSink | None, *, capacity: int = 256) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("event sink capacity must be a positive integer")
        self._sink = sink or (lambda event: None)
        self._queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=capacity)
        self._lock = threading.Lock()
        self._dropped_events = 0
        self._sink_errors = 0
        self._worker = threading.Thread(
            target=self._run,
            name="n24-fake-gateway-observer",
            daemon=True,
        )
        self._worker.start()

    @property
    def dropped_events(self) -> int:
        with self._lock:
            return self._dropped_events

    @property
    def sink_errors(self) -> int:
        with self._lock:
            return self._sink_errors

    def drain(self, *, timeout_s: float = 1.0) -> bool:
        """Wait a bounded time for queued evidence; never used by control paths."""

        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(float(timeout_s))
            or timeout_s < 0.0
        ):
            raise ValueError("drain timeout must be finite and non-negative")
        deadline = time.monotonic() + float(timeout_s)
        while True:
            with self._queue.mutex:
                pending = self._queue.unfinished_tasks
            if pending == 0:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.001)

    def __call__(self, event: dict[str, object]) -> None:
        try:
            self._queue.put_nowait(dict(event))
        except queue.Full:
            with self._lock:
                self._dropped_events += 1

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            try:
                self._sink(event)
            except Exception:  # noqa: BLE001 - observer failure never reaches control
                with self._lock:
                    self._sink_errors += 1
            finally:
                self._queue.task_done()


def nonblocking_event_sink(
    sink: EventSink | NonBlockingEventSinkV1 | None,
) -> NonBlockingEventSinkV1:
    if isinstance(sink, NonBlockingEventSinkV1):
        return sink
    return NonBlockingEventSinkV1(sink)


class JsonlEventSink:
    """Append and fsync one bounded fake-gateway evidence event."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def __call__(self, event: dict[str, object]) -> None:
        payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
        if len(payload.encode("utf-8")) > 16 * 1024:
            raise ValueError("fake gateway evidence event exceeds 16 KiB")
        with self._lock, self._path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())


@dataclass(frozen=True, slots=True)
class FakeSportFaultsV1:
    move_delay_s: float = 0.0
    move_no_reply: bool = False
    stale_state_by_s: float = 0.0
    out_of_order_state: bool = False
    stop_move_failure: bool = False

    def __post_init__(self) -> None:
        for name in ("move_delay_s", "stale_state_by_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name in ("move_no_reply", "out_of_order_state", "stop_move_failure"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be boolean")


@dataclass(frozen=True, slots=True)
class FakeSportStateV1:
    sequence: int
    received_at_monotonic_s: float
    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float
    lease_active: bool

    @property
    def stationary(self) -> bool:
        return all(abs(value) <= 1e-9 for value in (self.vx_mps, self.vy_mps, self.vyaw_rad_s))


class FakeSportServiceV1:
    """Thread-safe fake Sport writer, Move/StopMove, lease, and state source."""

    def __init__(
        self,
        *,
        faults: FakeSportFaultsV1 | None = None,
        clock: Callable[[], float] = time.monotonic,
        event_sink: EventSink | None = None,
    ) -> None:
        self.faults = faults or FakeSportFaultsV1()
        self._clock = clock
        self._event_sink = nonblocking_event_sink(event_sink)
        self._lock = threading.Lock()
        self._writer_id: str | None = None
        self._lease_active = False
        self._sequence = 1
        self._received_at = self._clock()
        self._velocity = (0.0, 0.0, 0.0)
        self._no_reply_release = threading.Event()

    @property
    def writer_id(self) -> str | None:
        with self._lock:
            return self._writer_id

    def acquire_writer(self, writer_id: str) -> bool:
        with self._lock:
            if self._writer_id is not None and self._writer_id != writer_id:
                self._record("writer_conflict", requested_writer=writer_id)
                return False
            self._writer_id = writer_id
            self._lease_active = True
            self._advance_state_locked()
        self._record("lease_acquired", writer_id=writer_id)
        return True

    def release_writer(self, writer_id: str | None) -> None:
        with self._lock:
            if writer_id is not None and self._writer_id not in {None, writer_id}:
                return
            released = self._writer_id
            self._writer_id = None
            self._lease_active = False
            self._advance_state_locked()
        self._record("lease_released", writer_id=released or "")

    def force_lease_loss(self) -> None:
        with self._lock:
            self._lease_active = False
            self._advance_state_locked()
        self._record("lease_lost")

    def move(self, *, writer_id: str, vx_mps: float, vy_mps: float, vyaw_rad_s: float) -> None:
        self._record("move_called", writer_id=writer_id)
        with self._lock:
            if writer_id != self._writer_id:
                raise RuntimeError("fake Sport Move writer mismatch")
            if not self._lease_active:
                raise RuntimeError("fake Sport lease lost")
        self._record("move_accepted", writer_id=writer_id)
        # The RPC was accepted while the writer held the lease.  A delayed
        # completion may therefore apply after a concurrent stop/release; that
        # is the exact late-Move hazard the gateway stop epoch must compensate.
        if self.faults.move_delay_s:
            time.sleep(self.faults.move_delay_s)
        with self._lock:
            self._velocity = (float(vx_mps), float(vy_mps), float(vyaw_rad_s))
            self._advance_state_locked()
        self._record(
            "move_applied",
            writer_id=writer_id,
            vx_mps=vx_mps,
            vy_mps=vy_mps,
            vyaw_rad_s=vyaw_rad_s,
        )
        if self.faults.move_no_reply:
            self._record("move_no_reply", writer_id=writer_id)
            self._no_reply_release.wait()

    def stop_move(self, *, reason: str) -> bool:
        if self.faults.stop_move_failure:
            self._record("stop_move_called", reason=reason)
            self._record("stop_move_failed", reason=reason)
            return False
        with self._lock:
            self._velocity = (0.0, 0.0, 0.0)
            self._advance_state_locked()
        # The physical fake effect happens before either observational write.
        # A raising, blocked, or full sink cannot prevent the exact-zero stop.
        self._record("stop_move_called", reason=reason)
        self._record("stop_move_succeeded", reason=reason)
        return True

    def state(self) -> FakeSportStateV1:
        with self._lock:
            if not self.faults.stale_state_by_s and not self.faults.out_of_order_state:
                # Model a periodic high-level state stream.  Every poll sees a
                # distinct source sample in the healthy fixture.
                self._advance_state_locked()
            sequence = self._sequence
            received_at = self._received_at
            if self.faults.out_of_order_state:
                sequence = max(1, sequence - 1)
            if self.faults.stale_state_by_s:
                received_at = self._clock() - self.faults.stale_state_by_s
            return FakeSportStateV1(
                sequence=sequence,
                received_at_monotonic_s=received_at,
                vx_mps=self._velocity[0],
                vy_mps=self._velocity[1],
                vyaw_rad_s=self._velocity[2],
                lease_active=self._lease_active,
            )

    def close(self) -> None:
        self._no_reply_release.set()

    def _advance_state_locked(self) -> None:
        self._sequence += 1
        self._received_at = self._clock()

    def _record(self, event: str, **details: object) -> None:
        self._event_sink({"event": event, "at_monotonic_s": self._clock(), **details})
