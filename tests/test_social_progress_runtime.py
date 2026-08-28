"""Product wiring checks for the shadow-only SOCIAL-PROGRESS-1 observer."""

from __future__ import annotations

import ast
import math
import time
from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.control.models import ControllerStatus, ControlLifecycle
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.social_progress import SocialBlockCauseV1
from parcel_robot.navigation.social_progress_observer import (
    PlannerFactsV1,
    VelocityEvidenceV1,
)
from parcel_robot.runtime import RobotRuntime
from parcel_robot.simulation.headless_city import HeadlessCityWorld

REPO = Path(__file__).resolve().parents[1]


class _Backend:
    name = "social-progress-test"

    def __init__(self, observation: SimObservation) -> None:
        self.observation = observation
        self.moves: list[VelocityCommand] = []
        self.stops = 0

    def observe(self) -> SimObservation:
        return replace(self.observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        self.moves.append(command)

    def stop(self) -> None:
        self.stops += 1

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill


def _observation(*, obstacle_m: float = 10.0) -> SimObservation:
    return SimObservation(
        timestamp=time.monotonic(),
        robot=RobotPose(),
        owner=OwnerTrack(owner_id="owner-test", x=3.0, y=0.0, visible=True),
        nearest_obstacle_m=obstacle_m,
        nearest_obstacle_bearing_rad=0.0,
        lidar_ranges=tuple(obstacle_m for _ in range(9)),
        lidar_angle_min_rad=-0.4,
        lidar_angle_increment_rad=0.1,
        lidar_range_min_m=0.05,
        lidar_range_max_m=10.0,
        backend="fake",
    )


def _config(tmp_path: Path, *, social: str = "") -> Path:
    path = tmp_path / "robot.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
{social}
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


def _audio() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )


def test_default_off_constructs_no_observer_and_adds_no_public_key(tmp_path: Path) -> None:
    runtime = RobotRuntime(
        _config(tmp_path),
        _Backend(_observation()),
        audio_status=_audio(),
    )
    try:
        assert runtime._social_progress is None
        assert "social_progress" not in runtime.snapshot()
        assert not list(tmp_path.glob("**/*social*progress*"))
    finally:
        runtime.close()


