"""Card W4: dynamic-agent costs in `grid_v1` and the outgoing-command TTC gate.

The safety claim these tests back is narrow and explicit: the TTC gate only
ever *reduces* an already admitted command, and neither `collision.py` nor
`reactive_safety.py` changes to make that true. The last test in this file
asserts that second half against git directly.
"""

from __future__ import annotations

import math
import subprocess
import time
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
import yaml

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import (
    DynamicAgentTrack,
    OwnerTrack,
    RobotPose,
    SimObservation,
)
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.navigation.base import GoalPose, Mission, ModelSpec, NavObservation
from parcel_robot.navigation.dynamic_layer import (
    AgentTrack,
    DynamicAgentCostConfig,
    TimeToCollisionConfig,
    merged_cost_mask,
    minimum_time_to_collision_s,
    tracks_from_payload,
)
from parcel_robot.navigation.grid_navigator import GridNavigator
from parcel_robot.navigation.grid_planner import LidarScan, Pose2D, RollingGridPlanner
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]


# --- configuration ----------------------------------------------------------


def test_unknown_dynamic_agent_keys_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown grid_v1 dynamic_agents settings"):
        DynamicAgentCostConfig.from_mapping({"weight_m": 2.0})


def test_the_owner_may_never_be_avoided_harder_than_a_stranger() -> None:
    with pytest.raises(ValueError, match="owner_weight must not exceed weight"):
        DynamicAgentCostConfig(owner_weight=3.0, weight=1.0)


def test_unknown_ttc_keys_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown safety.time_to_collision settings"):
        TimeToCollisionConfig.from_mapping({"brake_seconds": 2.0})


def test_ttc_thresholds_are_ordered() -> None:
    with pytest.raises(ValueError, match="stop_s must be below brake_s"):
        TimeToCollisionConfig(stop_s=3.0, brake_s=2.0)
    with pytest.raises(ValueError, match="min_scale must be within"):
        TimeToCollisionConfig(min_scale=1.0)
    with pytest.raises(TypeError, match="enabled must be a boolean"):
        TimeToCollisionConfig.from_mapping({"enabled": 1})


def test_the_shipped_config_blocks_load() -> None:
    robot = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    grid = yaml.safe_load(
        (REPO / "configs" / "navigation" / "models" / "grid.yaml").read_text(encoding="utf-8")
    )

    ttc = TimeToCollisionConfig.from_mapping(robot["safety"]["time_to_collision"])
    costs = DynamicAgentCostConfig.from_mapping(grid["controller"]["dynamic_agents"])

    assert ttc.enabled is True
    assert costs.enabled is True
    assert costs.owner_weight < costs.weight


def test_a_malformed_track_payload_is_rejected_not_guessed() -> None:
    with pytest.raises(ValueError, match="entry 0 is malformed"):
        tracks_from_payload([{"x": 1.0, "y": 2.0}])
    with pytest.raises(ValueError, match="entry 0 is not finite"):
        tracks_from_payload([{"x": float("nan"), "y": 0.0, "vx": 0.0, "vy": 0.0}])


# --- the cost mask ----------------------------------------------------------


def _query(points: list[tuple[float, float]]) -> np.ndarray:
    return np.asarray(points, dtype=float)


def test_the_mask_is_zero_when_disabled() -> None:
    costs = merged_cost_mask(
        config=DynamicAgentCostConfig(enabled=False),
        agent_tracks=[AgentTrack(x=1.0, y=0.0, vx=0.0, vy=0.0)],
        owner_tracks=[],
        cell_centers_xy=_query([(1.0, 0.0)]),
        robot_xy=(0.0, 0.0),
    )

    assert float(costs[0]) == 0.0


def test_the_mask_penalizes_the_future_corridor_not_just_the_body() -> None:
    config = DynamicAgentCostConfig(enabled=True)
    # Pedestrian at (2, -2) walking +y at 1 m/s crosses (2, 0) in two seconds.
    tracks = [AgentTrack(x=2.0, y=-2.0, vx=0.0, vy=1.0)]

    costs = merged_cost_mask(
        config=config,
        agent_tracks=tracks,
        owner_tracks=[],
        cell_centers_xy=_query([(2.0, 0.0), (2.0, 5.0)]),
        robot_xy=(0.0, 0.0),
    )

    assert float(costs[0]) > 0.0
    assert float(costs[1]) == pytest.approx(0.0, abs=1e-6)


