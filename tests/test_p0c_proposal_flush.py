"""P0-C: atomic proposal-buffer flush on a plan_revision correction.

Defect: when the owner corrects a mission ("no, the other lamppost") the
executive increments plan_revision and invalidates the old plan, but stale
``SE2Goal`` proposals already sitting in ``ProposerBus`` / ``GoalArbiter`` from
the OLD revision were not flushed -- so a superseded-revision proposal could
still win arbitration and briefly steer the body toward the abandoned target.

These tests prove: (a) a stale proposal is REJECTED by ``GoalArbiter`` after the
new revision commits; (b) the proposer buffer is flushed the instant ``replace``
activates; (c) a fresh proposal at the new revision wins normally; and that the
existing TTL/lethal veto and suspend/resume semantics are unchanged.
"""

from __future__ import annotations

from parcel_robot.brain import (
    ExecutionResult,
    GoalSpec,
    GoalTarget,
    PlanIR,
    PlanStep,
    PlanValidator,
    SkillContractRegistry,
    SuccessCondition,
    TaskExecutive,
    VerifiedFact,
)
from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus, SE2Goal
from parcel_robot.revision import CommittedRevisions


# --------------------------------------------------------------------------- #
# Fixtures mirroring tests/test_brain_executive.py (kept local, minimal).
# --------------------------------------------------------------------------- #
def _hold_plan(task_id: str, *, revision: int = 1) -> PlanIR:
    return PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=revision,
        source_turn_id=f"turn-{task_id}-{revision}",
        goal=GoalSpec("hold", GoalTarget("current_pose"), 0.0),
        invariants=("keep_collision_margin",),
        steps=(
            PlanStep(
                "hold",
                "Hold",
                {},
                ("base_available",),
                SuccessCondition("motion_stopped"),
                5.0,
                1,
                (),
                ("base",),
                "checkpoint",
            ),
        ),
    )


def _validated(plan: PlanIR):
    registry = SkillContractRegistry.default(pose_names=("sit",))
    return PlanValidator(registry).validate(plan)


def _hold_result(request, status: str, *, checkpoint: bool = True) -> ExecutionResult:
    terminal = status != "in_progress"
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status=status,
        feedback_code=status,
        snapshot_id="snapshot-p0c",
        verified_facts=(
            (VerifiedFact("motion_stopped", None, "controller", 1.0),)
            if status == "succeeded"
            else ()
        ),
        checkpoint=checkpoint,
        detail_code=status,
        started_at_monotonic_s=10.0,
        finished_at_monotonic_s=11.0 if terminal else None,
    )


def _goal(task_id: str, revision: int, *, x: float = 1.0, source: str = "grounder") -> SE2Goal:
    return SE2Goal(
        source=source,
        pose=(x, 0.0, 0.0),
        confidence=1.0,
        ttl_s=5.0,
        plan_step_id="align_then_translate",
        issued_s=9.0,
        priority=10,
        task_id=task_id,
        plan_revision=revision,
    )


# --------------------------------------------------------------------------- #
# 1. Pure ledger.
# --------------------------------------------------------------------------- #
def test_committed_revisions_is_monotonic_and_fail_closed() -> None:
    ledger = CommittedRevisions()
    assert ledger.committed("nav") == 0
    assert not ledger.is_stale(task_id="nav", plan_revision=0)

    assert ledger.commit(task_id="nav", plan_revision=2) == 2
    assert ledger.is_stale(task_id="nav", plan_revision=1)
    assert not ledger.is_stale(task_id="nav", plan_revision=2)
    # never lowers, and is keyed per task
    assert ledger.commit(task_id="nav", plan_revision=1) == 2
    assert ledger.committed("other") == 0
    assert not ledger.is_stale(task_id="other", plan_revision=1)


