"""Card W4: dynamic-agent costs in `grid_v1` and the outgoing-command TTC gate.

The safety claim these tests back is narrow and explicit: the TTC gate only
ever *reduces* an already admitted command, and neither `collision.py` nor
`reactive_safety.py` changes to make that true. The last test in this file
asserts that second half against git directly.
"""

from __future__ import annotations

import ast
import hashlib
import math
import subprocess
import time
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
import yaml

from parcel_robot.audio.devices import AudioDeviceStatus
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
        # Far-field scan sample: missing scan fails closed (P0-B / S-A2).
        nearest_obstacle_m=10.0,
        nearest_obstacle_bearing_rad=0.0,
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
                nearest_obstacle_m=10.0,
                nearest_obstacle_bearing_rad=0.0,
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

    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{name!r} not found")


def _method_source(source: str, class_name: str, method: str) -> str:
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and stmt.name == method:
                    return ast.unparse(stmt)
    raise AssertionError(f"{class_name}.{method} not found")


def _symbol_source(source: str, symbol: str) -> str:
    """``"name"`` or ``"Class.method"`` -> its AST-normalised source."""

    if "." in symbol:
        class_name, method = symbol.split(".", 1)
        return _method_source(source, class_name, method)
    return _named_source(source, symbol)


def _symbol_digest(source: str, symbol: str) -> str:
    return hashlib.sha256(_symbol_source(source, symbol).encode("utf-8")).hexdigest()


def _annotated_defaults(source: str, class_name: str) -> dict[str, object]:
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


REACTIVE_SAFETY_PATH = "src/parcel_robot/navigation/reactive_safety.py"