def test_the_owner_lobe_is_weaker_than_a_stranger_lobe() -> None:
    config = DynamicAgentCostConfig(enabled=True)
    track = AgentTrack(x=2.0, y=0.0, vx=0.0, vy=0.0)
    query = _query([(2.0, 0.0)])

    stranger = merged_cost_mask(
        config=config,
        agent_tracks=[track],
        owner_tracks=[],
        cell_centers_xy=query,
        robot_xy=(0.0, 0.0),
    )
    owner = merged_cost_mask(
        config=config,
        agent_tracks=[],
        owner_tracks=[track],
        cell_centers_xy=query,
        robot_xy=(0.0, 0.0),
    )

    assert 0.0 < float(owner[0]) < float(stranger[0])


def test_cells_outside_the_local_window_are_never_scored() -> None:
    config = DynamicAgentCostConfig(enabled=True, window_radius_m=3.0)

    costs = merged_cost_mask(
        config=config,
        agent_tracks=[AgentTrack(x=10.0, y=0.0, vx=0.0, vy=0.0)],
        owner_tracks=[],
        cell_centers_xy=_query([(10.0, 0.0)]),
        robot_xy=(0.0, 0.0),
    )

    assert float(costs[0]) == 0.0


# --- the planner detour -----------------------------------------------------


def _open_scan() -> LidarScan:
    count = 180
    return LidarScan(
        ranges_m=(12.0,) * count,
        angle_min_rad=-math.pi,
        angle_increment_rad=2.0 * math.pi / count,
        range_min_m=0.05,
        range_max_m=12.0,
    )


def _cost_layer(planner: RollingGridPlanner, tracks: list[AgentTrack]) -> np.ndarray:
    """Build the layer exactly as the navigator does, with the shipped weights."""

    size = planner.config.grid_size_cells
    costs = merged_cost_mask(
        config=DynamicAgentCostConfig(enabled=True, window_radius_m=12.0),
        agent_tracks=tracks,
        owner_tracks=[],
        cell_centers_xy=planner.grid.cell_centers_xy(),
        robot_xy=(0.0, 0.0),
    )
    return costs.reshape(size, size)


def _worst_exposure(waypoints: tuple, tracks: list[AgentTrack]) -> float:
    """Peak predicted-occupancy cost anywhere along a route, densely sampled."""

    from parcel_robot.navigation.dynamic_costs import agent_cost_at

    dense: list[tuple[float, float]] = []
    for start, end in pairwise(waypoints):
        steps = max(2, int(math.dist(start, end) / 0.05))
        for index in range(steps + 1):
            fraction = index / steps
            dense.append(
                (
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                )
            )
    return float(agent_cost_at(tracks, np.asarray(dense)).max())


def test_the_route_leaves_a_crossing_pedestrians_future_corridor() -> None:
    pose = Pose2D(0.0, 0.0, 0.0)
    goal = (6.0, 0.0)
    # Pedestrian at (3, -1.2) walking north at 1 m/s: their rollout sweeps
    # straight across the direct route, which is empty on the static map.
    tracks = [AgentTrack(x=3.0, y=-1.2, vx=0.0, vy=1.0, radius_m=0.35)]

    static = RollingGridPlanner()
    static.update(pose, _open_scan())
    static_plan = static.plan(pose, goal)

    dynamic = RollingGridPlanner()
    dynamic.update(pose, _open_scan())
    dynamic.set_dynamic_cost_layer(_cost_layer(dynamic, tracks))
    dynamic_plan = dynamic.plan(pose, goal)

    assert static_plan.usable and dynamic_plan.usable
    # The static planner drives straight down y = 0, through the corridor.
    assert max(abs(point[1]) for point in static_plan.waypoints_world) < 0.2
    # After weight-normalized costs (arbitration 2026-08-04) the corridor is
    # still clearly expensive relative to free space, just no longer a flat 1.0.
    assert _worst_exposure(static_plan.waypoints_world, tracks) > 0.5
    # The dynamic planner detours clear of it.
    assert dynamic_plan.waypoints_world != static_plan.waypoints_world
    assert _worst_exposure(dynamic_plan.waypoints_world, tracks) < 0.25


