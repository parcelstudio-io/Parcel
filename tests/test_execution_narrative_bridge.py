"""Fail-closed product-contract tests for the DMC-3 local bridge."""

from __future__ import annotations

from dataclasses import replace

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
from parcel_robot.brain.execution_narrative_bridge import (
    ExecutiveJournalContinuityError,
    NarratingTaskExecutiveV1,
)
from parcel_robot.brain.executive import TaskExecutive
from parcel_robot.brain.validator import PlanValidator
from parcel_robot.contracts.execution_narrative_v1 import (
    ExecutionNarrativeEventV1,
    build_execution_narrative_event,
)
from parcel_robot.voice.execution_narrative import (
    AuthenticatedExecutionNarrativeEventV1,
    NarrativeConsumerStateV1,
    TrustedExecutionNarrativeAuthenticatorV1,
    advance_speech_generation,
    consume_execution_narrative_event,
)

NOW_NS = 1_000_000_000_000
AUTH = TrustedExecutionNarrativeAuthenticatorV1(
    authenticator_id="dmc3_test_executive",
    key=b"dmc3-product-test-authentication-key-0001",
)


def _plan(task_id: str):
    plan = PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=1,
        source_turn_id=f"turn-{task_id}",
        goal=GoalSpec("hold", GoalTarget("current_pose"), 0.0),
        invariants=(),
        steps=(
            PlanStep(
                f"step-{task_id}",
                "Hold",
                {},
                ("base_available",),
                SuccessCondition("motion_stopped"),
                5.0,
                1,
                (),
                ("base",),
                "immediate",
            ),
        ),
    )
    return PlanValidator().validate(plan)


def _result(
    request,
    *,
    status: str,
    facts: tuple[VerifiedFact, ...] = (),
    detail: str = "controller_update",
) -> ExecutionResult:
    terminal = status != "in_progress"
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status=status,
        feedback_code=status,
        snapshot_id=f"snapshot-{request.task_id}",
        verified_facts=facts,
        checkpoint=True,
        detail_code=detail,
        started_at_monotonic_s=10.0,
        finished_at_monotonic_s=10.1 if terminal else None,
    )


def _bridge(*, capacity: int = 64) -> NarratingTaskExecutiveV1:
    return NarratingTaskExecutiveV1(
        TaskExecutive(),
        authenticator=AUTH,
        source_epoch=7,
        speech_generation_provider=lambda: 3,
        monotonic_ns=lambda: NOW_NS,
        event_capacity=capacity,
    )


def _consume_all(events):
    state = NarrativeConsumerStateV1(source_epoch=7, speech_generation=3)
    frames = []
    for authenticated in events:
        reduction = consume_execution_narrative_event(
            state,
            authenticated,
            authenticator=AUTH,
            now_monotonic_ns=NOW_NS + 1,
        )
        assert reduction.accepted, reduction.reason
        state = reduction.state
        assert reduction.frame is not None
        frames.append(reduction.frame)
        replay = consume_execution_narrative_event(
            state,
            authenticated,
            authenticator=AUTH,
            now_monotonic_ns=NOW_NS + 1,
        )
        assert replay.accepted is False
        assert replay.reason == "event_already_consumed"
        assert replay.frame is None
    return state, frames


def test_exact_lifecycle_is_authenticated_once_and_non_actuating() -> None:
    bridge = _bridge()
    assert bridge.submit(_plan("task-main")).accepted
    request = bridge.tick(now=10.0)[0]
    progress = _result(
        request,
        status="in_progress",
        facts=(VerifiedFact("near", "sofa", "localization", 0.94),),
    )
    assert bridge.report(progress).accepted
    success_fact = VerifiedFact("motion_stopped", None, "controller", 1.0)
    assert bridge.report(_result(request, status="succeeded", facts=(success_fact,))).accepted

    events = bridge.drain_narrative_events()
    assert [item.event.status for item in events] == [
        "accepted",
        "started",
        "progress",
        "succeeded",
    ]
    assert [item.event.event_sequence for item in events] == [1, 2, 3, 4]
    assert all(AUTH.verify(item) for item in events)
    assert all(item.authorizes_actuation is False for item in events)
    assert events[-1].event.verified_facts == (success_fact,)

    state, frames = _consume_all(events)
    assert state.tasks[0].phase == "succeeded"
    assert frames[-1].claimable_facts == (success_fact,)
    assert all(frame.authorizes_actuation is False for frame in frames)


