from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from parcel_robot.brain.contracts import FrozenDict, SuccessCondition
from parcel_robot.brain.executive import DispatchRequest
from parcel_robot.brain.runtime_adapter import (
    SemanticRuntimeState,
    SemanticTaskRuntimeAdapter,
    admitted_plan_schema,
    dispatch_key,
)
from parcel_robot.models import SpatialIntent


def _request(
    skill: str,
    arguments: dict[str, object],
    fact: str,
    *,
    target: str | None = None,
) -> DispatchRequest:
    return DispatchRequest(
        task_id=f"task-{skill.lower()}",
        plan_revision=1,
        step_id="step-1",
        attempt=1,
        skill=skill,
        arguments=FrozenDict(arguments),
        success=SuccessCondition(fact, target),
        resources=("base",),
        timeout_s=30.0,
    )


@pytest.fixture
def calls() -> list[tuple[str, object]]:
    return []


@pytest.fixture
def adapter(calls: list[tuple[str, object]]) -> SemanticTaskRuntimeAdapter:
    def callback(name: str) -> Callable[[object], None]:
        return lambda value=None: calls.append((name, value))

    return SemanticTaskRuntimeAdapter(
        navigate=callback("navigate"),
        follow_formation=lambda relation, distance: calls.append(
            ("follow", (relation, distance))
        ),
        spatial_behavior=callback("spatial"),
        hold=callback("hold"),
        vocalize=callback("voice"),
    )


def test_navigation_dispatch_has_no_raw_motion_and_requires_terminal_verifier(
    adapter: SemanticTaskRuntimeAdapter,
    calls: list[tuple[str, object]],
) -> None:
    request = _request(
        "NavigateTo",
        {"directive": "the sidewalk"},
        "inside",
        target="sidewalk",
    )

    assert adapter.dispatch(request, now=10.0) is None
    assert calls == [("navigate", "the sidewalk")]
    progress = adapter.poll(
        SemanticRuntimeState(
            "snapshot-1",
            navigation_enabled=True,
            navigation_state="verifying",
            navigation_reason="settling",
            robot_moving=False,
        ),
        now=11.0,
    )[0]
    assert progress.status == "in_progress"
    assert progress.verified_facts == ()

    succeeded = adapter.poll(
        SemanticRuntimeState(
            "snapshot-2",
            navigation_state="arrived",
            navigation_goal="sidewalk",
        ),
        now=12.0,
    )[0]
    assert succeeded.status == "succeeded"
    assert succeeded.verified_facts[0].fact == "inside"
    assert succeeded.verified_facts[0].target == "sidewalk"
    assert succeeded.verified_facts[0].source == "navigation_terminal_verifier"
    assert adapter.active() == ()


@pytest.mark.parametrize(
    ("dispatch_request", "expected"),
    [
        (
            _request(
                "OrbitOwner",
                {"direction": "clockwise", "size": "small", "revolutions": 1.0},
                "orbit_complete",
            ),
            SpatialIntent("orbit_owner", "clockwise", size="small", revolutions=1.0),
        ),
        (
            _request(
                "MoveRelative",
                {"direction": "away_from_owner", "steps": 5},
                "distance_travelled",
            ),
            SpatialIntent("move_steps", "away_from_owner", steps=5),
        ),
    ],
)
def test_spatial_skills_compile_to_bounded_intents_and_verify_completion(
    adapter: SemanticTaskRuntimeAdapter,
    calls: list[tuple[str, object]],
    dispatch_request: DispatchRequest,
    expected: SpatialIntent,
) -> None:
    adapter.dispatch(dispatch_request, now=20.0)
    assert calls == [("spatial", expected)]

    result = adapter.poll(
        SemanticRuntimeState(
            "snapshot-spatial",
            spatial_state="completed",
            spatial_reason="controller_verified",
        ),
        now=22.0,
    )[0]
    assert result.status == "succeeded"
    assert result.verified_facts[0].fact == dispatch_request.success.fact


def test_follow_succeeds_only_after_camera_controller_holds_behind(
    adapter: SemanticTaskRuntimeAdapter,
    calls: list[tuple[str, object]],
) -> None:
    request = _request(
        "FollowFormation",
        {"relation": "behind", "distance_m": 1.9},
        "behind",
        target="owner",
    )
    adapter.dispatch(request, now=30.0)
    assert calls == [("follow", ("behind", 1.9))]

    acquiring = adapter.poll(
        SemanticRuntimeState(
            "snapshot-follow-1",
            follow_enabled=True,
            follow_state="acquiring_heading",
            follow_mode="behind",
        ),
        now=31.0,
    )[0]
    assert acquiring.status == "in_progress"

    holding = adapter.poll(
        SemanticRuntimeState(
            "snapshot-follow-2",
            follow_enabled=True,
            follow_state="holding_behind",
            follow_mode="behind",
        ),
        now=32.0,
    )[0]
    assert holding.status == "succeeded"
    assert holding.verified_facts[0].source == "camera_track_formation_controller"


def test_speech_is_logged_and_completed_without_claiming_body_motion(
    adapter: SemanticTaskRuntimeAdapter,
    calls: list[tuple[str, object]],
) -> None:
    request = _request(
        "AskClarification",
        {"question": "Which store do you mean?"},
        "utterance_sent",
    )

    result = adapter.dispatch(request, now=40.0)
    assert calls == [("voice", "Which store do you mean?")]
    assert result is not None and result.status == "succeeded"
    assert result.verified_facts[0].source == "runtime_voice_log"
    assert adapter.active() == ()