def test_which_side_the_detour_takes_is_not_socially_adjudicated() -> None:
    """A documented limitation, pinned so W9 cannot mistake it for a win.

    The chosen side is geometric, not social: with the pedestrian south of the
    goal line the shorter free path is north, including when the pedestrian is
    stationary (no rollout / no decay). Lookahead decay does *not* make
    front-passing cheaper — measured behind costs are lower at equal range.
    Expressing a true "pass behind" preference needs the robot's arrival time
    in the cost (`query_t`), which this card does not add. See U13 (corrected).
    """

    pose = Pose2D(0.0, 0.0, 0.0)
    tracks = [AgentTrack(x=3.0, y=-1.2, vx=0.0, vy=1.0, radius_m=0.35)]
    planner = RollingGridPlanner()
    planner.update(pose, _open_scan())
    planner.set_dynamic_cost_layer(_cost_layer(planner, tracks))

    plan = planner.plan(pose, (6.0, 0.0))

    # Northbound pedestrian, and the route goes north too: in front, not behind.
    assert max(point[1] for point in plan.waypoints_world) > 1.0
    assert min(point[1] for point in plan.waypoints_world) > -0.1


def test_the_cost_layer_can_never_open_a_route_hard_inflation_closed() -> None:
    pose = Pose2D(0.0, 0.0, 0.0)
    planner = RollingGridPlanner()
    planner.update(pose, _open_scan())
    blocked_before = planner.grid.inflated_occupied_mask().copy()

    planner.set_dynamic_cost_layer(_cost_layer(planner, [AgentTrack(3.0, 0.0, 0.0, 0.0)]))

    assert np.array_equal(planner.grid.inflated_occupied_mask(), blocked_before)


def test_a_bad_cost_layer_is_refused() -> None:
    planner = RollingGridPlanner()
    size = planner.config.grid_size_cells
    with pytest.raises(ValueError, match="must be non-negative"):
        planner.set_dynamic_cost_layer(np.full((size, size), -1.0))
    with pytest.raises(ValueError, match="must be finite"):
        planner.set_dynamic_cost_layer(np.full((size, size), np.inf))
    with pytest.raises(ValueError, match="must have shape"):
        planner.set_dynamic_cost_layer(np.zeros((4, 4)))


def test_cell_centres_line_up_with_the_single_cell_accessor() -> None:
    planner = RollingGridPlanner()
    planner.update(Pose2D(1.3, -2.7, 0.0), _open_scan())
    size = planner.config.grid_size_cells
    centers = planner.grid.cell_centers_xy().reshape(size, size, 2)

    for cell in ((0, 0), (5, 11), (size - 1, size - 1)):
        assert tuple(centers[cell[1], cell[0]]) == pytest.approx(
            planner.grid.local_cell_center(cell)
        )


# --- navigator wiring -------------------------------------------------------


def _grid_navigator(**dynamic) -> GridNavigator:
    spec = ModelSpec(id="grid_v1", type="grid", version="1.0.0")
    return GridNavigator(spec, dynamic_agents=dynamic or None)


def _nav_observation(agents: tuple[dict[str, float], ...] = ()) -> NavObservation:
    count = 180
    return NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=0.0,
        lidar=(12.0,) * count,
        extras={
            "lidar_angle_min_rad": -math.pi,
            "lidar_angle_increment_rad": 2.0 * math.pi / count,
            "lidar_range_min_m": 0.05,
            "lidar_range_max_m": 12.0,
            "dynamic_agents": agents,
        },
    )


def test_a_typo_in_the_model_dynamic_block_fails_construction() -> None:
    spec = ModelSpec(id="grid_v1", type="grid", version="1.0.0")
    with pytest.raises(ValueError, match="unknown grid_v1 dynamic_agents settings"):
        GridNavigator(spec, dynamic_agents={"enabled": True, "wieght": 2.0})


def test_the_navigator_reports_when_the_layer_is_live() -> None:
    navigator = _grid_navigator(enabled=True)
    mission = Mission(directive="go", goal=GoalPose(x=6.0, y=0.0))
    navigator.reset(mission)

    navigator.act(_nav_observation(), mission)
    assert navigator.dynamic_cost_active is False

    navigator.act(
        _nav_observation(({"x": 3.0, "y": -1.0, "vx": 0.0, "vy": 1.0, "radius_m": 0.35},)),
        mission,
    )
    assert navigator.dynamic_cost_active is True
    assert navigator._planner.dynamic_cost_layer is not None