#: sha256 of the AST-normalised (``ast.unparse``) source of the reactive-safety
#: authority's load-bearing symbols.
#:
#: Regenerate ONLY with owner authorization, and record why in the batch status
#: doc — that record is the whole point of the ratchet::
#:
#:   PYTHONPATH=src:. .parcel/bin/python -c "
#:   import hashlib, pathlib, sys; sys.path.insert(0,'tests')
#:   from test_dynamic_layer import _symbol_digest, REACTIVE_SAFETY_PATH
#:   src = pathlib.Path(REACTIVE_SAFETY_PATH).read_text()
#:   for s in ('apply_reactive_safety','ReactiveSafetyPolicy.__post_init__',
#:             'ReactiveSafetyPolicy.owner_slow_m','_owner_comfort_band_m',
#:             '_owner_identity_trusted'):
#:       print(repr(s), repr(_symbol_digest(src, s)))"
#: Captured 2026-08-10 (lane E3) from the settled post-E2 working tree. Both
#: values equal commit 6bd945d after AST normalisation.
#:
#: Regeneration log — one line per movement. This log is the record the deleted
#: ``git status --porcelain`` ratchet never produced, and it is why a COMMITTED
#: digest was chosen over a ``HEAD`` comparison: a ``HEAD`` comparison absorbs a
#: change silently the moment it is committed, so nobody has to read it.
#:
#: * ``apply_reactive_safety`` — ``1f46251c…``. Moved between 60ecea2 and
#:   6bd945d (card S-A2's authorized ``input_health`` wiring, which is what this
#:   pin holds) and has not moved since. Lane E2's task_15 follow-up never
#:   touched it.
#: * ``ReactiveSafetyPolicy.__post_init__`` — ``2be49ad0…``. Net-unchanged from
#:   6bd945d, but it did NOT sit still: lane E2 added a symmetric person-clearance
#:   floor (``person_stop_m`` may not undercut
#:   ``SafetyEnvelope.person_stop(0.0)``), this ratchet reddened on it unprompted
#:   and named the symbol, the pin was regenerated to ``4c07dc07…`` after reading
#:   the diff — and E2 then REVERTED the guard (the legacy ``robot.yaml`` inject
#:   of ``person_stop_m=1.0`` undercuts the derived floor and 33 tests failed on
#:   it), which reddened the ratchet a second time and returned the pin here.
#:   Both movements were caught, read, and recorded rather than absorbed; see
#:   ``scrum/20260809/task_15/E3_EVAL_INTEGRITY_STATUS.md``.
#: * ``ReactiveSafetyPolicy.__post_init__`` — ``2be49ad0…`` -> ``4c07dc07…``,
#:   regenerated 2026-08-10 by lane E5 under EXPLICIT OWNER AUTHORIZATION
#:   ("1. person clearance. Implement your recommendation"). The symmetric
#:   person-clearance floor landed for real this time: ``person_stop_m`` may no
#:   longer undercut ``SafetyEnvelope.person_stop(0.0)``, mirroring the
#:   ``obstacle_stop_m`` floor that was already there. It could land now because
#:   the paired ``robot.yaml`` retune (1.0/2.0 -> 1.2/2.5, all four copies) went
#:   in with it, so no shipped config undercuts the floor any more.
#:   **The regenerated value is bit-identical to the ``4c07dc07…`` E3 captured
#:   during E2's measurement window** — i.e. the guard that finally landed is
#:   AST-identical to the one E2 built and then reverted under rule 2, which is
#:   independent evidence that the pin now names a state that actually exists.
#:   ``apply_reactive_safety`` is UNCHANGED at ``1f46251c…`` across this move
#:   (checked, not assumed): the gate function did not move, only the
#:   constructor's validation. Measurements, the 2x2 attribution for every row
#:   this moved, and the follow stand-off derivation are in
#:   ``scrum/20260809/task_15/E5_PERSON_CLEARANCE_STATUS.md``.
#: * ``apply_reactive_safety`` — ``1f46251c…`` -> ``f52db9c5…``, and
#:   ``ReactiveSafetyPolicy.__post_init__`` — ``4c07dc07…`` -> ``e01bcca9…``,
#:   regenerated 2026-08-11 by lane E6 under EXPLICIT OWNER AUTHORIZATION (the
#:   owner-band separation card written up by E5 §7.1 and declined there under
#:   rule 2). **This is the first authorized change to the gate function itself
#:   in this batch.** The owner branch now gets its OWN comfort band
#:   (``ReactiveSafetyPolicy.owner_slow_m``, derived = ``person_stop_m +
#:   OWNER_STAND_OFF_MARGIN_M`` = the follow controller's stand-off expressed in
#:   the gate's clearance coordinates), granted only to a positively-identified
#:   owner track in a scene with no stranger on the person channel; every other
#:   case FAILS CLOSED to the 2.5 m stranger band. The owner's STOP distance,
#:   the predictive stop, the TTC brake, the orbit gate and the obstacle path
#:   are untouched — the stop ring was re-measured by bisection at three speeds
#:   for both an identified owner and an unidentified person and is the same
#:   number (``tests/test_e6_owner_band.py``).
#:   2x2, with the pre-E6 tree reconstructed by reverse-applying this lane's own
#:   edits: HEAD digests ``1f46251c…`` / ``2be49ad0…`` and pre-E6 digests
#:   ``1f46251c…`` / ``4c07dc07…``, i.e. BOTH outgoing pins matched the state
#:   they named, and this lane's delta is exactly the band separation plus the
#:   band's construction-time guard. FOLLOW_BENCH_V1: ``follow_success`` 6/9 ->
#:   **7/9** with ``min_pedestrian_surface_m`` **0.5300 unchanged** and the
#:   personal-space dwell **2.3 s unchanged**. 9/9 was NOT reached and is not
#:   reachable this way; the factorial that proves it is in
#:   ``scrum/20260809/task_15/E6_OWNER_BAND_STATUS.md``.
#: * Three symbols were ADDED to the pin by the same lane rather than left
#:   outside it: ``ReactiveSafetyPolicy.owner_slow_m`` (the derivation),
#:   ``_owner_comfort_band_m`` (which band, and why) and
#:   ``_owner_identity_trusted`` (who counts as the owner). The gate's safety
#:   decision moved partly into helpers, and a ratchet that watched only the
#:   caller would have been weaker after this change than before it.
#: * ``ReactiveSafetyPolicy.__post_init__`` — ``e01bcca9…`` -> ``c228b5f8…``,
#:   regenerated 2026-08-22 by card P1-E (``scrum/20260822/task_12``) under the
#:   Wave P0/P1 board directive ("reactive_safety *distances* are config and may
#:   move; the *semantics* do not") and the P0 verifier's row A-1
#:   (``scrum/20260822/WAVE_P0_VERIFICATION_FABLE.md``). The ratchet reddened
#:   unprompted, named this symbol, and the pin was regenerated after reading
#:   the diff — it was not deleted or worked around.
#:   **What moved is the SOURCE of one number.** E5's person floor compared the
#:   configured ``person_stop_m`` against ``DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)``
#:   — the SHIPPED social zone, 1.2 m — which made the shipped commissioning
#:   value its own floor: no profile could set an indoor stand-off, and the
#:   0.7 m overlay P0-A wanted did not relax the robot, it stopped it booting.
#:   Now the configured value COMMISSIONS the envelope's social zone
#:   (``SafetyEnvelope.with_person_social_zone``) and the floor underneath is
#:   the authority's named ``PERSON_SOCIAL_ZONE_FLOOR_M`` (0.68 m = the Go2's
#:   ISO/TS-15066 stopping distance at cruise). The refusal is unchanged in
#:   kind — construction-time, fail-closed, naming ``person_stop_m`` AND the
#:   floor — and the obstacle floor now reads the same injected envelope.
#:   **``apply_reactive_safety`` is UNCHANGED at ``f52db9c5…`` across this move
#:   (checked, not assumed), as are ``owner_slow_m``, ``_owner_comfort_band_m``
#:   and ``_owner_identity_trusted``**: the gate function, the owner band and
#:   the identity test carry zero AST-normalised change. Only the constructor's
#:   validation moved. Measurements — including the MOVE-1 owner-standoff arm
#:   re-run (net displacement 0.31 m -> 0.84 m, zero contact) — are in
#:   ``scrum/20260822/task_12/P1E_STATUS.md``.
#: * ``ReactiveSafetyPolicy.__post_init__`` — ``c228b5f8…`` -> ``8c39f4ee…``,
#:   regenerated 2026-08-22 by card DOOR-1 (``scrum/20260822/task_19``) under the
#:   same Wave P0/P1/2 board directive P1-E cited ("reactive_safety *distances*
#:   are config and may move; the *semantics* do not") and the wave-2 design's
#:   DW-4 exit (``scrum/20260822/WAVE2_DESIGN_FABLE.md`` §1). The ratchet
#:   reddened unprompted, named this symbol, and the pin was regenerated after
#:   reading the diff.
#:   **What moved is the SOURCE of one number — the OBSTACLE twin of what P1-E
#:   did one entry up.** The obstacle floor compared the configured
#:   ``obstacle_stop_m`` against ``self.envelope.obstacle_stop_floor_m`` — the
#:   SHIPPED 0.6 m field — which made the shipped envelope its own floor. The
#:   consequence, measured: the FINAL gate is directional, so at any ring at or
#:   above 0.6 m it refuses to translate down every corridor narrower than
#:   ``2*ring*sin(1.15)`` >= 1.10 m, i.e. every interior doorway (0.8-0.9 m), and
#:   no profile could commission its way out. Now the configured value
#:   COMMISSIONS the envelope's obstacle ring
#:   (``SafetyEnvelope.with_obstacle_stop_ring``) and the floor underneath is the
#:   authority's named ``OBSTACLE_STOP_FLOOR_M`` (0.41 m = the Go2's ISO/TS-15066
#:   stopping distance at the APPROACH regime, 0.35 m/s). One check was ADDED
#:   beside the person physics floor: the obstacle ring may not sit inside the
#:   body's own hull ``stop_distance(0.0)``, which binds for an injected wider
#:   envelope. The refusal is unchanged in kind — construction-time, fail-closed,
#:   naming ``obstacle_stop_m`` AND the floor.
#:   **``apply_reactive_safety`` is UNCHANGED at ``f52db9c5…`` across this move
#:   (checked, not assumed), as are ``owner_slow_m`` and ``_owner_comfort_band_m``**.
#:   NOTE for the verifier: ``_owner_identity_trusted`` also reads as drifted on
#:   this working tree — that is card OT-2 (``scrum/20260822/task_17``), which
#:   owns the identity-gate source and regenerates its own pin. DOOR-1 changed
#:   exactly one digest in this dict and touched no other symbol.
#:   **UNCOMMISSIONED**: no robot hardware exists (owner, 2026-08-22), so 0.41 m
#:   is arithmetic over in-tree body constants, not a measured stopping distance.
#:   Measurements are in ``scrum/20260822/task_19/DOOR1_STATUS.md``.
#: * ``_owner_identity_trusted`` — ``5262d3ed…`` -> ``646234a1…``, regenerated
#:   2026-08-22 by card OT-2 (``scrum/20260822/task_17``) under the Wave 2 board
#:   directive and the card's own OWNS ("``reactive_safety`` identity-gate
#:   SOURCE only ... regenerate its pin only with a log entry, as P1-E did").
#:   The ratchet reddened, named exactly this symbol, and the pin was
#:   regenerated after reading the diff.
#:   **What moved is WHAT THE QUESTION IS.** Before: "is ``confidence`` >= 0.65".
#:   That was the right question of a channel PRIOR — the fusion stub's
#:   hard-coded 0.55 (UWB) / 0.70 (vision) trust in whatever supplied pose, and
#:   the mocap simulator's flat 1.0. Card P1-C then made ``confidence`` a
#:   MEASURED SigLIP-2 cosine, on which 0.65 is meaningless: P1-C measured a
#:   STRANGER at 0.9295 against the owner's own enrolled crops, so a 0.65 floor
#:   trusts every person-shaped crop in the room. The predicate now branches on
#:   ``OwnerTrack.identity_source``. A MEASURED identity is judged on the
#:   producer's ``state`` (``confirmed`` only), on whether the producer's
#:   boundary was CALIBRATED against a known non-owner, and on the HEADROOM the
#:   claim had above that boundary (``OWNER_IDENTITY_MARGIN_MIN`` = 0.005,
#:   derived from the 2.02e-4 fp16/CUDA re-enrollment spread P1-C measured) —
#:   never on the number. A CHANNEL PRIOR, including every producer predating
#:   this card (``identity_source`` = ``""``), keeps the pre-OT-2 rule at the
#:   pre-OT-2 constant.
#:   **The direction, measured rather than asserted** (corrected under
#:   verification; the first version of this entry claimed "strictly fewer" and
#:   that is false). Over a 7,650-case enumeration against the pre-OT-2 rule:
#:   **1,314 newly REFUSED, 66 newly GRANTED, 6,270 unchanged.** All 66 are
#:   ``pixel_reid`` + ``confirmed`` + headroom >= 0.005 + a cosine BELOW 0.65 —
#:   a calibrated operating point that sits low (the in-tree fixture encoder
#:   calibrates to 0.639943), where refusing would mean re-importing a
#:   channel-prior number onto the cosine scale. What they buy is the relaxed
#:   comfort BAND; the stop ring is ``person_stop_m`` on both sides. No stop
#:   distance, comfort-band value, predictive stop, TTC brake, orbit gate or
#:   obstacle path is reachable from here.
#:   **``apply_reactive_safety`` is UNCHANGED at ``f52db9c5…`` across this move
#:   (checked, not assumed), as are ``owner_slow_m`` and ``_owner_comfort_band_m``**
#:   — the gate function, the owner band and WHICH band is chosen carry zero
#:   AST-normalised change; only WHO COUNTS AS THE OWNER moved.
#:   ``ReactiveSafetyPolicy.__post_init__`` at ``8c39f4ee…`` is DOOR-1's
#:   concurrent regeneration one entry up and is not this card's; OT-2 changed
#:   exactly one digest in this dict. 648 reactive-safety cases over tracks with
#:   no identity provenance hash byte-identically to the pre-OT-2 tree
#:   (``f16316b3…``). Measurements are in
#:   ``scrum/20260822/task_17/OT2_STATUS.md``.
#:   A4 SPINE (scrum/20260824/task_2) re-froze exactly two of the five digests:
#:   ``apply_reactive_safety`` and ``_owner_comfort_band_m``. The ONLY change to
#:   either body is the observation parameter's annotation, which moved off the
#:   simulator backend type onto the transitional carrier Protocol
#:   (``SimObservation`` -> ``ObservationCarrierV1``) so this module stops
#:   importing ``backends.base`` (audit row K3). Proved by diffing
#:   ``ast.unparse`` of each symbol against HEAD f1a6a92: exactly one changed
#:   line each, the ``def`` line. No threshold, branch, ordering or clearance
#:   moved; the three untouched digests (``__post_init__``, ``owner_slow_m``,
#:   ``_owner_identity_trusted``) are the evidence that nothing else in the
#:   authority shifted. The card's V2 entry point
#:   (``apply_reactive_safety_from_snapshot``) is a STRICTLY stronger wrapper
#:   around this unmodified function, never a replacement for it.
REACTIVE_SAFETY_PIN: dict[str, str] = {
    "apply_reactive_safety": (
        "520211afbd060bfb31362402f9aeb438411367019e7af1cd7cbe62f71ffa484f"
    ),
    "ReactiveSafetyPolicy.__post_init__": (
        "8c39f4eee7eda0090d2d767f06ef82e120959896fb05acb8289ec3d7e78d445a"
    ),
    "ReactiveSafetyPolicy.owner_slow_m": (
        "119af4adb6575f21ebbebe929e77e1e29eba3da345a021a69a2f32959e222f0e"
    ),
    "_owner_comfort_band_m": (
        "b88d9f3544e8bf947372a251337040331f9ef27162d5c5b9411933f15621d764"
    ),
    "_owner_identity_trusted": (
        "646234a120df4b2d54d8b80c00d1ba9b72df681be368e9688571276476a08a77"
    ),
}


