"""ProposerBus + GoalArbiter (pure seam for hot-swappable SE2 goals)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.revision import CommittedRevisions


@dataclass(frozen=True)
class SE2Goal:
    source: str
    pose: tuple[float, float, float] | None  # x, y, yaw_rad
    waypoints: tuple[tuple[float, float], ...] = ()
    frame: str = "map"
    confidence: float = 1.0
    ttl_s: float = 2.0
    plan_step_id: str = ""
    issued_s: float = 0.0
    priority: int = 0
    #: The task and plan revision the proposal was authored under. Defaulting
    #: task_id="" / plan_revision=0 keeps every existing caller (and the
    #: navigation pipeline, which never stamps a revision) behaving exactly as
    #: before -- a proposal is stale only relative to a *committed* revision, and
    #: an uncommitted channel commits nothing. See ``parcel_robot.revision``.
    task_id: str = ""
    plan_revision: int = 0

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("SE2Goal.source must be non-empty")
        if self.pose is None and not self.waypoints:
            raise ValueError("SE2Goal requires pose or waypoints")
        if self.pose is not None and not all(math.isfinite(v) for v in self.pose):
            raise ValueError("pose must be finite")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if not math.isfinite(self.ttl_s) or self.ttl_s <= 0.0:
            raise ValueError("ttl_s must be finite and positive")
        if self.plan_revision < 0:
            raise ValueError("plan_revision must be a non-negative integer")

    def expired(self, now_s: float) -> bool:
        return float(now_s) - float(self.issued_s) > self.ttl_s

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "pose": list(self.pose) if self.pose is not None else None,
            "waypoints": [list(p) for p in self.waypoints],
            "frame": self.frame,
            "confidence": self.confidence,
            "ttl_s": self.ttl_s,
            "plan_step_id": self.plan_step_id,
            "issued_s": self.issued_s,
            "priority": self.priority,
            "task_id": self.task_id,
            "plan_revision": self.plan_revision,
        }


@dataclass
class ProposerBus:
    """Register async proposers; each emit is timestamped onto the bus.

    Carries a monotonic committed-revision ledger so the P0-C proposal-buffer
    flush lives here: :meth:`commit_revision` atomically drops every buffered
    proposal authored under a superseded revision, and :meth:`publish` /
    :meth:`poll` refuse to (re-)buffer a stale one afterwards. This makes the bus
    a ``parcel_robot.revision.RevisionSink`` the executive can flush in the same
    transaction as a correction's ``plan_revision`` bump.
    """

    _proposers: dict[str, Callable[..., SE2Goal | None]] = field(default_factory=dict)
    _latest: dict[str, SE2Goal] = field(default_factory=dict)
    _committed: CommittedRevisions = field(default_factory=CommittedRevisions)

    def register(self, source: str, proposer: Callable[..., SE2Goal | None]) -> None:
        if not source:
            raise ValueError("source must be non-empty")
        self._proposers[source] = proposer

    def publish(self, goal: SE2Goal) -> None:
        # Fail closed: a proposal older than the committed revision for its task
        # is never buffered, so it can never be handed to the arbiter -- this
        # also closes the window where an old-revision proposal is re-published
        # after a flush.
        if self._committed.is_stale(task_id=goal.task_id, plan_revision=goal.plan_revision):
            return
        self._latest[goal.source] = goal

    def poll(self, *, now_s: float, context: Mapping[str, Any] | None = None) -> tuple[SE2Goal, ...]:
        ctx = dict(context or {})
        for source, proposer in self._proposers.items():
            try:
                goal = proposer(now_s=now_s, **ctx)
            except TypeError:
                goal = proposer()
            if goal is None:
                continue
            if goal.source != source:
                goal = SE2Goal(
                    source=source,
                    pose=goal.pose,
                    waypoints=goal.waypoints,
                    frame=goal.frame,
                    confidence=goal.confidence,
                    ttl_s=goal.ttl_s,
                    plan_step_id=goal.plan_step_id,
                    issued_s=now_s,
                    priority=goal.priority,
                    task_id=goal.task_id,
                    plan_revision=goal.plan_revision,
                )
            elif goal.issued_s == 0.0:
                goal = SE2Goal(
                    source=goal.source,
                    pose=goal.pose,
                    waypoints=goal.waypoints,
                    frame=goal.frame,
                    confidence=goal.confidence,
                    ttl_s=goal.ttl_s,
                    plan_step_id=goal.plan_step_id,
                    issued_s=now_s,
                    priority=goal.priority,
                    task_id=goal.task_id,
                    plan_revision=goal.plan_revision,
                )
            if self._committed.is_stale(task_id=goal.task_id, plan_revision=goal.plan_revision):
                continue
            self._latest[source] = goal
        return tuple(self._latest.values())

    def commit_revision(self, *, task_id: str, plan_revision: int) -> int:
        """Commit a revision for a task and flush its now-stale buffered goals.

        Monotonic (never lowers a committed revision). Returns the resulting
        committed revision. Any buffered proposal authored under an older
        revision of ``task_id`` is dropped in this call, so there is no window in
        which it survives the correction.
        """

        committed = self._committed.commit(task_id=task_id, plan_revision=plan_revision)
        self._latest = {
            source: goal
            for source, goal in self._latest.items()
            if not self._committed.is_stale(
                task_id=goal.task_id, plan_revision=goal.plan_revision
            )
        }
        return committed

    def committed_revision(self, task_id: str = "") -> int:
        return self._committed.committed(task_id)

    def snapshot(self) -> dict[str, Any]:
        return {
            "sources": sorted(self._proposers),
            "latest": {key: goal.as_dict() for key, goal in sorted(self._latest.items())},
            "committed_revisions": self._committed.snapshot(),
        }


class GoalArbiter:
    """Resolve competing SE2 goals by plan-step ownership, priority, freshness.

    TTL-expired or lethal-cost goals are vetoed (AsyncShield staleness lesson).
    grid_v1 A* remains the sole consumer of the winner.
    """

    def __init__(
        self,
        *,
        lethal_cost: Callable[[float, float], bool] | None = None,
    ) -> None:
        self._lethal = lethal_cost or (lambda _x, _y: False)
        self._active_plan_step: str | None = None
        self._committed = CommittedRevisions()

    def set_plan_step(self, plan_step_id: str | None) -> None:
        self._active_plan_step = plan_step_id

    def commit_revision(self, *, task_id: str, plan_revision: int) -> int:
        """Commit a revision for a task so older proposals can never win.

        Monotonic (never lowers). The arbiter holds no buffer, so committing only
        raises the bar :meth:`resolve` rejects against; the paired
        :class:`ProposerBus` is what drops already-buffered stale goals.
        """

        return self._committed.commit(task_id=task_id, plan_revision=plan_revision)

    def committed_revision(self, task_id: str = "") -> int:
        return self._committed.committed(task_id)

    def resolve(
        self,
        goals: Sequence[SE2Goal],
        *,
        now_s: float,
    ) -> SE2Goal | None:
        viable: list[SE2Goal] = []
        for goal in goals:
            # P0-C: a proposal authored under a superseded revision can never
            # win, mirroring TaskExecutive.report()'s stale-revision-ignore. This
            # is additive to -- and never relaxes -- the TTL/lethal vetoes below.
            if self._committed.is_stale(
                task_id=goal.task_id, plan_revision=goal.plan_revision
            ):
                continue
            if goal.expired(now_s):
                continue
            pose = goal.pose
            if pose is not None and self._lethal(pose[0], pose[1]):
                continue
            if goal.waypoints and all(self._lethal(x, y) for x, y in goal.waypoints):
                continue
            viable.append(goal)
        if not viable:
            return None
        if self._active_plan_step:
            owned = [g for g in viable if g.plan_step_id == self._active_plan_step]
            if owned:
                viable = owned
        viable.sort(
            key=lambda g: (
                -int(g.priority),
                -float(g.confidence),
                -float(g.issued_s),
                g.source,
            )
        )
        return viable[0]
