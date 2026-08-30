from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from parcel_robot.brain.contracts import (
    ExecutionResult,
    GoalSpec,
    GoalTarget,
    PlanIR,
    PlanStep,
    SuccessCondition,
    VerifiedFact,
)
from parcel_robot.brain.executive import DispatchRequest, TaskExecutive
from parcel_robot.brain.validator import PlanValidator


class _InjectableRevisionSink:
    def __init__(self, *, fail_revision: int | None = None) -> None:
        self._lock = threading.RLock()
        self.committed: dict[str, int] = {"task": 1}
        self.fail_revision = fail_revision

    def commit_revision(self, *, task_id: str, plan_revision: int) -> None:
        with self._lock:
            self.committed[task_id] = plan_revision
            if plan_revision == self.fail_revision:
                raise RuntimeError("injected revision sink failure")

    def revision_transaction_acquire(self) -> None:
        self._lock.acquire()

    def revision_transaction_release(self) -> None:
        self._lock.release()

    def revision_transaction_snapshot(self) -> object:
        return dict(self.committed)

    def revision_transaction_restore(self, state: object) -> None:
        self.committed = dict(state)  # type: ignore[arg-type]


class _BlockingFailureSink(_InjectableRevisionSink):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.allow_failure = threading.Event()

    def commit_revision(self, *, task_id: str, plan_revision: int) -> None:
        with self._lock:
            self.committed[task_id] = plan_revision
            self.entered.set()
            if not self.allow_failure.wait(timeout=5.0):
                raise TimeoutError("test did not release the injected sink")
            raise RuntimeError("injected isolated revision failure")


class _OrderingSink(_InjectableRevisionSink):
    def __init__(self, label: str, acquisitions: list[str]) -> None:
        super().__init__()
        self.label = label
        self.acquisitions = acquisitions

    def revision_transaction_acquire(self) -> None:
        super().revision_transaction_acquire()
        self.acquisitions.append(self.label)


def _validated(revision: int):
    plan = PlanIR(
        schema_version=1,
        task_id="task",
        plan_revision=revision,
        source_turn_id=f"turn-{revision}",
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
    return PlanValidator().validate(plan)


def _result(
    request: DispatchRequest,
    *,
    status: str,
    checkpoint: bool,
) -> ExecutionResult:
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status=status,
        feedback_code=status,
        snapshot_id="revision-atomicity-snapshot",
        verified_facts=(
            (VerifiedFact("motion_stopped", None, "controller", 1.0),)
            if status == "succeeded"
            else ()
        ),
        checkpoint=checkpoint,
        detail_code=f"test_{status}",
        started_at_monotonic_s=10.0,
        finished_at_monotonic_s=11.0 if status != "in_progress" else None,
    )


@pytest.mark.parametrize(
    "failing_index",
    (0, 1),
    ids=("first_sink", "second_sink"),
)
def test_revision_sink_failure_rolls_back_every_participant(failing_index: int) -> None:
    sinks = [_InjectableRevisionSink(), _InjectableRevisionSink()]
    sinks[failing_index].fail_revision = 2
    executive = TaskExecutive(revision_sinks=sinks)
    executive.submit(_validated(1))
    task_before = executive.snapshot()["tasks"]
    journal_before = executive.read_transition_journal(after_sequence=0)

    with pytest.raises(RuntimeError, match="injected revision sink failure"):
        executive.replace(_validated(2))

    assert executive.snapshot()["tasks"] == task_before
    assert executive.read_transition_journal(after_sequence=0) == journal_before
    assert [sink.committed for sink in sinks] == [{"task": 1}, {"task": 1}]

    sinks[failing_index].fail_revision = None
    accepted = executive.replace(_validated(2))
    assert accepted.accepted and accepted.plan_revision == 2
    assert [sink.committed for sink in sinks] == [{"task": 2}, {"task": 2}]


def test_revision_journal_failure_rolls_back_record_and_sinks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinks = [_InjectableRevisionSink(), _InjectableRevisionSink()]
    executive = TaskExecutive(revision_sinks=sinks)
    executive.submit(_validated(1))
    task_before = executive.snapshot()["tasks"]
    journal_before = executive.read_transition_journal(after_sequence=0)
    journal = executive._executive_journal
    original: Callable[..., object] = journal.append

    def append_then_fail(*args: object, **kwargs: object) -> object:
        transition = original(*args, **kwargs)
        if kwargs.get("family") == "replacement":
            raise RuntimeError("injected journal failure")
        return transition

    monkeypatch.setattr(journal, "append", append_then_fail)
    with pytest.raises(RuntimeError, match="injected journal failure"):
        executive.replace(_validated(2))

    assert executive.snapshot()["tasks"] == task_before
    assert executive.read_transition_journal(after_sequence=0) == journal_before
    assert [sink.committed for sink in sinks] == [{"task": 1}, {"task": 1}]