def test_rejection_exception_and_unverified_success_never_mint_false_success() -> None:
    bridge = _bridge()
    assert bridge.submit(_plan("task-fail-closed")).accepted
    request = bridge.tick(now=10.0)[0]
    prefix = bridge.drain_narrative_events()

    wrong = replace(
        _result(request, status="succeeded", facts=(
            VerifiedFact("motion_stopped", None, "controller", 1.0),
        )),
        plan_revision=2,
    )
    assert bridge.report(wrong).accepted is False
    assert bridge.drain_narrative_events() == ()

    with pytest.raises(AttributeError):
        bridge.report(object())  # type: ignore[arg-type]
    assert bridge.drain_narrative_events() == ()

    disposition = bridge.report(_result(request, status="succeeded", facts=()))
    assert disposition.accepted and disposition.action == "task_failed"
    events = bridge.drain_narrative_events()
    assert len(events) == 1
    assert events[0].event.status == "failed"
    assert events[0].event.verified_facts == ()
    state, _ = _consume_all(prefix)
    silenced = consume_execution_narrative_event(
        state,
        events[0],
        authenticator=AUTH,
        now_monotonic_ns=NOW_NS + 1,
    )
    assert silenced.accepted
    assert silenced.reason == "unverified_success_claim_consumed_silently"
    assert silenced.frame is None
    assert silenced.state.last_event_sequence == 3
    failed = next(
        item for item in silenced.state.tasks if item.task_id == "task-fail-closed"
    )
    assert failed.phase == "failed"

    replay = consume_execution_narrative_event(
        silenced.state,
        events[0],
        authenticator=AUTH,
        now_monotonic_ns=NOW_NS + 1,
    )
    assert not replay.accepted
    assert replay.reason == "event_already_consumed"
    assert replay.state is silenced.state
    assert replay.frame is None

    assert bridge.submit(_plan("task-after-silent-failure")).accepted
    continued = bridge.tick(now=11.0)
    assert len(continued) == 1
    continuation_events = bridge.drain_narrative_events()
    assert [item.event.event_sequence for item in continuation_events] == [4, 5]
    state = silenced.state
    for authenticated in continuation_events:
        reduction = consume_execution_narrative_event(
            state,
            authenticated,
            authenticator=AUTH,
            now_monotonic_ns=NOW_NS + 1,
        )
        assert reduction.accepted, reduction.reason
        assert reduction.frame is not None
        state = reduction.state
    assert state.last_event_sequence == 5


def test_tamper_generation_freshness_and_lineage_fail_closed_without_frames() -> None:
    bridge = _bridge()
    bridge.submit(_plan("task-tamper"))
    authenticated = bridge.drain_narrative_events()[0]
    state = NarrativeConsumerStateV1(source_epoch=7, speech_generation=3)

    changed = build_execution_narrative_event(
        **{
            key: value
            for key, value in authenticated.event.as_dict().items()
            if key
            not in {
                "schema_version",
                "event_id",
                "mission_id",
                "action_id",
                "verified_facts",
                "evidence_refs",
                "detail_code",
            }
        },
        verified_facts=authenticated.event.verified_facts,
        evidence_refs=authenticated.event.evidence_refs,
        detail_code="altered_after_authentication",
    )
    tampered = AuthenticatedExecutionNarrativeEventV1(
        event=changed,
        authenticator_id=authenticated.authenticator_id,
        auth_tag=authenticated.auth_tag,
    )
    rejected = consume_execution_narrative_event(
        state,
        tampered,
        authenticator=AUTH,
        now_monotonic_ns=NOW_NS + 1,
    )
    assert not rejected.accepted and rejected.reason == "event_authentication_failed"
    assert rejected.frame is None and rejected.state is state

    state = advance_speech_generation(state, speech_generation=4)
    old = consume_execution_narrative_event(
        state,
        authenticated,
        authenticator=AUTH,
        now_monotonic_ns=NOW_NS + 1,
    )
    assert not old.accepted and old.reason == "speech_generation_mismatch"
    assert old.frame is None