# --------------------------------------------------------------------------- #
# 2. GoalArbiter revision gate (gate a + c) and veto semantics unchanged.
# --------------------------------------------------------------------------- #
def test_goal_arbiter_rejects_stale_revision_and_accepts_fresh() -> None:
    arbiter = GoalArbiter()
    stale = _goal("nav", 1, x=1.0)
    fresh = _goal("nav", 2, x=2.0)

    # Before any commit both are viable (backward-compatible / no gate engaged).
    assert arbiter.resolve((stale,), now_s=10.0) is stale

    # Correction commits revision 2 for the nav channel.
    assert arbiter.commit_revision(task_id="nav", plan_revision=2) == 2

    # (a) The old-revision proposal can never win.
    assert arbiter.resolve((stale,), now_s=10.0) is None
    # Even head-to-head against the fresh one it is rejected outright.
    assert arbiter.resolve((stale, fresh), now_s=10.0) is fresh
    # (c) A fresh proposal at the new revision wins normally.
    assert arbiter.resolve((fresh,), now_s=10.0) is fresh
    assert arbiter.committed_revision("nav") == 2


def test_stale_rejection_is_additive_to_ttl_and_lethal_vetoes() -> None:
    # Reproduce the shipped veto test verbatim with a default (uncommitted)
    # arbiter: the new revision gate must not touch TTL/lethal semantics.
    arbiter = GoalArbiter(lethal_cost=lambda x, y: x > 9.0)
    now = 10.0
    goals = [
        SE2Goal(source="a", pose=(1.0, 0.0, 0.0), priority=1, issued_s=9.0, ttl_s=2.0),
        SE2Goal(source="b", pose=(2.0, 0.0, 0.0), priority=5, issued_s=9.5, ttl_s=2.0),
        SE2Goal(source="stale", pose=(0.0, 0.0, 0.0), priority=9, issued_s=0.0, ttl_s=1.0),
        SE2Goal(source="lethal", pose=(10.0, 0.0, 0.0), priority=9, issued_s=9.0, ttl_s=2.0),
    ]
    assert arbiter.resolve(goals, now_s=now).source == "b"

    # Committing a revision must not relax a lethal veto: a fresh-revision but
    # lethal goal is still vetoed (fail-closed).
    arbiter.commit_revision(task_id="nav", plan_revision=1)
    lethal_fresh = SE2Goal(
        source="lethal_fresh",
        pose=(10.0, 0.0, 0.0),
        priority=9,
        issued_s=9.0,
        ttl_s=2.0,
        task_id="nav",
        plan_revision=1,
    )
    assert arbiter.resolve((lethal_fresh,), now_s=now) is None
    # S-B harden: mixed lethal/non-lethal waypoints fail closed (any() veto).
    mixed = SE2Goal(
        source="mixed",
        pose=None,
        waypoints=((10.0, 0.0), (1.0, 0.0)),
        issued_s=9.0,
        ttl_s=2.0,
        task_id="nav",
        plan_revision=1,
    )
    assert arbiter.resolve((mixed,), now_s=now) is None


# --------------------------------------------------------------------------- #
# 3. ProposerBus flush (gate b) + fail-closed re-publish.
# --------------------------------------------------------------------------- #
def test_proposer_bus_commit_flushes_stale_and_blocks_restale() -> None:
    bus = ProposerBus()
    bus.publish(_goal("nav", 1))
    assert "grounder" in bus.snapshot()["latest"]

    # (b) committing the new revision flushes the buffered old-revision proposal.
    assert bus.commit_revision(task_id="nav", plan_revision=2) == 2
    assert bus.snapshot()["latest"] == {}
    assert bus.committed_revision("nav") == 2

    # fail-closed: an old-revision proposal re-published after the flush is
    # never buffered again.
    bus.publish(_goal("nav", 1))
    assert bus.snapshot()["latest"] == {}

    # (c) a fresh proposal at the new revision is buffered normally.
    fresh = _goal("nav", 2, x=2.0)
    bus.publish(fresh)
    assert bus.snapshot()["latest"]["grounder"]["plan_revision"] == 2


def test_proposer_bus_poll_drops_stale_emissions() -> None:
    bus = ProposerBus()
    bus.commit_revision(task_id="nav", plan_revision=2)
    bus.register("grounder", lambda *, now_s, **_: _goal("nav", 1, source="grounder"))
    assert bus.poll(now_s=10.0) == ()
    assert bus.snapshot()["latest"] == {}


