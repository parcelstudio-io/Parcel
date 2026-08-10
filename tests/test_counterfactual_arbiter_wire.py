"""C-B opus half: GoalArbiter resolve wires arbitration log + oracle report."""

from __future__ import annotations

import pytest

from parcel_robot.counterfactual import (
    COUNTERFACTUAL_REPORT_SCHEMA,
    replay_committed_choice,
)
from parcel_robot.instructnav.arbiter import ARBITRATION_LOG_ENV, GoalArbiter, SE2Goal


def _goal(
    source: str,
    *,
    pose: tuple[float, float, float] = (1.0, 0.0, 0.0),
    priority: int = 0,
    confidence: float = 1.0,
    issued_s: float = 9.0,
    ttl_s: float = 2.0,
    plan_step_id: str = "",
    task_id: str = "",
    plan_revision: int = 0,
    waypoints: tuple[tuple[float, float], ...] = (),
) -> SE2Goal:
    return SE2Goal(
        source=source,
        pose=pose if not waypoints else None,
        waypoints=waypoints,
        priority=priority,
        confidence=confidence,
        issued_s=issued_s,
        ttl_s=ttl_s,
        plan_step_id=plan_step_id,
        task_id=task_id,
        plan_revision=plan_revision,
    )


def test_flag_off_leaves_no_log_and_preserves_winner() -> None:
    arbiter = GoalArbiter(
        lethal_cost=lambda x, y: x > 9.0,
        arbitration_log=False,
    )
    goals = [
        _goal("a", pose=(1.0, 0.0, 0.0), priority=1, issued_s=9.0),
        _goal("b", pose=(2.0, 0.0, 0.0), priority=5, issued_s=9.5),
        _goal("stale", pose=(0.0, 0.0, 0.0), priority=9, issued_s=0.0, ttl_s=1.0),
        _goal("lethal", pose=(10.0, 0.0, 0.0), priority=9, issued_s=9.0),
    ]
    winner = arbiter.resolve(goals, now_s=10.0)
    assert winner is not None
    assert winner.source == "b"
    assert arbiter.last_arbitration_log is None
    with pytest.raises(RuntimeError, match="no arbitration log"):
        arbiter.report_counterfactual(oracle_success={"b": True})


def test_flag_on_stamps_log_and_replay_matches_committed() -> None:
    arbiter = GoalArbiter(
        lethal_cost=lambda x, y: x > 9.0,
        arbitration_log=True,
        episode_id="ep-wire",
    )
    goals = [
        _goal("low", pose=(1.0, 0.0, 0.0), priority=1, confidence=0.9, issued_s=9.0),
        _goal("high", pose=(2.0, 0.0, 0.0), priority=5, confidence=0.5, issued_s=9.5),
        _goal("stale", pose=(0.0, 0.0, 0.0), priority=9, issued_s=0.0, ttl_s=1.0),
        _goal("lethal", pose=(10.0, 0.0, 0.0), priority=9, issued_s=9.0),
    ]
    winner = arbiter.resolve(goals, now_s=10.0)
    assert winner is not None
    assert winner.source == "high"

    record = arbiter.last_arbitration_log
    assert record is not None
    assert record.episode_id == "ep-wire"
    assert record.committed_candidate_id == "high"
    assert replay_committed_choice(record) == record.committed_candidate_id
    assert replay_committed_choice(record) == "high"

    by_id = {c.candidate_id: c for c in record.candidates}
    assert by_id["stale"].admissible is False
    assert by_id["stale"].veto_reason == "ttl"
    assert by_id["lethal"].admissible is False
    assert by_id["lethal"].veto_reason == "lethal"
    assert by_id["high"].admissible is True
    assert by_id["low"].admissible is True


def test_hold_logs_none_and_replay_holds() -> None:
    arbiter = GoalArbiter(
        lethal_cost=lambda _x, _y: True,
        arbitration_log=True,
        episode_id="ep-hold",
    )
    winner = arbiter.resolve(
        [_goal("only", pose=(1.0, 0.0, 0.0), issued_s=9.0)],
        now_s=10.0,
    )
    assert winner is None
    record = arbiter.last_arbitration_log
    assert record is not None
    assert record.committed_candidate_id is None
    assert replay_committed_choice(record) is None
    assert record.candidates[0].veto_reason == "lethal"


def test_plan_step_filter_logged_and_replay_matches() -> None:
    arbiter = GoalArbiter(arbitration_log=True, episode_id="ep-step")
    arbiter.set_plan_step("step-a")
    goals = [
        _goal("other", priority=9, plan_step_id="step-b", issued_s=9.0),
        _goal("owned", priority=1, plan_step_id="step-a", issued_s=9.0),
    ]
    winner = arbiter.resolve(goals, now_s=10.0)
    assert winner is not None
    assert winner.source == "owned"
    record = arbiter.last_arbitration_log
    assert record is not None
    assert record.active_plan_step == "step-a"
    assert record.committed_candidate_id == "owned"
    assert replay_committed_choice(record) == "owned"
    # Non-owned remains admissible; ownership is applied via active_plan_step.
    assert all(c.admissible for c in record.candidates)


def test_counterfactual_report_via_arbiter() -> None:
    arbiter = GoalArbiter(arbitration_log=True, episode_id="ep-cf")
    goals = [
        _goal("wrong", priority=5, confidence=0.9, issued_s=9.0),
        _goal("right", priority=1, confidence=0.5, issued_s=8.0),
    ]
    winner = arbiter.resolve(goals, now_s=10.0)
    assert winner is not None
    assert winner.source == "wrong"

    report = arbiter.report_counterfactual(
        oracle_success={"wrong": False, "right": True}
    )
    assert report.schema_version == COUNTERFACTUAL_REPORT_SCHEMA
    assert report.replay_matches_committed is True
    assert report.committed_candidate_id == "wrong"
    assert report.would_different_candidate_have_won is True
    assert report.alternate_success_ids == ("right",)
    assert report.oracle_preferred_candidate_id == "right"
    assert report.selection_regret is True
    assert arbiter.last_counterfactual_report is report


def test_env_flag_enables_arbitration_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ARBITRATION_LOG_ENV, "1")
    arbiter = GoalArbiter(episode_id="ep-env")
    assert arbiter.arbitration_log_enabled is True
    winner = arbiter.resolve(
        [_goal("solo", pose=(1.0, 0.0, 0.0), issued_s=9.0)],
        now_s=10.0,
    )
    assert winner is not None
    assert arbiter.last_arbitration_log is not None
    assert arbiter.last_arbitration_log.committed_candidate_id == "solo"
    monkeypatch.delenv(ARBITRATION_LOG_ENV, raising=False)


def test_constructor_false_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ARBITRATION_LOG_ENV, "true")
    arbiter = GoalArbiter(arbitration_log=False)
    assert arbiter.arbitration_log_enabled is False
    arbiter.resolve([_goal("solo", issued_s=9.0)], now_s=10.0)
    assert arbiter.last_arbitration_log is None