def test_the_reactive_safety_authority_is_pinned_not_merely_unmodified() -> None:
    """Card W4's safety-authority ratchet, RE-ARMED (lane E3, 2026-08-10).

    History, because it is the reason this test is shaped the way it is:

    * W4 pinned this file with an unconditional ``git status --porcelain`` check
      (``test_the_reactive_safety_authority_file_is_untouched_on_this_branch``).
    * Card S-A2 in task_15 DELETED that ratchet and replaced it with a behavioural
      test of its own — a self-replacement of a guard by the card the guard was
      watching, which is a rule-4 process breach. After the deletion
      ``grep -rn "git status --porcelain" tests/*.py`` returned nothing repo-wide:
      the safety authority had no file-level ratchet at all.
    * Fable's independent audit caught it
      (``scrum/20260809/task_15/AUDIT_FABLE_INDEPENDENT.md``).

    Re-armed to the STRONGER sibling convention already used by
    ``test_the_collision_gate_behaviour_is_untouched_on_this_branch``: AST
    normalisation, so cosmetic reformatting and comment edits are green and only
    a semantic change is red. Two differences from that sibling, both deliberate:

    * it compares against a COMMITTED digest rather than against ``HEAD``. A
      HEAD comparison silently re-baselines the moment the change is committed —
      the ratchet forgets. A committed pin survives the commit and has to be
      edited by a human, in the diff, on purpose.
    * it covers ``ReactiveSafetyPolicy.__post_init__`` as well as the gate
      function, so a re-tuned threshold hidden behind a derivation is red too.

    The behavioural pins in the next test are kept; they are complementary (they
    catch a value moving through config, this catches the code moving).
    """

    live = (REPO / REACTIVE_SAFETY_PATH).read_text(encoding="utf-8")

    drifted: list[str] = []
    for symbol, pinned in sorted(REACTIVE_SAFETY_PIN.items()):
        actual = _symbol_digest(live, symbol)
        if actual != pinned:
            drifted.append(f"  {symbol}: {actual} != pinned {pinned}")

    assert not drifted, (
        "the reactive-safety authority changed semantically:\n"
        + "\n".join(drifted)
        + "\n\nThis is a ratchet, not a blocker. If the change is intended and "
        "owner-authorized, regenerate REACTIVE_SAFETY_PIN with the command in "
        "its docstring and record the reason in the batch status doc. Do NOT "
        "delete this test to make it pass — that is exactly what card S-A2 did."
    )