# --------------------------------------------------------------------------- #
# 4. Product-shaped correction: executive flushes both sinks atomically.
# --------------------------------------------------------------------------- #
def test_executive_replace_flushes_proposer_buffers_immediately() -> None:
    bus = ProposerBus()
    arbiter = GoalArbiter()
    executive = TaskExecutive(revision_sinks=(bus, arbiter))

    # A nav task at revision 1 with a stale grounder proposal already buffered
    # toward the old target (queued, so replace activates immediately).
    executive.submit(_validated(_hold_plan("nav", revision=1)))
    stale = _goal("nav", 1, x=1.0)
    bus.publish(stale)
    assert "grounder" in bus.snapshot()["latest"]

    # "no, the other lamppost": correction commits revision 2.
    submission = executive.replace(_validated(_hold_plan("nav", revision=2)))
    assert submission.accepted and submission.disposition == "queued"

    # (b) the buffer is flushed the instant the replacement activates.
    assert bus.snapshot()["latest"] == {}
    assert bus.committed_revision("nav") == 2
    assert arbiter.committed_revision("nav") == 2
    # (a) the stale proposal can never win arbitration.
    assert arbiter.resolve((stale,), now_s=10.0) is None
    # (c) a fresh proposal at the new revision wins.
    fresh = _goal("nav", 2, x=2.0)
    assert arbiter.resolve((fresh,), now_s=10.0) is fresh


def test_executive_checkpoint_replacement_flushes_buffers() -> None:
    """The deferred correction path (running task -> defer -> checkpoint)."""

    bus = ProposerBus()
    arbiter = GoalArbiter()
    executive = TaskExecutive(revision_sinks=(bus, arbiter))

    executive.submit(_validated(_hold_plan("nav", revision=1)))
    request = executive.tick(now=10.0)[0]  # task now running, not at checkpoint
    bus.publish(_goal("nav", 1))

    deferred = executive.replace(_validated(_hold_plan("nav", revision=2)))
    assert deferred.disposition == "defer"
    # Still the old revision -- the running plan is not yet superseded, so the
    # buffer must NOT be flushed during the defer window.
    assert bus.committed_revision("nav") == 0
    assert "grounder" in bus.snapshot()["latest"]

    disposition = executive.report(_hold_result(request, "in_progress", checkpoint=True))
    assert disposition.action == "replacement_activated_at_checkpoint"
    # Now the replacement has committed: buffers flushed atomically.
    assert bus.committed_revision("nav") == 2
    assert bus.snapshot()["latest"] == {}
    assert arbiter.resolve((_goal("nav", 1),), now_s=10.0) is None


# --------------------------------------------------------------------------- #
# 5. No regression to suspend/resume: the flush fires ONLY on a correction.
# --------------------------------------------------------------------------- #
def test_suspend_resume_does_not_flush_or_bump_revision() -> None:
    bus = ProposerBus()
    arbiter = GoalArbiter()
    executive = TaskExecutive(revision_sinks=(bus, arbiter))

    executive.submit(_validated(_hold_plan("nav", revision=1)))
    request = executive.tick(now=10.0)[0]
    bus.publish(_goal("nav", 1))

    suspended = executive.suspend_task(request.task_id, reason="owner summons")
    assert suspended.state == "suspended"
    resumed = executive.resume_task(request.task_id, reason="summons_done")
    assert resumed.state == "queued"

    # No spurious flush: revision unchanged and the (still-valid) proposal
    # survives across a pause/resume cycle.
    assert bus.committed_revision("nav") == 0
    assert arbiter.committed_revision("nav") == 0
    assert "grounder" in bus.snapshot()["latest"]

    again = executive.tick(now=11.0)
    assert again[0].task_id == request.task_id


def test_registered_sink_must_expose_commit_revision() -> None:
    executive = TaskExecutive()
    try:
        executive.register_revision_sink(object())  # type: ignore[arg-type]
    except TypeError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected TypeError for a sink without commit_revision")

    # A structural RevisionSink is accepted and deduped by identity.
    bus = ProposerBus()
    assert hasattr(bus, "commit_revision")
    executive.register_revision_sink(bus)
    executive.register_revision_sink(bus)