def test_reconcile_drops_stale_attempts_after_executive_retry(
    adapter: SemanticTaskRuntimeAdapter,
) -> None:
    request = _request("Hold", {}, "motion_stopped")
    adapter.dispatch(request, now=50.0)
    assert dispatch_key(request) == adapter.active()[0].key

    removed = adapter.reconcile(())
    assert removed[0].request == request
    assert adapter.active() == ()


def test_hold_requires_fresh_controller_stop_feedback(
    adapter: SemanticTaskRuntimeAdapter,
) -> None:
    request = _request("Hold", {}, "motion_stopped")
    adapter.dispatch(request, now=55.0)

    unverified = adapter.poll(
        SemanticRuntimeState(
            "snapshot-hold-stale",
            stop_confirmed=True,
            control_feedback_fresh=False,
            robot_moving=False,
        ),
        now=55.1,
    )[0]
    assert unverified.status == "in_progress"
    assert unverified.verified_facts == ()

    verified = adapter.poll(
        SemanticRuntimeState(
            "snapshot-hold-fresh",
            stop_confirmed=True,
            control_feedback_fresh=True,
            robot_moving=False,
        ),
        now=55.2,
    )[0]
    assert verified.status == "succeeded"
    assert verified.verified_facts[0].source == "controller_feedback"


def test_failed_runtime_state_never_fabricates_success_fact(
    adapter: SemanticTaskRuntimeAdapter,
) -> None:
    request = _request(
        "NavigateTo",
        {"directive": "the lamppost"},
        "near",
        target="lamppost",
    )
    adapter.dispatch(request, now=60.0)
    result = adapter.poll(
        SemanticRuntimeState(
            "snapshot-fail",
            navigation_state="failed",
            navigation_reason="target_not_grounded",
        ),
        now=61.0,
    )[0]

    assert result.status == "failed"
    assert result.verified_facts == ()


@pytest.mark.parametrize("skill", ("ScanBehavior", "SearchEntity"))
@pytest.mark.parametrize(
    ("navigation_state", "navigation_reason"),
    (
        ("arrived", "collision_contact"),
        ("stale", ""),
        ("failed", "semantic_target_unreachable"),
    ),
    ids=("collision_reason", "stale_state", "unreachable_reason"),
)
def test_instructnav_failure_never_fabricates_skill_completion(
    skill: str,
    navigation_state: str,
    navigation_reason: str,
) -> None:
    adapter = SemanticTaskRuntimeAdapter(
        navigate=lambda _directive: None,
        follow_formation=lambda _relation, _distance: None,
        spatial_behavior=lambda _intent: None,
        hold=lambda: None,
        vocalize=lambda _text: None,
        scan_behavior=lambda: None,
        search_entity=lambda _query: None,
    )
    request = _request(
        skill,
        {} if skill == "ScanBehavior" else {"query": "lamppost"},
        "skill_completed",
    )
    adapter.dispatch(request, now=62.0)

    result = adapter.poll(
        SemanticRuntimeState(
            "snapshot-instructnav-failure",
            navigation_state=navigation_state,
            navigation_reason=navigation_reason,
        ),
        now=63.0,
    )[0]

    assert result.status == "failed"
    assert result.verified_facts == ()
    assert adapter.active() == ()


@pytest.mark.parametrize("skill", ("ScanBehavior", "SearchEntity"))
def test_instructnav_requires_an_unambiguous_arrived_terminal(skill: str) -> None:
    adapter = SemanticTaskRuntimeAdapter(
        navigate=lambda _directive: None,
        follow_formation=lambda _relation, _distance: None,
        spatial_behavior=lambda _intent: None,
        hold=lambda: None,
        vocalize=lambda _text: None,
        scan_behavior=lambda: None,
        search_entity=lambda _query: None,
    )
    request = _request(
        skill,
        {} if skill == "ScanBehavior" else {"query": "lamppost"},
        "skill_completed",
    )
    adapter.dispatch(request, now=64.0)

    result = adapter.poll(
        SemanticRuntimeState(
            "snapshot-instructnav-arrived",
            navigation_state="arrived",
            navigation_reason="semantic_arrival_verified",
        ),
        now=65.0,
    )[0]

    assert result.status == "succeeded"
    assert result.verified_facts[0].fact == "skill_completed"


def test_admitted_schema_is_a_defensive_runtime_skill_subset() -> None:
    source = {
        "$defs": {
            "step": {
                "properties": {
                    "skill": {"enum": ["NavigateTo", "Pose", "Hold"]},
                }
            }
        }
    }

    restricted = admitted_plan_schema(source, ("Hold", "NavigateTo"))

    assert restricted["$defs"]["step"]["properties"]["skill"]["enum"] == [
        "Hold",
        "NavigateTo",
    ]
    assert source["$defs"]["step"]["properties"]["skill"]["enum"] == [
        "NavigateTo",
        "Pose",
        "Hold",
    ]


def test_retry_safe_stop_runs_before_semantic_redispatch(
    adapter: SemanticTaskRuntimeAdapter,
    calls: list[tuple[str, object]],
) -> None:
    request = replace(
        _request(
            "NavigateTo",
            {"directive": "sidewalk"},
            "inside",
            target="sidewalk",
        ),
        attempt=2,
        recovery_action="safe_stop",
    )

    adapter.dispatch(request, now=70.0)

    assert calls == [("hold", None), ("navigate", "sidewalk")]