def test_default_off_tick_performs_no_social_sampling_observation_or_metric(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = RobotRuntime(
        _config(tmp_path),
        _Backend(_observation()),
        audio_status=_audio(),
    )
    calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        calls.append("social")
        raise AssertionError("default-off tick reached social progress work")

    def duplex(observation: object) -> None:
        del observation
        runtime._stop_event.set()

    try:
        monkeypatch.setattr(runtime, "_social_progress_requested_velocity", forbidden)
        monkeypatch.setattr(runtime, "_observe_social_progress", forbidden)
        monkeypatch.setattr(runtime, "_step_duplex", duplex)
        runtime._control_loop_body()

        assert calls == []
        assert runtime._social_progress_sample_sequence == 0
        assert "SocialProgressObserver" not in runtime.component_metrics.snapshot()
        assert "social_progress" not in runtime.snapshot()
    finally:
        runtime.close()


def test_shadow_tick_samples_observes_and_records_metric(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = RobotRuntime(
        _config(
            tmp_path,
            social="social_progress:\n  enabled: true\n  mode: shadow\n",
        ),
        _Backend(_observation()),
        audio_status=_audio(),
    )
    calls: list[str] = []
    original_sample = runtime._social_progress_requested_velocity
    original_observe = runtime._observe_social_progress

    def sample(*, now: float) -> object:
        calls.append("sample")
        return original_sample(now=now)

    def observe(*, requested: object, now: float) -> None:
        calls.append("observe")
        original_observe(requested=requested, now=now)  # type: ignore[arg-type]

    def duplex(observation: object) -> None:
        del observation
        runtime._stop_event.set()

    try:
        monkeypatch.setattr(runtime, "_social_progress_requested_velocity", sample)
        monkeypatch.setattr(runtime, "_observe_social_progress", observe)
        monkeypatch.setattr(runtime, "_step_duplex", duplex)
        runtime._control_loop_body()

        assert calls == ["sample", "observe"]
        assert runtime._social_progress_sample_sequence == 1
        assert "SocialProgressObserver" in runtime.component_metrics.snapshot()
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "social",
    (
        "social_progress:\n  enabled: true\n  mode: active\n",
        "social_progress:\n  enabled: true\n  mode: shadow\n  enabledd: true\n",
    ),
)
def test_runtime_refuses_non_shadow_or_unknown_social_progress_config(
    tmp_path: Path,
    social: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match="social progress|unknown"):
        RobotRuntime(
            _config(tmp_path, social=social),
            _Backend(_observation()),
            audio_status=_audio(),
        )


def test_shadow_observer_records_pre_final_and_achieved_without_moving_gate(
    tmp_path: Path,
) -> None:
    backend = _Backend(_observation(obstacle_m=0.2))
    runtime = RobotRuntime(
        _config(
            tmp_path,
            social="social_progress:\n  enabled: true\n  mode: shadow\n",
        ),
        backend,
        audio_status=_audio(),
    )
    try:
        observation = backend.observe()
        runtime._observation = observation
        runtime._publish_navigation_snapshot(observation)
        if runtime._control_state_source is not None:
            runtime._control_state_source.update_observation(observation)
        runtime._navigation_directive = "walk forward"
        runtime.submit_motion("navigation", VelocityCommand(vx=0.2), ttl=1.0)

        sampled_at = time.monotonic()
        requested = runtime._social_progress_requested_velocity(now=sampled_at)
        assert requested is not None
        runtime._dispatch_active()
        runtime._observe_social_progress(
            requested=requested,
            now=time.monotonic(),
        )

        # ``_dispatch_active`` submits the accepted target to the control
        # manager; this unit fixture does not start its backend-delivery
        # thread.  The accepted target and the shadow record are therefore the
        # deterministic product-path facts.  If a backend delivery did happen,
        # it must also remain stopped.
        assert runtime._last_sent.vx == 0.0
        assert runtime._last_sent.vy == 0.0
        assert not backend.moves or all(
            command.vx == 0.0 and command.vy == 0.0 for command in backend.moves
        )
        social = runtime.snapshot()["social_progress"]
        latest = social["latest"]
        assert latest["requested_velocity"]["primitive"]["vx_mps"] == pytest.approx(0.2)
        assert latest["final_velocity"]["primitive"]["vx_mps"] == 0.0
        assert latest["decision"]["authorizes_motion"] is False
        assert latest["decision"]["requires_downstream_safety_gate"] is True
        assert runtime._social_progress_error == ""
    finally:
        runtime.close()


def test_enabled_missing_snapshot_is_a_visible_fail_closed_sample(tmp_path: Path) -> None:
    runtime = RobotRuntime(
        _config(
            tmp_path,
            social="social_progress:\n  enabled: true\n  mode: shadow\n",
        ),
        _Backend(_observation()),
        audio_status=_audio(),
    )
    try:
        sampled_at = time.monotonic()
        requested = runtime._social_progress_requested_velocity(now=sampled_at)
        runtime._observe_social_progress(requested=requested, now=time.monotonic())

        assert runtime._social_progress is not None
        latest = runtime._social_progress.snapshot()["latest"]
        assert latest["snapshot_missing"] is True
        assert latest["decision"]["state"] == "hold_uncertain"
        assert latest["decision"]["cause"] == "stale_sensor"
    finally:
        runtime.close()


def test_runtime_normalizes_base_centre_scan_before_corridor_proof(
    tmp_path: Path,
) -> None:
    raw_range_m = 1.30
    ray_count = 65
    observation = replace(
        _observation(),
        nearest_obstacle_m=None,
        nearest_obstacle_bearing_rad=None,
        lidar_ranges=tuple(raw_range_m for _ in range(ray_count)),
        lidar_angle_min_rad=-math.pi,
        lidar_angle_increment_rad=2.0 * math.pi / (ray_count - 1),
        lidar_range_min_m=0.05,
        lidar_range_max_m=raw_range_m,
    )
    runtime = RobotRuntime(
        _config(
            tmp_path,
            social="social_progress:\n  enabled: true\n  mode: shadow\n",
        ),
        _Backend(observation),
        audio_status=_audio(),
    )
    original_navigator = runtime.dog._navigator

    class _DemandingPlanner:
        def snapshot(self) -> dict[str, object]:
            return {
                "mission_status": "running",
                "route_status": "clear",
                "progress_demand": True,
                "has_mission": True,
            }

    try:
        current = replace(observation, timestamp=time.monotonic())
        runtime._publish_navigation_snapshot(current)
        snapshot = runtime.navigation_snapshot()
        assert snapshot is not None
        assert snapshot.traversability.ranges[0] == pytest.approx(0.98)
        assert snapshot.traversability.range_max_m == pytest.approx(0.98)

        runtime.dog._navigator = _DemandingPlanner()
        runtime.submit_motion("navigation", VelocityCommand(vx=0.2), ttl=1.0)
        sampled_at = time.monotonic()
        requested = runtime._social_progress_requested_velocity(now=sampled_at)
        runtime._observe_social_progress(requested=requested, now=sampled_at)

        assert runtime._social_progress is not None
        latest = runtime._social_progress.snapshot()["latest"]
        assert latest["planner"]["progress_demand"] is True
        assert latest["corridor_evidence"] is None
    finally:
        runtime.dog._navigator = original_navigator
        runtime.close()


def test_headless_city_clock_is_normalized_at_ingress_and_still_expires(
    tmp_path: Path,
) -> None:
    """Raw MuJoCo time is not host time; only the live adapter maps it."""

    world = HeadlessCityWorld()
    raw = world.observe()
    assert raw.timestamp == 0.0
    runtime = RobotRuntime(
        _config(
            tmp_path,
            social="social_progress:\n  enabled: true\n  mode: shadow\n",
        ),
        _Backend(_observation()),
        audio_status=_audio(),
    )

    def velocities(now: float) -> dict[str, VelocityEvidenceV1]:
        return {
            name: VelocityEvidenceV1.from_value(
                value,
                source=f"test:{name}",
                sequence=1,
                sample_monotonic_s=now,
            )
            for name, value in (
                ("requested_velocity", VelocityCommand(vx=0.2)),
                ("final_velocity", VelocityCommand(vx=0.2)),
                ("achieved_velocity", VelocityCommand()),
            )
        }

    planner = PlannerFactsV1(
        mission_status="running",
        route_status="clear",
        progress_demand=True,
        has_mission=True,
    )
    try:
        before_ns = time.monotonic_ns()
        runtime._publish_navigation_snapshot(raw)
        after_ns = time.monotonic_ns()
        snapshot = runtime.navigation_snapshot()
        assert snapshot is not None
        assert before_ns <= snapshot.assembled_monotonic_ns <= after_ns
        assert {
            header.capture_monotonic_ns for header in snapshot.headers
        } == {snapshot.assembled_monotonic_ns}
        assert {header.origin for header in snapshot.headers} == {
            EvidenceOrigin.SIMULATION
        }
        assert {header.fixture_label for header in snapshot.headers} == {
            "headless_mujoco_city"
        }
        assert snapshot.health_reasons == ()

        observer = runtime._social_progress
        assert observer is not None
        fresh_now = snapshot.assembled_monotonic_ns / 1_000_000_000.0
        fresh = observer.observe(
            navigation_generation=1,
            now_monotonic_s=fresh_now,
            snapshot=snapshot,
            planner=planner,
            **velocities(fresh_now),
        )
        assert fresh is not None
        assert fresh.decision.cause is not SocialBlockCauseV1.STALE_SENSOR

        stale_now = fresh_now + 0.251
        stale = observer.observe(
            navigation_generation=2,
            now_monotonic_s=stale_now,
            snapshot=snapshot,
            planner=planner,
            **velocities(stale_now),
        )
        assert stale is not None
        assert stale.decision.cause is SocialBlockCauseV1.STALE_SENSOR
    finally:
        runtime.close()


def test_final_evidence_is_one_injected_clock_control_snapshot_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = RobotRuntime(
        _config(
            tmp_path,
            social="social_progress:\n  enabled: true\n  mode: shadow\n",
        ),
        _Backend(_observation()),
        audio_status=_audio(),
    )
    sampled_now = time.monotonic()
    seen_now: list[float | None] = []

    def target_cleared_snapshot(*, now: float | None = None) -> ControllerStatus:
        seen_now.append(now)
        return ControllerStatus(
            lifecycle=ControlLifecycle.IDLE,
            controller="test-controller",
            # Models a target cleared by a watchdog after an earlier accepted
            # command.  Its zero target and absent lineage must stay together.
            target=VelocityCommand(),
            measured=VelocityCommand(vx=0.03),
            target_source=None,
            target_sequence=None,
            command_age_ms=None,
            feedback_age_ms=25.0,
            watchdog_stops=1,
            last_stop_reason="command_watchdog",
        )

    try:
        runtime._last_sent = VelocityCommand(vx=0.41)
        monkeypatch.setattr(runtime.control_manager, "snapshot", target_cleared_snapshot)
        requested = runtime._social_progress_requested_velocity(now=sampled_now)
        runtime._observe_social_progress(requested=requested, now=sampled_now)

        assert runtime._social_progress is not None
        latest = runtime._social_progress.snapshot()["latest"]
        final = latest["final_velocity"]
        assert seen_now == [sampled_now]
        assert final["primitive"]["vx_mps"] == 0.0
        assert final["source"] == "control:none"
        assert final["sequence"] == 0
        assert final["fresh"] is False
        assert latest["achieved_velocity"]["primitive"]["vx_mps"] == pytest.approx(0.03)
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("failure_site", "error_type"),
    (
        ("sample", "KeyError"),
        ("observer", "AttributeError"),
        ("planner", "KeyError"),
    ),
)
def test_shadow_failures_never_skip_dispatch_or_later_loop_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_site: str,
    error_type: str,
) -> None:
    runtime = RobotRuntime(
        _config(
            tmp_path,
            social="social_progress:\n  enabled: true\n  mode: shadow\n",
        ),
        _Backend(_observation()),
        audio_status=_audio(),
    )
    events: list[str] = []
    original_navigator = runtime.dog._navigator

    class _BrokenPlanner:
        def snapshot(self) -> dict[str, object]:
            events.append("planner_failure")
            raise KeyError("planner diagnostic failed")

    def broken_sample(*, now: float) -> None:
        del now
        events.append("sample_failure")
        raise KeyError("sample diagnostic failed\n" + "x" * 1000)

    def broken_observe(*args: object, **kwargs: object) -> None:
        del args
        del kwargs
        events.append("observer_failure")
        raise AttributeError("observer diagnostic failed")

    def dispatch() -> None:
        events.append("dispatch")

    def duplex(observation: object) -> None:
        del observation
        events.append("duplex")
        if events.count("duplex") == 2:
            runtime._stop_event.set()

    try:
        monkeypatch.setattr(runtime, "_dispatch_active", dispatch)
        monkeypatch.setattr(runtime, "_step_duplex", duplex)
        monkeypatch.setattr(
            runtime,
            "_step_whisperer",
            lambda observation: events.append("whisperer"),
        )
        if failure_site == "sample":
            monkeypatch.setattr(runtime, "_social_progress_requested_velocity", broken_sample)
        elif failure_site == "observer":
            assert runtime._social_progress is not None
            monkeypatch.setattr(type(runtime._social_progress), "observe", broken_observe)
        else:
            runtime.dog._navigator = _BrokenPlanner()

        runtime._control_loop_body()

        assert events.count("dispatch") == 2
        assert events.count("duplex") == 2
        assert events.count("whisperer") == 2
        assert events.count(f"{failure_site}_failure") == 2
        assert events.index("dispatch") < events.index("duplex")
        assert events[-1] == "whisperer"
        assert runtime._social_progress_error.startswith(f"{error_type}:")
        assert "\n" not in runtime._social_progress_error
        assert len(runtime._social_progress_error) <= 306
        assert runtime.snapshot()["social_progress"]["last_error"].startswith(f"{error_type}:")
    finally:
        runtime.dog._navigator = original_navigator
        runtime.close()


