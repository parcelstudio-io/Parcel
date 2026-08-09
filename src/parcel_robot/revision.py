"""Revision / channel-epoch key type binding proposer buffers to the executive's
committed ``plan_revision`` (P0-C proposal-buffer flush).

Pure leaf: stdlib + typing only, so both the brain executive
(``parcel_robot.brain.executive``) and the instructnav proposer/arbiter
(``parcel_robot.instructnav.arbiter``) can share it without an import cycle.
Neither package ``__init__`` is dragged in beyond the trivial top-level package,
which is the reason this lives at the top level rather than under ``brain`` or
``core`` (both of those transitively import ``navigation``, which imports
``instructnav.arbiter`` -- so importing them from the arbiter would loop).

The defect this closes: when the owner corrects a mission ("no, the other
lamppost") the executive increments ``plan_revision`` and invalidates the old
plan, but ``SE2Goal`` proposals already sitting in ``ProposerBus`` /
``GoalArbiter`` from the OLD revision were never flushed, so a stale proposal
could still win arbitration and briefly steer the body toward the abandoned
target before the new plan's proposals arrive. This mirrors
``TaskExecutive.report()``'s existing stale-revision-ignore discipline down into
the learned-goal buffers, and lets the executive flush them in the same
transaction as the revision bump.
"""

from __future__ import annotations

from typing import Protocol

#: A plan revision is a strictly-increasing integer per task
#: (``TaskExecutive.replace`` enforces the monotonicity). Larger == newer; a
#: revision strictly smaller than what is committed for its task is stale and can
#: never win arbitration.
PlanRevision = int


class RevisionSink(Protocol):
    """A proposer buffer the executive can flush when a new revision commits.

    ``ProposerBus`` and ``GoalArbiter`` satisfy this structurally -- neither has
    to import this module. The executive holds registered sinks opaquely and, on
    committing a strictly newer ``plan_revision`` for a task, calls this for every
    sink inside the SAME locked transaction as the record's revision bump, so no
    proposal authored under an older revision survives the correction window.
    """

    def commit_revision(self, *, task_id: str, plan_revision: int) -> None: ...


class CommittedRevisions:
    """Monotonic, per-task ledger of the committed plan_revision (fail-closed).

    The single source of the "older than committed == stale" rule shared by the
    proposer buffer and the goal arbiter. Not internally locked: the proposer
    bus / goal arbiter run single-threaded behind the navigator, and the
    executive touches sinks only under its own lock.
    """

    __slots__ = ("_committed",)

    def __init__(self) -> None:
        self._committed: dict[str, int] = {}

    def committed(self, task_id: str) -> int:
        """Highest revision committed for ``task_id`` (0 if never committed)."""

        return self._committed.get(str(task_id), 0)

    def commit(self, *, task_id: str, plan_revision: int) -> int:
        """Raise the committed revision for a task; never lowers it.

        Returns the resulting committed revision.
        """

        key = str(task_id)
        nxt = max(self._committed.get(key, 0), int(plan_revision))
        self._committed[key] = nxt
        return nxt

    def is_stale(self, *, task_id: str, plan_revision: int) -> bool:
        """True iff a proposal is older than what is committed for its task.

        A stale proposal must never be buffered nor win arbitration.
        """

        return int(plan_revision) < self._committed.get(str(task_id), 0)

    def snapshot(self) -> dict[str, int]:
        return dict(self._committed)
