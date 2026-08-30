"""Owner-authored transition journal and one-to-one bridge tests for DMC-4."""

from __future__ import annotations

import ast
import importlib.util
import json
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from parcel_robot.brain.contracts import (
    BatteryStateSnapshot,
    ExecutionResult,
    GoalSpec,
    GoalTarget,
    ObservationSnapshot,
    PlanIR,
    PlanStep,
    RobotStateSnapshot,
    SafetyStateSnapshot,
    SensorSnapshot,
    SuccessCondition,
    TaskStateSnapshot,
    VerifiedFact,
)
from parcel_robot.brain.execution_narrative_bridge import (
    ExecutiveJournalContinuityError,
    NarratingTaskExecutiveV1,
)
from parcel_robot.brain.executive import InterruptRequest, ResourceLocks, TaskExecutive
from parcel_robot.brain.validator import PlanValidator, SkillContractRegistry
from parcel_robot.voice.execution_narrative import (
    NarrativeConsumerStateV1,
    TrustedExecutionNarrativeAuthenticatorV1,
    consume_execution_narrative_event,
)

AUTH = TrustedExecutionNarrativeAuthenticatorV1(
    authenticator_id="dmc4_test_journal",
    key=b"dmc4-product-journal-test-key-20260829",
)
NOW_NS = 4_000_000_000_000


def _snapshot(*, critical: bool = False) -> ObservationSnapshot:
    return ObservationSnapshot(
        schema_version=1,
        snapshot_id="snapshot-dmc4",
        captured_at_monotonic_s=10.0,
        camera=SensorSnapshot("camera", True, True, "camera", 9.9, 100.0),
        lidar=SensorSnapshot("lidar", True, True, "lidar", 9.9, 50.0),
        robot=RobotStateSnapshot(False, "stand"),
        safety=SafetyStateSnapshot(False, False, True),
        battery=BatteryStateSnapshot(
            "critical" if critical else "normal",
            5.0 if critical else 80.0,
            "unitree",
        ),
        task=TaskStateSnapshot(),
    )


def _hold_plan(
    task_id: str,
    *,
    revision: int = 1,
    attempts: int = 1,
    interruptibility: str = "checkpoint",
    steps: int = 1,
) -> PlanIR:
    return PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=revision,
        source_turn_id=f"turn-{task_id}-{revision}",
        goal=GoalSpec("hold", GoalTarget("current_pose"), 0.0),
        invariants=(),
        steps=tuple(
            PlanStep(
                f"hold-{index}",
                "Hold",
                {},
                ("base_available",),
                SuccessCondition("motion_stopped"),
                5.0,
                attempts,
                ("safe_stop",) if attempts > 1 else (),
                ("base",),
                interruptibility,
            )
            for index in range(steps)
        ),
    )


def _critical_plan(task_id: str, *, revision: int = 1) -> PlanIR:
    return PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=revision,
        source_turn_id=f"turn-{task_id}-{revision}",
        goal=GoalSpec("safe_pose", GoalTarget("safe_region", "safe region"), 0.5),
        invariants=("do_not_interrupt_critical_task",),
        steps=(
            PlanStep(
                "safe",
                "ReturnToSafePose",
                {"pose": "sit"},
                (
                    "camera_fresh",
                    "lidar_fresh",
                    "base_available",
                    "posture_available",
                    "battery_critical",
                ),
                SuccessCondition("safe_pose"),
                30.0,
                1,
                (),
                ("base", "posture", "attention"),
                "never",
            ),
        ),
    )


def _validated(plan: PlanIR, *, critical: bool = False):
    registry = SkillContractRegistry.default(pose_names=("sit",))
    return PlanValidator(registry).validate(plan, _snapshot(critical=critical))


def _result(
    request,
    status: str,
    *,
    checkpoint: bool = True,
    verified: bool = True,
) -> ExecutionResult:
    terminal = status != "in_progress"
    success_fact = (
        VerifiedFact("safe_pose", None, "controller", 1.0)
        if request.skill == "ReturnToSafePose"
        else VerifiedFact("motion_stopped", None, "controller", 1.0)
    )
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status=status,
        feedback_code=status,
        snapshot_id="snapshot-dmc4",
        verified_facts=((success_fact,) if status == "succeeded" and verified else ()),
        checkpoint=checkpoint,
        detail_code=f"result_{status}",
        started_at_monotonic_s=10.0,
        finished_at_monotonic_s=11.0 if terminal else None,
    )


