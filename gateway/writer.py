"""The single vendor command writer — one thread, one slot, veto-only.

X12 (``scrum/20260823/task_1/FABLE_VERDICT.md``) puts the governor and the
gateway in one process with "one clamp owner (the governor), the writer module
veto-only (may reject/zero, never originate/increase)".  This module is that
writer, and it holds to the rule in the only way that survives review: it has
no arithmetic at all.  It takes an already-governed setpoint and either writes
exactly those three numbers to the vendor or writes nothing and asks the core
to stop.

**One slot, latest wins.**  A control writer that queues is a writer that
applies stale motion after a fresher command exists.  ``submit`` overwrites the
pending slot and counts the supersession; it never blocks the caller, which is
holding the core lock.

**Two gates immediately before the vendor call**, on the writer thread, at the
last possible instant:

1.  the stop epoch must still be the one the setpoint was admitted under —
    otherwise a stop happened in between and this write is dead; and
2.  the receiver-derived deadline must still be in the future — otherwise the
    TTL expired while the write was queued.

Either gate closing means **no ``Move`` is issued at all** and the core is told
to stop.  This is what makes "the vendor never receives a command past its TTL"
a structural property rather than a measurement: the soak's zero-violation
claim is checked against the applied timestamps, but it is *enforced* here.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .ports import SportPort


@dataclass(frozen=True)
class VendorWriteV1:
    writer_id: str
    vx_mps: float
    vy_mps: float
    vyaw_rad_s: float
    stop_epoch: int
    client_sequence: int
    deadline_monotonic_s: float
    submitted_at_monotonic_s: float


class VendorWriterV1:
    def __init__(
        self,
        sport: SportPort,
        *,
        stop_epoch_reader: Callable[[], int],
        on_refused: Callable[[VendorWriteV1, str], None],
        on_completed: Callable[[VendorWriteV1, float, BaseException | None], None],
        clock: Callable[[], float] = time.monotonic,
        idle_poll_s: float = 0.02,
    ) -> None:
        self._sport = sport
        self._stop_epoch_reader = stop_epoch_reader
        self._on_refused = on_refused
        self._on_completed = on_completed
        self._clock = clock
        self._idle_poll_s = idle_poll_s
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._pending: VendorWriteV1 | None = None
        self._in_flight_since: float | None = None
        self._thread: threading.Thread | None = None
        self._submitted = 0
        self._superseded = 0
        self._refused = 0
        self._applied = 0

    @property
    def submitted(self) -> int:
        with self._lock:
            return self._submitted

    @property
    def superseded(self) -> int:
        with self._lock:
            return self._superseded

    @property
    def refused(self) -> int:
        with self._lock:
            return self._refused

    @property
    def applied(self) -> int:
        with self._lock:
            return self._applied

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="m1-0-gateway-vendor-writer",
            daemon=True,
        )
        self._thread.start()

    def submit(self, write: VendorWriteV1) -> None:
        """Never blocks. The caller holds the core lock; this may not wait on I/O."""

        with self._lock:
            if self._pending is not None:
                self._superseded += 1
            self._pending = write
            self._submitted += 1
        self._wake.set()

    def in_flight_age_s(self, now: float) -> float:
        with self._lock:
            since = self._in_flight_since
        if since is None:
            return 0.0
        return max(0.0, now - since)

    def drop_pending(self) -> None:
        """Discard an unwritten setpoint. Called by the core on every stop."""

        with self._lock:
            self._pending = None

    def close(self, *, join_timeout_s: float = 0.5) -> None:
        self._closed.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            # A vendor call that never returns (GWF-009) must not be able to
            # hold the process open: the thread is a daemon and the join is
            # bounded.  The stop path never went through it.
            thread.join(timeout=join_timeout_s)

    def _run(self) -> None:
        while not self._closed.is_set():
            if not self._wake.wait(timeout=self._idle_poll_s):
                continue
            with self._lock:
                self._wake.clear()
                write = self._pending
                self._pending = None
                if write is not None:
                    self._in_flight_since = self._clock()
            if write is None:
                continue
            try:
                self._write_once(write)
            finally:
                with self._lock:
                    self._in_flight_since = None

    def _write_once(self, write: VendorWriteV1) -> None:
        if write.stop_epoch != self._stop_epoch_reader():
            with self._lock:
                self._refused += 1
            self._on_refused(write, "stop_dominance")
            return
        if self._clock() >= write.deadline_monotonic_s:
            with self._lock:
                self._refused += 1
            self._on_refused(write, "local_ttl_expired")
            return
        error: BaseException | None = None
        try:
            self._sport.move(
                writer_id=write.writer_id,
                vx_mps=write.vx_mps,
                vy_mps=write.vy_mps,
                vyaw_rad_s=write.vyaw_rad_s,
            )
        except BaseException as caught:
            # The vendor is a fault boundary: a raising Move is evidence, not a
            # crash, and it must reach the core as a stop cause.  Interpreter
            # shutdown (KeyboardInterrupt, SystemExit) is not a vendor fault
            # and is re-raised rather than silently turned into one.
            if not isinstance(caught, Exception):
                raise
            error = caught
        applied_at = self._clock()
        with self._lock:
            self._applied += 1
        self._on_completed(write, applied_at, error)