def test_planner_snapshot_is_read_under_navigation_lock_without_runtime_lock(
    tmp_path: Path,
) -> None:
    runtime = RobotRuntime(
        _config(
            tmp_path,
            social="social_progress:\n  enabled: true\n  mode: shadow\n",
        ),
        _Backend(_observation()),
        audio_status=_audio(),
    )
    original_navigator = runtime.dog._navigator

    class _LockCheckingPlanner:
        def snapshot(self) -> dict[str, object]:
            assert runtime._navigation_lock._is_owned()
            assert not runtime._lock._is_owned()
            return {"route_status": "clear", "progress_demand": False}

    try:
        runtime.dog._navigator = _LockCheckingPlanner()
        facts = runtime._social_progress_planner_facts()
        assert facts.route_status == "clear"
    finally:
        runtime.dog._navigator = original_navigator
        runtime.close()


def test_navigation_demand_without_navigator_is_typed_unavailable(
    tmp_path: Path,
) -> None:
    runtime = RobotRuntime(
        _config(
            tmp_path,
            social="social_progress:\n  enabled: true\n  mode: shadow\n",
        ),
        _Backend(_observation()),
        audio_status=_audio(),
    )
    original_navigator = runtime.dog._navigator
    try:
        with runtime._lock:
            runtime._navigation_directive = "walk beside me"
        runtime.dog._navigator = None
        facts = runtime._social_progress_planner_facts()
        assert facts.progress_demand is True
        assert facts.has_mission is True
        assert facts.mission_status == "unresolved"
        assert facts.route_status == "unavailable"
        assert facts.planner_healthy is False
    finally:
        runtime.dog._navigator = original_navigator
        runtime.close()


def test_observer_call_is_after_dispatch_and_dispatch_body_is_untouched() -> None:
    source = (REPO / "src" / "parcel_robot" / "runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    runtime_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "RobotRuntime"
    )
    loop = next(
        node
        for node in runtime_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_control_loop_body"
    )
    rendered = ast.unparse(loop)
    assert rendered.index("self._dispatch_active()") < rendered.index(
        "self._observe_social_progress"
    )

    observer_source = (
        REPO / "src" / "parcel_robot" / "navigation" / "social_progress_observer.py"
    ).read_text(encoding="utf-8")
    observer_tree = ast.parse(observer_source)
    imports: set[str] = set()
    for node in ast.walk(observer_tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    assert not any(
        name.startswith(prefix)
        for name in imports
        for prefix in (
            "parcel_robot.runtime",
            "parcel_robot.control",
            "parcel_robot.backends",
        )
    )
    calls = {
        node.func.attr
        for node in ast.walk(observer_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not calls.intersection(
        {
            "set_target",
            "submit_motion",
            "move",
            "walk",
            "open",
            "write_text",
            "write_bytes",
        }
    )