def _rows(executive: TaskExecutive):
    read = executive.read_transition_journal(after_sequence=0)
    assert read.status == "ok"
    return read.transitions


def _bridge(executive: TaskExecutive | None = None, *, capacity: int = 256):
    return NarratingTaskExecutiveV1(
        executive or TaskExecutive(),
        authenticator=AUTH,
        source_epoch=41,
        speech_generation_provider=lambda: 2,
        monotonic_ns=lambda: NOW_NS,
        event_capacity=capacity,
    )


def test_journal_submission_rejections_nested_replace_and_immutability() -> None:
    executive = TaskExecutive()
    first = executive.submit(_validated(_hold_plan("one")))
    assert first.accepted
    rejected = executive.submit(_validated(_hold_plan("one")))
    assert not rejected.accepted
    # replace(unknown) nests through submit() but records exactly once.
    nested = executive.replace(_validated(_hold_plan("nested", revision=2)))
    assert nested.accepted

    rows = _rows(executive)
    assert [row.transition_sequence for row in rows] == [1, 2]
    assert [row.family for row in rows] == ["submission", "submission"]
    assert [row.disposition for row in rows] == ["task_queued", "task_queued"]
    assert rows[0].prior_state == "absent" and rows[0].resulting_state == "queued"
    assert all(row.authorizes_actuation is False for row in rows)
    with pytest.raises(FrozenInstanceError):
        rows[0].resulting_state = "succeeded"  # type: ignore[misc]


def test_tick_timeout_retry_and_dispatch_are_two_exact_ordered_rows() -> None:
    executive = TaskExecutive()
    executive.submit(_validated(_hold_plan("timeout", attempts=2)))
    first = executive.tick(_snapshot(), now=10.0)[0]
    assert first.attempt == 1
    retry = executive.tick(_snapshot(), now=15.0)[0]
    assert retry.attempt == 2

    rows = _rows(executive)
    assert [row.disposition for row in rows] == [
        "task_queued",
        "step_dispatched",
        "step_timeout_retry",
        "step_dispatched",
    ]
    timeout, redispatch = rows[-2:]
    assert (timeout.attempt, timeout.prior_state, timeout.resulting_state) == (
        1,
        "running",
        "recovering",
    )
    assert (redispatch.attempt, redispatch.prior_state, redispatch.resulting_state) == (
        2,
        "recovering",
        "running",
    )


def test_tick_terminal_timeout_and_waits_are_owner_authored_without_spam() -> None:
    precondition = TaskExecutive()
    precondition.submit(_validated(_critical_plan("precondition"), critical=True))
    assert precondition.tick(None, now=10.0) == ()
    assert precondition.tick(None, now=10.1) == ()
    assert [row.disposition for row in _rows(precondition)] == [
        "task_queued",
        "waiting_precondition",
    ]

    locks = ResourceLocks()
    resource = TaskExecutive(resources=locks)
    resource.submit(_validated(_hold_plan("holder")))
    resource.tick(_snapshot(), now=10.0)
    resource.submit(_validated(_hold_plan("waiter")))
    assert resource.tick(_snapshot(), now=10.1) == ()
    assert resource.tick(_snapshot(), now=10.2) == ()
    assert [row.disposition for row in _rows(resource)].count("waiting_resource") == 1

    terminal = TaskExecutive()
    terminal.submit(_validated(_hold_plan("timeout-terminal")))
    terminal.tick(_snapshot(), now=10.0)
    assert terminal.tick(_snapshot(), now=15.0) == ()
    assert _rows(terminal)[-1].disposition == "step_timeout_failed"