def test_a_disabled_model_never_installs_a_layer() -> None:
    navigator = _grid_navigator(enabled=False)
    mission = Mission(directive="go", goal=GoalPose(x=6.0, y=0.0))
    navigator.reset(mission)

    navigator.act(
        _nav_observation(({"x": 3.0, "y": -1.0, "vx": 0.0, "vy": 1.0, "radius_m": 0.35},)),
        mission,
    )

    assert navigator.dynamic_cost_active is False
    assert navigator._planner.dynamic_cost_layer is None


def test_a_malformed_payload_degrades_to_static_planning_loudly(caplog) -> None:
    navigator = _grid_navigator(enabled=True)
    mission = Mission(directive="go", goal=GoalPose(x=6.0, y=0.0))
    navigator.reset(mission)

    with caplog.at_level("WARNING"):
        navigator.act(_nav_observation(({"x": 3.0},)), mission)

    assert navigator.dynamic_cost_active is False
    assert "dynamic agent costs disabled this tick" in caplog.text


# --- the TTC gate ------------------------------------------------------------


def test_the_ramp_scales_down_and_never_up() -> None:
    config = TimeToCollisionConfig(enabled=True, brake_s=2.0, stop_s=0.8)

    assert config.scale_for(math.inf) == 1.0
    assert config.scale_for(5.0) == 1.0
    assert config.scale_for(1.4) == pytest.approx(0.5)
    assert config.scale_for(0.8) == 0.0
    assert config.scale_for(0.0) == 0.0
    for ttc in (0.0, 0.5, 1.0, 1.5, 2.0, 10.0, math.inf):
        assert 0.0 <= config.scale_for(ttc) <= 1.0


def test_an_approaching_agent_produces_a_finite_time_to_collision() -> None:
    config = TimeToCollisionConfig(enabled=True)

    ttc = minimum_time_to_collision_s(
        config=config,
        tracks=[AgentTrack(x=2.0, y=0.0, vx=-1.0, vy=0.0)],
        robot_xy=(0.0, 0.0),
        robot_v=(0.5, 0.0),
    )

    assert math.isfinite(ttc)
    assert 0.0 < ttc < config.brake_s


def test_a_receding_agent_is_never_braked_for() -> None:
    config = TimeToCollisionConfig(enabled=True)

    ttc = minimum_time_to_collision_s(
        config=config,
        tracks=[AgentTrack(x=2.0, y=0.0, vx=2.0, vy=0.0)],
        robot_xy=(0.0, 0.0),
        robot_v=(0.5, 0.0),
    )

    assert ttc == math.inf
    assert config.scale_for(ttc) == 1.0


def test_a_crossing_agent_is_caught_only_while_the_paths_intersect() -> None:
    config = TimeToCollisionConfig(enabled=True)
    crossing = AgentTrack(x=1.2, y=-1.2, vx=0.0, vy=1.0)

    on_course = minimum_time_to_collision_s(
        config=config,
        tracks=[crossing],
        robot_xy=(0.0, 0.0),
        robot_v=(1.0, 0.0),
    )
    stopped = minimum_time_to_collision_s(
        config=config,
        tracks=[crossing],
        robot_xy=(0.0, 0.0),
        robot_v=(0.0, 0.0),
    )

    assert math.isfinite(on_course)
    # Standing still takes the robot out of this particular crossing path.
    assert stopped == math.inf


def test_a_disabled_gate_reports_no_contact() -> None:
    assert (
        minimum_time_to_collision_s(
            config=TimeToCollisionConfig(enabled=False),
            tracks=[AgentTrack(x=0.4, y=0.0, vx=-1.0, vy=0.0)],
            robot_xy=(0.0, 0.0),
            robot_v=(1.0, 0.0),
        )
        == math.inf
    )


# --- the gate inside the runtime --------------------------------------------


class _Backend:
    name = "dynamic-layer-runtime"

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            backend=self.name,
        )

    def move(self, command: VelocityCommand) -> None:
        del command

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


