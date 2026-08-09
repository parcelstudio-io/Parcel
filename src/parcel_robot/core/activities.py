from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from parcel_robot.models import ActionProposal


@dataclass(frozen=True)
class ActivityContext:
    emergency_stopped: bool = False
    active_source: str | None = None
    navigation_active: bool = False
    follow_active: bool = False
    physical_activity_active: bool = False

    @property
    def busy_reason(self) -> str | None:
        if self.emergency_stopped:
            return "emergency_stop"
        if self.active_source == "manual":
            return "manual_control"
        if self.navigation_active or self.active_source == "navigation":
            return "navigation"
        if self.follow_active or self.active_source == "follow":
            return "owner_follow"
        if self.active_source is not None:
            return f"{self.active_source}_motion"
        if self.physical_activity_active:
            return "physical_activity"
        return None


@dataclass
class ActivityRecord:
    activity_id: int
    proposal: ActionProposal
    created_at: float
    expires_at: float
    status: str = "queued"
    disposition: str = "defer"
    detail: str = ""
    started_at: float | None = None
    completed_at: float | None = None

    def snapshot(self) -> dict[str, object]:
        return {
            "id": self.activity_id,
            "kind": self.proposal.kind,
            "name": self.proposal.name,
            "trigger": self.proposal.trigger,
            "status": self.status,
            "disposition": self.disposition,
            "detail": self.detail,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class ActivitySubmission:
    accepted: bool
    disposition: str
    message: str
    activity_id: int | None = None


@dataclass
class ActivityCoordinator:
    """Queues semantic gestures without granting a model motor authority."""

    proposal_ttl_s: float = 20.0
    cooldown_s: float = 8.0
    max_pending: int = 8
    _pending: deque[ActivityRecord] = field(default_factory=deque, init=False)
    _running: ActivityRecord | None = field(default=None, init=False)
    _recent: deque[ActivityRecord] = field(default_factory=lambda: deque(maxlen=20), init=False)
    _last_started: dict[str, float] = field(default_factory=dict, init=False)
    _next_id: int = field(default=0, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def __post_init__(self) -> None:
        values = (self.proposal_ttl_s, self.cooldown_s)
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("activity timing values must be finite and non-negative")
        if self.max_pending <= 0:
            raise ValueError("activity max_pending must be positive")

    def submit(
        self,
        proposal: ActionProposal,
        context: ActivityContext,
        *,
        now: float | None = None,
    ) -> ActivitySubmission:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            self._expire(current_time)
            if context.emergency_stopped:
                return ActivitySubmission(False, "reject", "Rejected during emergency stop")
            busy = context.busy_reason
            if proposal.trigger == "conversation_reaction" and busy is not None:
                return ActivitySubmission(
                    False,
                    "skip",
                    f"Reaction skipped while {busy} is active",
                )
            last_started = self._last_started.get(proposal.name)
            if last_started is not None and current_time - last_started < self.cooldown_s:
                return ActivitySubmission(False, "reject", "Gesture is cooling down")
            if self._running and self._running.proposal.name == proposal.name:
                return ActivitySubmission(False, "reject", "Gesture is already running")
            if any(item.proposal.name == proposal.name for item in self._pending):
                return ActivitySubmission(False, "reject", "Gesture is already queued")
            if len(self._pending) >= self.max_pending:
                return ActivitySubmission(False, "reject", "Gesture queue is full")

            self._next_id += 1
            ttl_s = (
                min(self.proposal_ttl_s, 2.0)
                if proposal.trigger == "conversation_reaction"
                else self.proposal_ttl_s
            )
            record = ActivityRecord(
                activity_id=self._next_id,
                proposal=proposal,
                created_at=current_time,
                expires_at=current_time + ttl_s,
                disposition="execute" if busy is None else "defer",
                detail="ready" if busy is None else f"waiting_for_{busy}",
            )
            self._pending.append(record)
            if busy is None:
                message = f"Accepted {proposal.name} for the next control tick"
            else:
                message = f"Deferred {proposal.name} while {busy} is active"
            return ActivitySubmission(True, record.disposition, message, record.activity_id)

    def start_ready(
        self,
        context: ActivityContext,
        *,
        now: float | None = None,
    ) -> ActivityRecord | None:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            self._expire(current_time)
            if self._running is not None or context.busy_reason is not None:
                return None
            if not self._pending:
                return None
            record = self._pending.popleft()
            record.status = "running"
            record.disposition = "execute"
            record.detail = "executing"
            record.started_at = current_time
            self._last_started[record.proposal.name] = current_time
            self._running = record
            return record

    def finish(
        self,
        *,
        success: bool,
        detail: str,
        now: float | None = None,
    ) -> ActivityRecord | None:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            record = self._running
            if record is None:
                return None
            record.status = "completed" if success else "cancelled"
            record.detail = detail
            record.completed_at = current_time
            self._recent.append(record)
            self._running = None
            return record

    def running(self) -> ActivityRecord | None:
        with self._lock:
            return self._running

    def clear(self, detail: str = "cleared") -> None:
        with self._lock:
            while self._pending:
                record = self._pending.popleft()
                record.status = "cancelled"
                record.detail = detail
                record.completed_at = time.monotonic()
                self._recent.append(record)
            if self._running is not None:
                self._running.status = "cancelled"
                self._running.detail = detail
                self._running.completed_at = time.monotonic()
                self._recent.append(self._running)
                self._running = None

    def snapshot(self, *, now: float | None = None) -> dict[str, object]:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            self._expire(current_time)
            return {
                "running": self._running.snapshot() if self._running else None,
                "pending": [record.snapshot() for record in self._pending],
                "recent": [record.snapshot() for record in self._recent],
            }

    def _expire(self, now: float) -> None:
        retained: deque[ActivityRecord] = deque()
        while self._pending:
            record = self._pending.popleft()
            if now >= record.expires_at:
                record.status = "expired"
                record.detail = "proposal_ttl_elapsed"
                record.completed_at = now
                self._recent.append(record)
            else:
                retained.append(record)
        self._pending = retained