def test_replacement_immediate_deferred_checkpoint_and_after_step_lineage() -> None:
    immediate = TaskExecutive()
    immediate.submit(_validated(_hold_plan("immediate")))
    immediate.replace(_validated(_hold_plan("immediate", revision=2)))
    assert [(row.disposition, row.plan_revision) for row in _rows(immediate)] == [
        ("task_queued", 1),
        ("replacement_activated", 2),
    ]

    checkpoint = TaskExecutive()
    checkpoint.submit(_validated(_hold_plan("checkpoint")))
    old = checkpoint.tick(_snapshot(), now=10.0)[0]
    checkpoint.replace(_validated(_hold_plan("checkpoint", revision=2)))
    checkpoint.report(_result(old, "in_progress", checkpoint=True))
    checkpoint_rows = _rows(checkpoint)
    assert [row.disposition for row in checkpoint_rows][-2:] == [
        "replacement_deferred",
        "replacement_activated_at_checkpoint",
    ]
    assert [row.plan_revision for row in checkpoint_rows][-2:] == [1, 2]

    after_step = TaskExecutive()
    after_step.submit(
        _validated(_critical_plan("after-step"), critical=True),
        task_class="system",
    )
    old_critical = after_step.tick(_snapshot(critical=True), now=10.0)[0]
    after_step.replace(_validated(_hold_plan("after-step", revision=2)))
    after_step.report(_result(old_critical, "succeeded"))
    final_rows = _rows(after_step)
    assert [row.disposition for row in final_rows][-2:] == [
        "replacement_deferred",
        "replacement_activated_after_step",
    ]
    assert final_rows[-1].plan_revision == 2
    assert final_rows[-1].verified_facts == ()


def test_report_final_step_preserves_preterminal_lineage_and_exact_fact() -> None:
    executive = TaskExecutive()
    executive.submit(_validated(_hold_plan("final", steps=2)))
    first = executive.tick(_snapshot(), now=10.0)[0]
    executive.report(_result(first, "succeeded"))
    second = executive.tick(_snapshot(), now=11.0)[0]
    fact = _result(second, "succeeded").verified_facts[0]
    executive.report(_result(second, "succeeded"))

    rows = _rows(executive)
    step_row = next(row for row in rows if row.disposition == "step_succeeded")
    final_row = rows[-1]
    assert step_row.step_id == first.step_id
    assert final_row.disposition == "task_succeeded"
    assert final_row.step_id == second.step_id
    assert final_row.attempt == second.attempt
    assert final_row.prior_state == "running"
    assert final_row.resulting_state == "succeeded"
    assert final_row.verified_facts == (fact,)
    assert final_row.evidence_refs == ("snapshot-dmc4",)


def test_interruption_and_explicit_lifecycle_append_only_real_mutations() -> None:
    executive = TaskExecutive()
    executive.submit(_validated(_hold_plan("parent")))
    executive.tick(_snapshot(), now=10.0)
    overlap = executive.request_interrupt(
        InterruptRequest("voice", "ambient", target_task_id="parent")
    )
    before = len(_rows(executive))
    assert overlap.action == "overlap"
    assert len(_rows(executive)) == before

    suspended = executive.request_interrupt(
        InterruptRequest("voice", "summons", target_task_id="parent")
    )
    assert suspended.action == "suspend"
    assert _rows(executive)[-1].disposition == "interrupt_suspended"
    no_op = executive.suspend_task("parent", reason="already parked")
    assert no_op.accepted
    assert len(_rows(executive)) == before + 1
    resumed = executive.resume_task("parent", reason="child complete")
    assert resumed.accepted
    assert _rows(executive)[-1].disposition == "task_resumed"
    rejected = executive.resume_task("parent")
    assert not rejected.accepted
    count = len(_rows(executive))
    assert len(_rows(executive)) == count

    executive.tick(_snapshot(), now=11.0)
    cancelled = executive.cancel_all("owner stop")
    assert cancelled.action == "cancel_now"
    assert _rows(executive)[-1].disposition == "interrupt_cancelled"