def test_door_child_resume_preserves_parent_and_does_not_infer_keys() -> None:
    bridge = _bridge()
    bridge.submit(_plan("door-task"))
    bridge.tick(now=10.0)[0]
    suspended = bridge.suspend_task("door-task", reason="check_keys_on_sofa")
    assert suspended.accepted and suspended.state == "suspended"

    bridge.submit(
        _plan("sofa-keys-child"),
        task_class="voice",
        resume_parent_task_id="door-task",
    )
    child_request = bridge.tick(now=11.0)[0]
    arrival = VerifiedFact("near", "sofa", "localization", 0.96)
    bridge.report(_result(child_request, status="in_progress", facts=(arrival,)))
    bridge.report(
        _result(
            child_request,
            status="succeeded",
            facts=(VerifiedFact("motion_stopped", None, "controller", 1.0),),
        )
    )
    resumed = bridge.resume_task("door-task", reason="child_complete")
    assert resumed.accepted and resumed.state == "queued"
    resumed_request = bridge.tick(now=12.0)[0]

    events = bridge.drain_narrative_events()
    state, frames = _consume_all(events)
    by_status = [(item.event.task_id, item.event.status) for item in events]
    assert ("door-task", "suspended") in by_status
    assert ("door-task", "cancelled") not in by_status
    assert ("door-task", "succeeded") not in by_status
    child_success = next(
        item.event
        for item in events
        if item.event.task_id == "sofa-keys-child" and item.event.status == "succeeded"
    )
    assert child_success.resume_parent_task_id == "door-task"
    assert not any(
        fact.fact == "object_observed" and fact.target == "keys"
        for frame in frames
        for fact in frame.claimable_facts
    )
    parent = next(item for item in state.tasks if item.task_id == "door-task")
    assert (parent.plan_revision, parent.step_id, parent.attempt) == (
        resumed_request.plan_revision,
        resumed_request.step_id,
        resumed_request.attempt,
    )


def test_queue_overflow_is_bounded_visible_and_never_adds_authority() -> None:
    bridge = _bridge(capacity=1)
    bridge.submit(_plan("overflow-task"))
    with pytest.raises(ExecutiveJournalContinuityError) as captured:
        bridge.tick(now=10.0)
    assert captured.value.fault_code == "narrative_queue_overflow"
    status = bridge.narrative_queue_status()
    assert status.queued == 1 and status.capacity == 1 and status.overflow_count == 1
    assert status.journal_cursor == 1
    assert status.fault_code == "narrative_queue_overflow"
    retained = bridge.drain_narrative_events()[0]
    assert retained.authorizes_actuation is False
    rejected = consume_execution_narrative_event(
        NarrativeConsumerStateV1(source_epoch=7, speech_generation=3),
        retained,
        authenticator=AUTH,
        now_monotonic_ns=NOW_NS + 1,
    )
    assert rejected.accepted is True
    assert rejected.frame is not None
    assert rejected.state.last_event_sequence == 1
    # No post-gap event is ever emitted from the faulted bridge.
    assert bridge.drain_narrative_events() == ()
    with pytest.raises(ExecutiveJournalContinuityError):
        bridge.sync_narrative_transitions()


def test_contract_exact_decode_rejects_unknown_fields() -> None:
    bridge = _bridge()
    bridge.submit(_plan("task-exact"))
    mapping = bridge.drain_narrative_events()[0].event.as_dict()
    assert ExecutionNarrativeEventV1.from_mapping(mapping).as_dict() == mapping
    with pytest.raises(ValueError, match="fields must be exact"):
        ExecutionNarrativeEventV1.from_mapping({**mapping, "hosted_claim": True})
    with pytest.raises(TypeError, match="task_id must be a string"):
        ExecutionNarrativeEventV1.from_mapping({**mapping, "task_id": 123})
