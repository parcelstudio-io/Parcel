"""The bounded local audit ring (HLD §8.8).

Two properties matter more than what it stores.

1.  **It is bounded.**  Fixed capacity, oldest record discarded first, drops
    counted.  A gateway whose evidence buffer can grow is a gateway that can
    be stopped by a full disk or a slow reader.

2.  **It is never on the stop path.**  ``record`` appends under a short lock
    and calls nothing.  There is no observer callback, no serialization and no
    I/O inside it, so a raising or blocking evidence consumer cannot exist in
    the first place: an exporter (see ``gateway/process.py``) *pulls* with
    :meth:`drain` from its own daemon thread.  ``record`` additionally cannot
    raise — a malformed detail value is coerced and counted, because a
    ``TypeError`` from a log line must never become a missing StopMove.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from .limits import AUDIT_RING_CAPACITY

#: Bounds on one record, so a single entry can never be unbounded either.
MAX_DETAIL_PAIRS = 16
MAX_DETAIL_CHARS = 200


@dataclass(frozen=True)
class AuditRecordV1:
    index: int
    at_monotonic_s: float
    event: str
    boot_epoch: str
    phase: str
    detail: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, object]:
        record: dict[str, object] = {
            "index": self.index,
            "at_monotonic_s": self.at_monotonic_s,
            "event": self.event,
            "boot_epoch": self.boot_epoch,
            "phase": self.phase,
        }
        record.update(dict(self.detail))
        return record


class BoundedAuditRingV1:
    def __init__(
        self,
        *,
        capacity: int = AUDIT_RING_CAPACITY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("audit ring capacity must be a positive integer")
        self._clock = clock
        self._lock = threading.Lock()
        self._records: deque[AuditRecordV1] = deque(maxlen=capacity)
        self._capacity = capacity
        self._total = 0
        self._dropped = 0
        self._coerced = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def total_records(self) -> int:
        with self._lock:
            return self._total

    @property
    def dropped_records(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def coerced_details(self) -> int:
        with self._lock:
            return self._coerced

    def record(self, event: str, *, boot_epoch: str, phase: str, **detail: object) -> None:
        """Append one record. Never raises, never blocks on anything but its own lock."""

        pairs: list[tuple[str, str]] = []
        coerced = 0
        for key, value in list(detail.items())[:MAX_DETAIL_PAIRS]:
            try:
                rendered = value if isinstance(value, str) else repr(value)
            except BaseException as caught:
                # A ``__repr__`` that raises must never break a stop.  The
                # catch is deliberately wide and deliberately not total:
                # KeyboardInterrupt and SystemExit are not detail-rendering
                # failures and are re-raised untouched.
                if not isinstance(caught, Exception):
                    raise
                rendered = "<unrenderable>"
                coerced += 1
            if len(rendered) > MAX_DETAIL_CHARS:
                rendered = rendered[:MAX_DETAIL_CHARS]
                coerced += 1
            pairs.append((str(key)[:MAX_DETAIL_CHARS], rendered))
        with self._lock:
            self._total += 1
            self._coerced += coerced
            if len(self._records) == self._capacity:
                self._dropped += 1
            self._records.append(
                AuditRecordV1(
                    index=self._total,
                    at_monotonic_s=self._clock(),
                    event=str(event)[:MAX_DETAIL_CHARS],
                    boot_epoch=boot_epoch,
                    phase=phase,
                    detail=tuple(pairs),
                )
            )

    def snapshot(self) -> tuple[AuditRecordV1, ...]:
        with self._lock:
            return tuple(self._records)

    def drain(self) -> tuple[AuditRecordV1, ...]:
        with self._lock:
            drained = tuple(self._records)
            self._records.clear()
            return drained

    def events(self, name: str) -> tuple[AuditRecordV1, ...]:
        return tuple(record for record in self.snapshot() if record.event == name)