def _runtime(tmp_path: Path, *, ttc: str = "enabled: true") -> RobotRuntime:
    path = tmp_path / "dynamic-layer.yaml"
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
safety:
  time_to_collision:
    {ttc}
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


def _closing(agent_vx: float = -1.5) -> SimObservation:
    return SimObservation(
        timestamp=time.monotonic(),
        robot=RobotPose(x=0.0, y=0.0, yaw=0.0),
        owner=OwnerTrack(),
        dynamic_agents=(
            DynamicAgentTrack(
                agent_id="ped-1",
                kind="pedestrian",
                x=1.4,
                y=0.0,
                vx=agent_vx,
                vy=0.0,
                radius_m=0.35,
            ),
        ),
        backend="dynamic-layer-runtime",
    )


def test_a_typo_in_the_runtime_ttc_block_fails_startup(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown safety.time_to_collision settings"):
        _runtime(tmp_path, ttc="brake_seconds: 2.0")


def test_the_gate_brakes_a_command_the_geometric_gate_admitted(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        command = VelocityCommand(vx=0.5)
        observation = _closing()

        gated, state = runtime._collision_safe(command, observation)

        assert 0.0 <= gated.vx < command.vx
        assert state in {"slowing", "stopped"}
        assert math.isfinite(runtime._min_time_to_collision_s)
    finally:
        runtime.close()


def test_the_gate_is_inert_when_nothing_is_predicted_to_hit_us(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        command = VelocityCommand(vx=0.5)
        observation = _closing(agent_vx=2.0)

        gated, state = runtime._collision_safe(command, observation)

        assert gated == command
        assert state == "clear"
        assert runtime._min_time_to_collision_s == math.inf
    finally:
        runtime.close()


def test_the_gate_can_only_scale_down(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        for agent_x in (0.8, 1.2, 2.0, 4.0, 8.0):
            observation = SimObservation(
                timestamp=time.monotonic(),
                robot=RobotPose(),
                owner=OwnerTrack(),
                dynamic_agents=(
                    DynamicAgentTrack(
                        agent_id="ped-1",
                        kind="pedestrian",
                        x=agent_x,
                        y=0.0,
                        vx=-1.0,
                        vy=0.0,
                        radius_m=0.35,
                    ),
                ),
                backend="dynamic-layer-runtime",
            )
            command = VelocityCommand(vx=0.4, vyaw=0.3)
            gated, _ = runtime._collision_safe(command, observation)
            assert abs(gated.vx) <= abs(command.vx) + 1e-9
            assert abs(gated.vyaw) <= abs(command.vyaw) + 1e-9
    finally:
        runtime.close()


def test_a_disabled_gate_changes_nothing(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, ttc="enabled: false")
    try:
        command = VelocityCommand(vx=0.5)

        gated, state = runtime._collision_safe(command, _closing())

        assert gated == command
        assert state == "clear"
        assert runtime._min_time_to_collision_s == math.inf
    finally:
        runtime.close()


def test_the_snapshot_exposes_both_halves(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime._collision_safe(VelocityCommand(vx=0.5), _closing())
        navigation = runtime.snapshot()["navigation"]

        assert navigation["dynamic_cost_active"] is False
        assert navigation["time_to_collision_gate"] is True
        assert isinstance(navigation["min_time_to_collision_s"], float)
    finally:
        runtime.close()


# --- the safety-authority claim ----------------------------------------------


def _head_source(path: str) -> str:
    return subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _named_source(source: str, name: str) -> str:
    """Normalised source of one top-level def/class (comments/format stripped)."""

    import ast

    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{name!r} not found")


def _method_source(source: str, class_name: str, method: str) -> str:
    import ast

    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and stmt.name == method:
                    return ast.unparse(stmt)
    raise AssertionError(f"{class_name}.{method} not found")


def _annotated_defaults(source: str, class_name: str) -> dict[str, object]:
    import ast

    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            found: dict[str, object] = {}
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.value is not None
                ):
                    try:
                        found[stmt.target.id] = ast.literal_eval(stmt.value)
                    except ValueError:
                        # A derived (non-literal) default. Its value is checked
                        # against HEAD's literal by the caller.
                        continue
            return found
    raise AssertionError(f"{class_name} not found")


def test_the_reactive_safety_authority_file_is_untouched_on_this_branch() -> None:
    """W4's safety argument rests on this file not changing."""

    guarded = ("src/parcel_robot/navigation/reactive_safety.py",)
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *guarded],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "", (
        "card W4 supplements the geometric gate and must not modify it; "
        f"git reports changes:\n{result.stdout}"
    )


def test_the_collision_gate_behaviour_is_untouched_on_this_branch() -> None:
    """Same W4 claim for `collision.py`, stated behaviourally rather than by diff.

    Lane A (strata 4+5, 2026-08-07) replaced ``CollisionPolicy``'s literal field
    defaults with derivations from the single ``SafetyEnvelope`` authority, so a
    bare ``git status`` check on this file now reports a change that W4's
    argument does not actually care about. What W4 needs is that the *gate* did
    not move, so that is what is asserted here, and more tightly than before:

    * ``apply_collision_brake`` and ``CollisionPolicy.__post_init__`` are
      compared against ``HEAD`` after AST normalisation — any change to the
      braking logic or the validation, however formatted, is red;
    * every threshold the live ``CollisionPolicy`` produces is compared, with
      ``==`` on floats, against the literal that stood in ``HEAD``.

    A pure ``git status`` check could not have caught a re-tuned constant hidden
    behind a derivation; this can.
    """

    from parcel_robot.navigation.collision import CollisionPolicy

    path = "src/parcel_robot/navigation/collision.py"
    head = _head_source(path)
    live = (REPO / path).read_text(encoding="utf-8")

    assert _named_source(live, "apply_collision_brake") == _named_source(
        head, "apply_collision_brake"
    ), "card W4: the collision gate's braking logic must not change"
    assert _method_source(live, "CollisionPolicy", "__post_init__") == _method_source(
        head, "CollisionPolicy", "__post_init__"
    ), "card W4: the collision policy's validation must not change"

    head_defaults = _annotated_defaults(head, "CollisionPolicy")
    policy = CollisionPolicy()
    # Any field still carrying a *literal* default at HEAD is pinned against the
    # live value directly (slow_scale = 0.35, predictive_mode = "stop"): a
    # re-typed literal reddens here.
    for name, expected in head_defaults.items():
        assert getattr(policy, name) == expected, (
            f"card W4: CollisionPolicy.{name} moved from {expected!r} to "
            f"{getattr(policy, name)!r}"
        )
    # Re-pinned 2026-08-09 (Wave-2): the six gate thresholds are no longer
    # literals in collision.py — Lane A (strata 4+5, 2026-08-07) derives them by
    # reference from the single SafetyEnvelope authority, so `_annotated_defaults`
    # (which keeps only ast.literal_eval-able constants) can no longer see them,
    # and the previous `set(head_defaults) >= {...}` guard was committed RED at
    # b75ed05 because it demanded literal defaults the refactor had removed. The
    # guard's INTENT — "catch a re-tuned constant hidden behind a derivation" —
    # is preserved and made STRONGER: the live CollisionPolicy() is pinned
    # against the exact Go2-scale thresholds the SafetyEnvelope derivation
    # produces (person_stop 1.2 m social zone, person_slow 2.5 m comfort band,
    # obstacle_stop 0.6 m floor, obstacle_slow 1.2 m comfort band, slow_scale
    # 0.35, reaction 0.12 s — the values pinned bit-for-bit in
    # tests/test_authority_family_equality.py). A re-tune of any threshold,
    # written as a literal or hidden in the envelope, reddens this. The gate
    # BEHAVIOUR is confirmed untouched by the two AST comparisons above (live ==
    # HEAD for apply_collision_brake and __post_init__). NB the D5 two-authorities
    # gap is separate: this is the CollisionPolicy gate; the runtime robot.yaml
    # obstacle_stop_m (0.65) and navigator stop_distance_m (0.8) are distinct
    # keys tracked by card safety-margin-derivation, not this one.
    assert (policy.person_stop_m, policy.person_slow_m) == (1.2, 2.5)
    assert (policy.obstacle_stop_m, policy.obstacle_slow_m) == (0.6, 1.2)
    assert policy.slow_scale == 0.35
    assert policy.reaction_time_s == 0.12
