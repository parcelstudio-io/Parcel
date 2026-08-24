"""Card W7: the SearchOwner reacquisition skill, end to end.

Three layers are pinned here because the card spans all three: the bounded
controller itself, the semantic packaging (validator contract, adapter
dispatch, verified completion), and the deterministic runtime trigger that
proposes the skill without a model in the loop.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain.compiler import compile_plan_contracts
from parcel_robot.brain.contracts import (
    FrozenDict,
    GoalSpec,
    GoalTarget,
    PlanIR,
    PlanStep,
    SuccessCondition,
)
from parcel_robot.brain.executive import DispatchRequest
from parcel_robot.brain.runtime_adapter import (
    OWNER_TRACK_CONFIDENCE_MIN,
    SemanticRuntimeState,
    SemanticTaskRuntimeAdapter,
)
from parcel_robot.brain.validator import (
    SYSTEM_SKILL_NAMES,
    PlanValidator,
    SkillContractRegistry,
)
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.navigation.search_owner import (
    SearchOwnerConfig,
    SearchOwnerController,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]


# --- fixtures ---------------------------------------------------------------


def _observation(
    timestamp: float,
    *,
    robot_x: float = 0.0,
    robot_y: float = 0.0,
    robot_yaw: float = 0.0,
    owner_visible: bool = False,
    owner_x: float = 0.0,
    owner_y: float = 0.0,
    confidence: float = 0.0,
    collision: bool = False,
) -> SimObservation:
    return SimObservation(
        timestamp=timestamp,
        robot=RobotPose(x=robot_x, y=robot_y, yaw=robot_yaw),
        owner=OwnerTrack(
            owner_id="owner-camera-track",
            x=owner_x,
            y=owner_y,
            visible=owner_visible,
            confidence=confidence,
        ),
        # Healthy fixtures include a far-field scan; missing scan fails closed (P0-B).
        nearest_obstacle_m=10.0,
        nearest_obstacle_bearing_rad=0.0,
        collision=collision,
        backend="search-owner-test",
    )


def _started(
    controller: SearchOwnerController,
    *,
    last_x: float = 4.0,
    last_y: float = 0.0,
) -> SearchOwnerController:
    controller.start(last_x=last_x, last_y=last_y, lost_at_s=0.0, now=0.0)
    return controller


def _sweep_to_completion(
    controller: SearchOwnerController,
    *,
    start_t: float,
    robot_x: float,
) -> float:
    """Drive the in-place sweep by integrating its own yaw command."""

    yaw = 0.0
    t = start_t
    for _ in range(400):
        if controller.state != "sweep":
            return t
        decision = controller.step(
            _observation(t, robot_x=robot_x, robot_yaw=yaw), now=t
        )
        yaw += decision.command.vyaw * 0.1
        t += 0.1
    raise AssertionError("sweep never completed")


# --- configuration ----------------------------------------------------------


def test_unknown_owner_search_keys_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown owner_search settings"):
        SearchOwnerConfig.from_mapping({"max_serch_s": 45.0})


def test_owner_search_bounds_are_validated_not_clamped() -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        SearchOwnerConfig(max_search_s=0.0)
    with pytest.raises(ValueError, match="below the search budget"):
        SearchOwnerConfig(max_search_s=10.0, goto_timeout_s=12.0)
    with pytest.raises(ValueError, match="positive integer"):
        SearchOwnerConfig.from_mapping({"frontier_bearings": 0})
    with pytest.raises(ValueError, match="must be an integer"):
        SearchOwnerConfig.from_mapping({"frontier_rings": 2.5})


def test_shipped_config_section_loads() -> None:
    import yaml

    raw = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    config = SearchOwnerConfig.from_mapping(raw["owner_search"])

    assert config.lost_timeout_s == 3.0
    assert config.max_search_s == 45.0


# --- the three states -------------------------------------------------------


def test_search_walks_last_observed_then_sweep_then_frontier() -> None:
    controller = _started(SearchOwnerController())

    approach = controller.step(_observation(0.1, robot_x=0.0), now=0.1)
    assert approach.state == "go_to_last_observed"
    assert approach.command.vx > 0.0
    assert (approach.target_x_m, approach.target_y_m) == (4.0, 0.0)

    arrived = controller.step(_observation(1.0, robot_x=3.8), now=1.0)
    assert arrived.state == "sweep"
    assert arrived.reason == "reached_last_observed"

    swept = controller.step(_observation(1.1, robot_x=3.8), now=1.1)
    assert swept.state == "sweep"
    assert swept.command.vx == 0.0 and swept.command.vyaw != 0.0

    after = _sweep_to_completion(controller, start_t=1.2, robot_x=3.8)
    assert controller.state == "frontier_search"

    exploring = controller.step(_observation(after, robot_x=3.8), now=after)
    assert exploring.state == "frontier_search"
    assert exploring.target_x_m is not None
    # Frontier candidates are pruned to where the owner could have walked.
    reach = math.hypot(exploring.target_x_m - 4.0, exploring.target_y_m - 0.0)
    assert reach <= 1.6 * after + 1e-6 or reach <= controller.config.frontier_ring_step_m


def test_a_blocked_last_observed_point_does_not_eat_the_budget() -> None:
    controller = _started(
        SearchOwnerController(SearchOwnerConfig(goto_timeout_s=2.0)),
        last_x=40.0,
    )
    controller.step(_observation(0.1), now=0.1)

    timed_out = controller.step(_observation(2.5), now=2.5)

    assert timed_out.state == "sweep"
    assert timed_out.reason == "last_observed_unreachable"


# --- terminal outcomes ------------------------------------------------------


@pytest.mark.parametrize(
    ("advance_to", "expected_state"),
    [(0.1, "go_to_last_observed"), (1.0, "sweep")],
)
def test_owner_reappearing_in_any_state_is_immediate_terminal_success(
    advance_to: float,
    expected_state: str,
) -> None:
    controller = _started(SearchOwnerController())
    controller.step(_observation(0.1), now=0.1)
    if expected_state == "sweep":
        controller.step(_observation(advance_to, robot_x=3.8), now=advance_to)
        assert controller.state == "sweep"

    found = controller.step(
        _observation(
            advance_to + 0.1,
            robot_x=3.8,
            owner_visible=True,
            owner_x=5.0,
            confidence=0.9,
        ),
        now=advance_to + 0.1,
    )

    assert found.done is True
    assert found.state == "reacquired"
    assert found.outcome == "owner_reacquired"
    assert found.command == VelocityCommand()
    assert controller.enabled is False


def test_a_low_confidence_glimpse_is_not_a_reacquisition() -> None:
    controller = _started(SearchOwnerController())

    glimpse = controller.step(
        _observation(0.1, owner_visible=True, owner_x=5.0, confidence=0.2),
        now=0.1,
    )

    assert glimpse.done is False
    assert controller.enabled is True


def test_the_budget_expiring_gives_up_cleanly() -> None:
    controller = _started(
        SearchOwnerController(
            SearchOwnerConfig(max_search_s=5.0, goto_timeout_s=2.0, sweep_timeout_s=2.0)
        )
    )
    controller.step(_observation(0.1), now=0.1)

    expired = controller.step(_observation(5.5), now=5.5)

    assert expired.done is True
    assert expired.state == "gave_up"
    assert expired.outcome == "gave_up"
    assert expired.command == VelocityCommand()
    assert controller.enabled is False


# --- safety composition -----------------------------------------------------


def test_stale_perception_stops_motion_without_ending_the_search() -> None:
    controller = _started(SearchOwnerController())
    controller.step(_observation(0.1), now=0.1)

    stale = controller.step(_observation(1.0), now=3.0)

    assert stale.command == VelocityCommand()
    assert stale.reason == "stale_observation"
    assert controller.enabled is True
    assert controller.state == "go_to_last_observed"


def test_collision_contact_stops_every_state() -> None:
    controller = _started(SearchOwnerController())

    hit = controller.step(_observation(0.1, collision=True), now=0.1)

    assert hit.command == VelocityCommand()
    assert hit.reason == "collision_contact"


def test_a_missing_scan_degrades_loudly_rather_than_silently() -> None:
    controller = _started(SearchOwnerController())

    decision = controller.step(_observation(0.1), now=0.1)

    assert decision.degraded.startswith("no_calibrated_scan")
    assert controller.snapshot()["map_available"] is False


# --- semantic packaging -----------------------------------------------------


def test_search_owner_is_a_system_skill_no_planner_can_author() -> None:
    planner_registry = SkillContractRegistry.default(owner_heading_supported=True)
    system_registry = SkillContractRegistry.default(
        owner_heading_supported=True, include_system_skills=True
    )

    assert "SearchOwner" not in planner_registry.names()
    assert "SearchOwner" in system_registry.names()
    assert "SearchOwner" not in SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS
    assert "SearchOwner" in SemanticTaskRuntimeAdapter.EXECUTABLE_SKILLS
    assert "SearchOwner" in SYSTEM_SKILL_NAMES
    assert SYSTEM_SKILL_NAMES == frozenset({"SearchOwner", "ScanBehavior", "SearchEntity"})

    contract = system_registry.get("SearchOwner")
    # The skill runs precisely because the owner is not visible, so it must
    # not inherit the owner_visible precondition every other owner skill has.
    assert "owner_visible" not in contract.required_preconditions
    assert "lidar_fresh" in contract.required_preconditions
    assert contract.success_facts == frozenset({"owner_reacquired"})


def test_a_search_plan_compiles_the_same_safety_invariants_as_any_motion() -> None:
    registry = SkillContractRegistry.default(
        owner_heading_supported=True, include_system_skills=True
    )
    plan = compile_plan_contracts(
        PlanIR(
            schema_version=1,
            task_id="parcel-owner-search-1",
            plan_revision=1,
            source_turn_id="owner-lost-1",
            goal=GoalSpec(relation="reacquire", target=GoalTarget(kind="owner")),
            invariants=(),
            steps=(
                PlanStep(
                    step_id="step_1",
                    skill="SearchOwner",
                    arguments=FrozenDict({}),
                    success=SuccessCondition(fact="owner_reacquired", target="owner"),
                ),
            ),
        ),
        registry,
    )

    invariants = PlanValidator(registry)._effective_invariants(plan)

    assert "stop_on_stale_perception" in invariants
    assert "keep_collision_margin" in invariants
    assert "yield_to_people" in invariants
    assert "avoid_road_when_not_crossing" in invariants


def _search_adapter(calls: dict, *, wired: bool = True) -> SemanticTaskRuntimeAdapter:
    def record(name):
        def _inner(*args):
            calls.setdefault(name, []).append(args)
            return f"{name} ok"

        return _inner

    return SemanticTaskRuntimeAdapter(
        navigate=record("navigate"),
        follow_formation=record("follow_formation"),
        spatial_behavior=record("spatial_behavior"),
        hold=record("hold"),
        vocalize=record("vocalize"),
        search_owner=record("search_owner") if wired else None,
    )


def _search_request() -> DispatchRequest:
    return DispatchRequest(
        task_id="parcel-owner-search-1",
        plan_revision=1,
        step_id="step_1",
        attempt=1,
        skill="SearchOwner",
        arguments=FrozenDict({}),
        success=SuccessCondition(fact="owner_reacquired", target="owner"),
        resources=("base", "attention"),
        timeout_s=60.0,
        recovery_action=None,
    )


def _search_state(**overrides) -> SemanticRuntimeState:
    defaults = {
        "snapshot_id": "snap-1",
        "search_enabled": True,
        "search_state": "sweep",
        "control_feedback_fresh": True,
    }
    defaults.update(overrides)
    return SemanticRuntimeState(**defaults)


def test_search_owner_dispatch_requires_a_wired_callback() -> None:
    with pytest.raises(RuntimeError, match="no runtime callback"):
        _search_adapter({}, wired=False).dispatch(_search_request(), now=1.0)


def test_completion_needs_the_controller_and_the_track_to_agree() -> None:
    calls: dict = {}
    adapter = _search_adapter(calls)
    assert adapter.dispatch(_search_request(), now=1.0) is None
    assert calls["search_owner"] == [()]

    (progress,) = adapter.poll(_search_state(), now=2.0)
    assert progress.status == "in_progress"

    (done,) = adapter.poll(
        _search_state(
            search_enabled=False,
            search_state="reacquired",
            owner_track_confidence=0.85,
        ),
        now=3.0,
    )
    assert done.status == "succeeded"
    assert done.detail_code == "owner_reacquired_verified"
    fact = next(item for item in done.verified_facts if item.fact == "owner_reacquired")
    assert fact.target == "owner"
    assert fact.confidence == pytest.approx(0.85)


def test_a_controller_claim_without_a_confident_track_is_not_success() -> None:
    adapter = _search_adapter({})
    adapter.dispatch(_search_request(), now=1.0)

    (result,) = adapter.poll(
        _search_state(
            search_enabled=False,
            search_state="reacquired",
            owner_track_confidence=OWNER_TRACK_CONFIDENCE_MIN - 0.1,
        ),
        now=2.0,
    )

    assert result.status == "failed"
    assert result.detail_code == "owner_reacquisition_not_confirmed_by_track"
    assert result.verified_facts == ()


def test_giving_up_fails_the_step_and_claims_nothing() -> None:
    adapter = _search_adapter({})
    adapter.dispatch(_search_request(), now=1.0)

    (result,) = adapter.poll(
        _search_state(
            search_enabled=False,
            search_state="gave_up",
            search_reason="search_budget_exhausted",
        ),
        now=2.0,
    )

    assert result.status == "failed"
    assert result.detail_code == "search_budget_exhausted"
    assert result.verified_facts == ()


# --- the deterministic runtime trigger --------------------------------------


class _Backend:
    name = "search-runtime-test"

    def __init__(self) -> None:
        self.moves: list[VelocityCommand] = []

    def observe(self) -> SimObservation:
        return _observation(time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        self.moves.append(command)

    def stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del transcript, tools, context
        return AgentDecision("no planning in this test")


def _runtime(tmp_path: Path) -> RobotRuntime:
    path = tmp_path / "search-runtime.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
  brain:
    enabled: true
    skills: [NavigateTo, FollowFormation, OrbitOwner, MoveRelative, Hold, Vocalize]
owner_search:
  lost_timeout_s: 3.0
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="test",
        ),
    )


class _Lost:
    state = "lost"


def _seed_perception(runtime: RobotRuntime) -> None:
    """Give the runtime the fresh camera/LiDAR frame admission requires."""

    observation = runtime.backend.observe()
    with runtime._lock:
        runtime._observation = observation
    if runtime._control_state_source is not None:
        runtime._control_state_source.update_observation(observation)


def test_a_lost_owner_proposes_search_only_after_the_timeout(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        _seed_perception(runtime)
        seen = time.monotonic()
        runtime._last_confident_owner = (4.0, 0.0, seen)

        runtime._maybe_trigger_owner_search(_Lost(), seen)
        runtime._maybe_trigger_owner_search(_Lost(), seen + 2.0)
        assert runtime.task_executive.snapshot()["tasks"] == []

        runtime._maybe_trigger_owner_search(_Lost(), seen + 3.5)

        (task,) = runtime.task_executive.snapshot()["tasks"]
        assert task["task_id"] == "parcel-owner-search-1"
        assert task["task_class"] == "system"
        # The deterministic proposal is a plan like any other: it goes through
        # validation and the executive rather than poking the controller.
        assert runtime.search.enabled is False
    finally:
        runtime.close()


def test_a_recovered_owner_cancels_the_pending_trigger(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime._last_confident_owner = (4.0, 0.0, time.monotonic())
        now = time.monotonic()

        runtime._maybe_trigger_owner_search(_Lost(), now)

        class _Tracking:
            state = "tracking"

        runtime._maybe_trigger_owner_search(_Tracking(), now + 1.0)
        runtime._maybe_trigger_owner_search(_Lost(), now + 4.0)

        assert runtime.task_executive.snapshot()["tasks"] == []
    finally:
        runtime.close()


def test_no_confident_last_position_holds_instead_of_searching(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime._last_confident_owner = None
        now = time.monotonic()
        runtime._maybe_trigger_owner_search(_Lost(), now)

        runtime._maybe_trigger_owner_search(_Lost(), now + 4.0)

        assert runtime.task_executive.snapshot()["tasks"] == []
    finally:
        runtime.close()


def test_the_dispatch_starts_the_controller_from_the_loss_point(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime._last_confident_owner = (4.0, -1.0, time.monotonic())

        runtime._start_brain_owner_search()

        assert runtime.search.enabled is True
        assert runtime.search.state == "go_to_last_observed"
        snapshot = runtime.search.snapshot()
        assert (snapshot["last_observed_x_m"], snapshot["last_observed_y_m"]) == (4.0, -1.0)
        assert runtime.snapshot()["owner_search"]["state"] == "go_to_last_observed"
    finally:
        runtime.close()


def test_the_full_loop_dispatches_searches_and_verifies_reacquisition(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        _seed_perception(runtime)
        seen = time.monotonic()
        runtime._last_confident_owner = (4.0, 0.0, seen)
        runtime._maybe_trigger_owner_search(_Lost(), seen)
        runtime._maybe_trigger_owner_search(_Lost(), seen + 3.5)

        runtime._step_brain()
        assert runtime.semantic_tasks.active()[0].request.skill == "SearchOwner"
        assert runtime.search.enabled is True

        # The owner walks back into a confident camera track: the controller
        # terminates, and the same track grounds the verified fact.
        found = _observation(
            time.monotonic(),
            owner_visible=True,
            owner_x=4.2,
            confidence=0.9,
        )
        with runtime._lock:
            runtime._observation = found
        runtime._step_search(found)
        assert runtime.search.state == "reacquired"

        runtime._step_brain()

        (task,) = runtime.task_executive.snapshot()["tasks"]
        assert task["state"] == "succeeded"
        assert task["last_detail"] == "owner_reacquired_verified"
    finally:
        runtime.close()


def test_giving_up_says_so_out_loud_and_holds(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        _seed_perception(runtime)
        runtime._last_confident_owner = (4.0, 0.0, time.monotonic())
        runtime._start_brain_owner_search()
        # Rewind the search clock past the budget rather than waiting 45 s.
        runtime.search._started_at -= runtime.search.config.max_search_s + 1.0

        runtime._step_search(_observation(time.monotonic()))

        assert runtime.search.state == "gave_up"
        chat = runtime.snapshot()["chat"]
        assert any("I lost you" in str(item.get("text", "")) for item in chat)
        assert runtime.arbiter.snapshot()["active_source"] is None
    finally:
        runtime.close()


def test_emergency_stop_ends_an_active_search(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime._last_confident_owner = (4.0, 0.0, time.monotonic())
        runtime._start_brain_owner_search()

        runtime.emergency_stop()

        assert runtime.search.enabled is False
        assert runtime.search.state == "idle"
    finally:
        runtime.clear_emergency_stop()
        runtime.close()