def test_the_reactive_safety_pin_ignores_formatting_but_not_semantics() -> None:
    """The two directions the ratchet claims, proven on the live source.

    A pin that reddened on reformatting would be abandoned within a week; a pin
    that stayed green on a re-tuned threshold would be theatre. Both are checked
    against the real file rather than a fixture.
    """

    live = (REPO / REACTIVE_SAFETY_PATH).read_text(encoding="utf-8")
    symbol = "apply_reactive_safety"
    baseline = _symbol_digest(live, symbol)

    # Cosmetic: blank lines, a comment, and a re-wrapped signature. Green.
    reformatted = live.replace(
        "def apply_reactive_safety(",
        "# a comment that changes nothing\ndef apply_reactive_safety(\n",
        1,
    )
    assert _symbol_digest(reformatted, symbol) == baseline, (
        "AST-normalised comparison must ignore comments and line breaks"
    )

    # Semantic: the admitted command is returned unchanged (gate disabled). Red.
    tree = ast.parse(live)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == symbol:
            node.body = ast.parse("return command, 'clear'").body
            break
    else:  # pragma: no cover - the symbol is asserted to exist above
        raise AssertionError(f"{symbol} not found")
    assert _symbol_digest(ast.unparse(tree), symbol) != baseline, (
        "a pass-through gate must move the pin"
    )