def test_bridge_maps_journal_without_snapshot_inference_and_consumes_wait() -> None:
    executive = TaskExecutive()
    bridge = _bridge(executive)
    # Mapping must not consult snapshot; the facade's read-only snapshot method
    # remains available to callers, but event creation is journal-only.
    executive.snapshot = lambda: (_ for _ in ()).throw(AssertionError("snapshot inferred"))  # type: ignore[method-assign]
    bridge.submit(_validated(_critical_plan("wait"), critical=True))
    bridge.tick(None, now=10.0)
    events = bridge.drain_narrative_events()
    assert [item.event.status for item in events] == ["accepted", "blocked"]
    assert [item.event.event_sequence for item in events] == [1, 2]

    state = NarrativeConsumerStateV1(source_epoch=41, speech_generation=2)
    for authenticated in events:
        reduction = consume_execution_narrative_event(
            state,
            authenticated,
            authenticator=AUTH,
            now_monotonic_ns=NOW_NS + 1,
        )
        assert reduction.accepted, reduction.reason
        assert reduction.frame is not None
        state = reduction.state
    assert state.last_event_sequence == 2


def test_journal_and_bridge_overflow_are_explicit_and_no_suffix_is_guessed() -> None:
    executive = TaskExecutive(transition_capacity=2)
    executive.submit(_validated(_hold_plan("one")))
    executive.submit(_validated(_hold_plan("two")))
    executive.submit(_validated(_hold_plan("three")))
    status = executive.transition_journal_status()
    assert (status.retained, status.capacity, status.overflow_count) == (2, 2, 1)
    lost = executive.read_transition_journal(after_sequence=0)
    assert lost.status == "overflow" and lost.transitions == ()
    suffix = executive.read_transition_journal(after_sequence=1)
    assert suffix.status == "ok"
    assert [item.transition_sequence for item in suffix.transitions] == [2, 3]
    assert executive.read_transition_journal(after_sequence=4).status == "cursor_ahead"

    bridge = _bridge(executive)
    with pytest.raises(ExecutiveJournalContinuityError) as captured:
        bridge.sync_narrative_transitions()
    assert captured.value.fault_code == "journal_overflow"
    assert bridge.narrative_queue_status().fault_code == "journal_overflow"
    assert bridge.drain_narrative_events() == ()


def test_journal_sequences_are_contiguous_under_concurrent_producers() -> None:
    count = 32
    executive = TaskExecutive(max_records=64, transition_capacity=128)
    barrier = threading.Barrier(count)
    errors: list[BaseException] = []

    def produce(index: int) -> None:
        try:
            barrier.wait(timeout=5.0)
            result = executive.submit(_validated(_hold_plan(f"thread-{index}")))
            assert result.accepted
        except BaseException as error:  # noqa: BLE001 - retained for the main assertion
            errors.append(error)

    threads = [threading.Thread(target=produce, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    rows = _rows(executive)
    assert len(rows) == count
    assert [row.transition_sequence for row in rows] == list(range(1, count + 1))
    assert len({row.task_id for row in rows}) == count


def _load_dmc4_module(filename: str, module_name: str):
    path = (
        Path(__file__).resolve().parents[1]
        / "research"
        / "20260829"
        / "duplex-transaction-4"
        / filename
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dmc4_oracle_covers_negative_calls_and_parent_child_lineage() -> None:
    runner = _load_dmc4_module("run.py", "dmc4_runner_test")
    verifier = _load_dmc4_module("verify_results.py", "dmc4_verifier_test")
    manifest = json.loads(runner.MANIFEST_PATH.read_text(encoding="utf-8"))

    for family in manifest["transition_families"]:
        for trial in range(3):
            row = runner.run_transition_case(manifest, family, trial)
            assert verifier._verify_transition_row(row), (family, trial)
    parent = runner.run_parent_child_case(manifest, 0)
    assert verifier._verify_transition_row(parent)

    # The semantic oracle must detect a negative-call ledger mutation even if
    # the exact expected/actual transition lists themselves remain untouched.
    parent["final_consumer_state"]["last_event_sequence"] -= 1
    assert not verifier._verify_transition_row(parent)


def test_dmc4_independent_verifier_has_no_parcel_import() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "research"
        / "20260829"
        / "duplex-transaction-4"
        / "verify_results.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name == "parcel_robot" or name.startswith("parcel_robot.") for name in imports)