@pytest.mark.parametrize(
    ("status", "checkpoint", "expected_action"),
    (
        ("in_progress", True, "replacement_activated_at_checkpoint"),
        ("succeeded", True, "replacement_activated_after_step"),
    ),
    ids=("checkpoint", "after_step"),
)
def test_deferred_revision_journal_failure_restores_pre_report_state(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    checkpoint: bool,
    expected_action: str,
) -> None:
    sinks = [_InjectableRevisionSink(), _InjectableRevisionSink()]
    executive = TaskExecutive(revision_sinks=sinks)
    executive.submit(_validated(1))
    request = executive.tick(now=10.0)[0]
    assert executive.replace(_validated(2)).disposition == "defer"
    task_before = executive.snapshot()["tasks"]
    leases_before = executive.resources.leases()
    journal_before = executive.read_transition_journal(after_sequence=0)
    journal = executive._executive_journal
    original: Callable[..., object] = journal.append
    inject_failure = True

    def append_then_fail(*args: object, **kwargs: object) -> object:
        transition = original(*args, **kwargs)
        if inject_failure and kwargs.get("family") == "replacement":
            raise RuntimeError("injected deferred journal failure")
        return transition

    monkeypatch.setattr(journal, "append", append_then_fail)
    result = _result(request, status=status, checkpoint=checkpoint)
    with pytest.raises(RuntimeError, match="injected deferred journal failure"):
        executive.report(result)

    assert executive.snapshot()["tasks"] == task_before
    assert executive.resources.leases() == leases_before
    assert executive.read_transition_journal(after_sequence=0) == journal_before
    assert [sink.committed for sink in sinks] == [{"task": 1}, {"task": 1}]

    inject_failure = False
    disposition = executive.report(result)
    assert disposition.action == expected_action
    assert executive.snapshot()["tasks"][0]["plan_revision"] == 2
    assert executive.resources.leases() == ()
    assert [sink.committed for sink in sinks] == [{"task": 2}, {"task": 2}]


def test_failed_revision_is_isolated_from_concurrent_publish_and_resolve() -> None:
    from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus, SE2Goal

    bus = ProposerBus()
    arbiter = GoalArbiter()
    failure = _BlockingFailureSink()
    old_goal = SE2Goal(
        source="old",
        pose=(1.0, 0.0, 0.0),
        task_id="task",
        plan_revision=1,
        issued_s=1.0,
    )
    concurrent_goal = SE2Goal(
        source="concurrent",
        pose=(2.0, 0.0, 0.0),
        task_id="task",
        plan_revision=1,
        issued_s=1.1,
    )
    bus.publish(old_goal)
    executive = TaskExecutive(revision_sinks=(bus, arbiter, failure))
    executive.submit(_validated(1))

    replace_errors: list[RuntimeError] = []

    def replace() -> None:
        try:
            executive.replace(_validated(2))
        except RuntimeError as error:
            replace_errors.append(error)

    replacement = threading.Thread(target=replace)
    replacement.start()
    assert failure.entered.wait(timeout=2.0)

    publish_started = threading.Event()
    publish_done = threading.Event()
    resolve_started = threading.Event()
    resolve_done = threading.Event()
    winners: list[SE2Goal | None] = []

    def publish() -> None:
        publish_started.set()
        bus.publish(concurrent_goal)
        publish_done.set()

    def resolve() -> None:
        resolve_started.set()
        winners.append(arbiter.resolve((old_goal,), now_s=1.2))
        resolve_done.set()

    publisher = threading.Thread(target=publish)
    resolver = threading.Thread(target=resolve)
    publisher.start()
    resolver.start()
    assert publish_started.wait(timeout=1.0)
    assert resolve_started.wait(timeout=1.0)
    assert not publish_done.wait(timeout=0.05)
    assert not resolve_done.wait(timeout=0.05)

    failure.allow_failure.set()
    replacement.join(timeout=2.0)
    publisher.join(timeout=2.0)
    resolver.join(timeout=2.0)
    assert not replacement.is_alive()
    assert not publisher.is_alive()
    assert not resolver.is_alive()
    assert len(replace_errors) == 1
    assert isinstance(replace_errors[0], RuntimeError)

    # Both live operations occur after the complete rollback: the proposal is
    # not erased, and the arbiter never observes the transient revision 2.
    snapshot = bus.snapshot()
    assert set(snapshot["latest"]) == {"old", "concurrent"}
    assert snapshot["committed_revisions"] == {}
    assert arbiter.committed_revision("task") == 0
    assert winners == [old_goal]


def test_shared_sinks_use_one_process_wide_lock_order_across_executives() -> None:
    acquisitions: list[str] = []
    first = _OrderingSink("first", acquisitions)
    second = _OrderingSink("second", acquisitions)
    executive_a = TaskExecutive(revision_sinks=(first, second))
    executive_b = TaskExecutive(revision_sinks=(second, first))
    executive_a.submit(_validated(1))
    executive_b.submit(_validated(1))
    expected = [sink.label for sink in sorted((first, second), key=id)]

    acquisitions.clear()
    assert executive_a.replace(_validated(2)).accepted
    order_a = list(acquisitions)

    acquisitions.clear()
    assert executive_b.replace(_validated(2)).accepted
    order_b = list(acquisitions)

    assert order_a == expected
    assert order_b == expected