def test_the_reactive_safety_authority_gate_behaviour_holds() -> None:
    """W4 geometric-gate behaviour pin; S-A2 may wire input_health into the file.

    W4 cared that the geometric stop/slow surface did not move. S-A2 (task_15)
    is authorized to edit ``reactive_safety.py`` so missing scan fails closed
    via ``input_health``; a bare ``git status`` pin would false-alarm on that
    wiring. Behavioural pins cover the W4 thresholds plus the S-A2 contract.
    """

    from parcel_robot.navigation.reactive_safety import (
        ReactiveSafetyPolicy,
        apply_reactive_safety,
    )

    policy = ReactiveSafetyPolicy()
    assert policy.obstacle_stop_m == 0.65
    assert policy.obstacle_slow_m == 1.2
    assert policy.person_stop_m == 1.2
    assert policy.person_slow_m == 2.5
    assert policy.reaction_time_s == 0.12

    clear = SimObservation(
        timestamp=1.0,
        robot=RobotPose(),
        owner=OwnerTrack(),
        nearest_obstacle_m=10.0,
        nearest_obstacle_bearing_rad=0.0,
        backend="dynamic-layer-runtime",
    )
    admitted, state = apply_reactive_safety(
        VelocityCommand(vx=0.4),
        clear,
        policy=policy,
        now=1.0,
    )
    assert admitted == VelocityCommand(vx=0.4)
    assert state == "clear"

    missing_scan = SimObservation(
        timestamp=1.0,
        robot=RobotPose(),
        owner=OwnerTrack(),
        nearest_obstacle_m=None,
        lidar_obstacles=(),
        backend="dynamic-layer-runtime",
    )
    held, held_state = apply_reactive_safety(
        VelocityCommand(vx=0.4),
        missing_scan,
        policy=policy,
        now=1.0,
    )
    assert held.vx == 0.0 and held.vy == 0.0
    assert held_state == "stopped"

    near = SimObservation(
        timestamp=1.0,
        robot=RobotPose(),
        owner=OwnerTrack(),
        nearest_obstacle_m=0.4,
        nearest_obstacle_bearing_rad=0.0,
        backend="dynamic-layer-runtime",
    )
    stopped, stop_state = apply_reactive_safety(
        VelocityCommand(vx=0.4),
        near,
        policy=policy,
        now=1.0,
    )
    assert stopped.vx == 0.0
    assert stop_state == "stopped"


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
