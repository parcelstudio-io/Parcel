"""ProposerBus + GoalArbiter (pure seam for hot-swappable SE2 goals)."""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.core.arbiter import waypoints_trigger_lethal_veto
from parcel_robot.counterfactual import (
    ArbitrationCandidateV1,
    ArbitrationLogRecordV1,
    CounterfactualReportV1,
    build_arbitration_log,
    counterfactual_report,
)
from parcel_robot.revision import CommittedRevisions

#: Opt-in C-B arbitration candidate log at GoalArbiter.resolve commit.
#: Default off — observational measurement only; never changes selection.
ARBITRATION_LOG_ENV = "PARCEL_ARBITRATION_LOG"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


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

    When ``arbitration_log`` is enabled (constructor or ``PARCEL_ARBITRATION_LOG``),
    each :meth:`resolve` stamps a digest-backed ``ArbitrationLogRecordV1`` at the
    commit point for offline oracle replay. Selection is unchanged either way.
    """

    def __init__(
        self,
        *,
        lethal_cost: Callable[[float, float], bool] | None = None,
        arbitration_log: bool | None = None,
        episode_id: str = "unset",
    ) -> None:
        self._lethal = lethal_cost or (lambda _x, _y: False)
        self._active_plan_step: str | None = None
        self._committed = CommittedRevisions()
        self._arbitration_log_enabled = (
            bool(arbitration_log)
            if arbitration_log is not None
            else _env_flag(ARBITRATION_LOG_ENV)
        )
        if not episode_id or not str(episode_id).strip():
            raise ValueError("episode_id must be non-empty")
        self._episode_id = str(episode_id)
        self._log_seq = 0
        self._last_arbitration_log: ArbitrationLogRecordV1 | None = None
        self._last_counterfactual_report: CounterfactualReportV1 | None = None

    @property
    def arbitration_log_enabled(self) -> bool:
        return self._arbitration_log_enabled

    @property
    def last_arbitration_log(self) -> ArbitrationLogRecordV1 | None:
        return self._last_arbitration_log

    @property
    def last_counterfactual_report(self) -> CounterfactualReportV1 | None:
        return self._last_counterfactual_report

    def set_plan_step(self, plan_step_id: str | None) -> None:
        self._active_plan_step = plan_step_id

    def set_episode_id(self, episode_id: str) -> None:
        if not episode_id or not str(episode_id).strip():
            raise ValueError("episode_id must be non-empty")
        self._episode_id = str(episode_id)

    def commit_revision(self, *, task_id: str, plan_revision: int) -> int:
        """Commit a revision for a task so older proposals can never win.

        Monotonic (never lowers). The arbiter holds no buffer, so committing only
        raises the bar :meth:`resolve` rejects against; the paired
        :class:`ProposerBus` is what drops already-buffered stale goals.
        """

        return self._committed.commit(task_id=task_id, plan_revision=plan_revision)

    def committed_revision(self, task_id: str = "") -> int:
        return self._committed.committed(task_id)

    def report_counterfactual(
        self,
        oracle_success: Mapping[str, bool],
    ) -> CounterfactualReportV1:
        """Emit would-a-different-candidate-have-won for the last logged resolve.

        Requires a prior flag-on :meth:`resolve` that stamped
        :attr:`last_arbitration_log`.  Oracle labels never affect selection.
        """

        record = self._last_arbitration_log
        if record is None:
            raise RuntimeError(
                "no arbitration log; enable arbitration_log=True or "
                f"{ARBITRATION_LOG_ENV}=1 before resolve"
            )
        report = counterfactual_report(record, oracle_success=oracle_success)
        self._last_counterfactual_report = report
        return report

    def _veto_reason(self, goal: SE2Goal, now_s: float) -> str:
        if self._committed.is_stale(
            task_id=goal.task_id, plan_revision=goal.plan_revision
        ):
            return "stale_revision"
        if goal.expired(now_s):
            return "ttl"
        pose = goal.pose
        if pose is not None and self._lethal(pose[0], pose[1]):
            return "lethal"
        # S-B / verdict arbiter mixed-lethal harden: any lethal waypoint vetoes
        # (old all() let mixed safe/lethal waypoint goals through).
        if waypoints_trigger_lethal_veto(self._lethal, goal.waypoints):
            return "lethal"
        return ""

    def _candidate_from_goal(
        self,
        goal: SE2Goal,
        *,
        admissible: bool,
        veto_reason: str,
    ) -> ArbitrationCandidateV1:
        return ArbitrationCandidateV1(
            candidate_id=goal.source,
            source=goal.source,
            priority=int(goal.priority),
            confidence=float(goal.confidence),
            issued_s=float(goal.issued_s),
            pose_xyyaw=goal.pose,
            waypoints_xy=tuple(goal.waypoints),
            plan_step_id=str(goal.plan_step_id),
            task_id=str(goal.task_id),
            plan_revision=int(goal.plan_revision),
            admissible=admissible,
            veto_reason=veto_reason,
        )

    def _stamp_arbitration_log(
        self,
        goals: Sequence[SE2Goal],
        *,
        now_s: float,
        winner: SE2Goal | None,
    ) -> ArbitrationLogRecordV1:
        candidates = []
        for goal in goals:
            reason = self._veto_reason(goal, now_s)
            candidates.append(
                self._candidate_from_goal(
                    goal,
                    admissible=not reason,
                    veto_reason=reason,
                )
            )
        self._log_seq += 1
        record = build_arbitration_log(
            record_id=f"{self._episode_id}:{self._log_seq}",
            episode_id=self._episode_id,
            decision_monotonic_ns=time.monotonic_ns(),
            candidates=candidates,
            committed_candidate_id=None if winner is None else winner.source,
            active_plan_step=self._active_plan_step or "",
        )
        self._last_arbitration_log = record
        return record

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
            if self._veto_reason(goal, now_s):
                continue
            viable.append(goal)
        winner: SE2Goal | None
        if not viable:
            winner = None
        else:
            pool = viable
            if self._active_plan_step:
                owned = [g for g in pool if g.plan_step_id == self._active_plan_step]
                if owned:
                    pool = owned
            pool.sort(
                key=lambda g: (
                    -int(g.priority),
                    -float(g.confidence),
                    -float(g.issued_s),
                    g.source,
                )
            )
            winner = pool[0]
        if self._arbitration_log_enabled:
            self._stamp_arbitration_log(goals, now_s=now_s, winner=winner)
        return winner
