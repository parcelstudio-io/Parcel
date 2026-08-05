from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mujoco
import numpy as np

from parcel_robot.backends.base import (
    LidarObstacle,
    OwnerTrack,
    RobotPose,
    SemanticObjectTrack,
    SemanticRegionTrack,
    SimObservation,
)
from parcel_robot.city_semantics import extract_city_semantics, visible_city_semantics
from parcel_robot.config import ConfigStore
from parcel_robot.models import VelocityCommand
from parcel_robot.mujoco_lidar import (
    MAX_LIDAR_OBSTACLES,
    ROBOT_FOOTPRINT_RADIUS_M,
    ROBOT_OBSTACLE_HEIGHT_M,
    planar_geom_surface_hit,
    raycast_planar_scan,
    scan_mujoco_lidar,
)
from parcel_robot.navigation.approach import point_in_polygon_with_clearance
from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.follow import FollowOwnerController
from parcel_robot.navigation.goals import navigation_directive_from_text
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    apply_reactive_safety,
)
from parcel_robot.navigation.semantic_map import (
    lidar_payload_from_observation,
    semantic_candidates_from_observation,
)
from parcel_robot.navigation.spatial import (
    SpatialBehaviorConfig,
    SpatialBehaviorController,
    parse_follow_intent,
    parse_spatial_intent,
)

DEFAULT_CITY_SCENE = Path(__file__).with_name("scenes") / "city_block.xml"
DEFAULT_ROBOT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "robot.yaml"
_STATIC_OBSTACLE_PREFIXES = (
    "obstacle_",
    "bldg_",
    "bench_",
    "planter_",
    "tree_",
    "lamp_",
    "signal_",
)


@dataclass(frozen=True)
class HeadlessTraceSample:
    time_s: float
    robot: RobotPose
    command: VelocityCommand
    phase: str
    note: str
    progress: float


@dataclass(frozen=True)
class HeadlessTaskResult:
    directive: str
    status: str
    reason: str
    target_id: str | None
    terminal_relation: str | None
    final_observation: SimObservation
    trace: tuple[HeadlessTraceSample, ...]
    path: tuple[tuple[float, float], ...]
    collision_count: int
    minimum_clearance_m: float
    required_obstacle_clearance_m: float
    semantic_scan_steps: int
    terminal_command: VelocityCommand

    @property
    def succeeded(self) -> bool:
        return self.status in {"arrived", "completed"}

    @property
    def stopped(self) -> bool:
        """Whether the controller stopped before harness cleanup ran."""

        return _is_stopped(self.terminal_command)

    @property
    def timed_out(self) -> bool:
        return self.status == "timed_out"


class HeadlessCityWorld:
    """Deterministic, viewer-free MuJoCo-geometry closed-loop quality rig.

    The world owns simulator geometry and an independent truth oracle. The
    controller-facing :meth:`observe` boundary exposes only the same camera,
    LiDAR, owner-track, and odometry types used by the normal runtime. Base
    motion is deliberately kinematic and advanced with ``mj_forward``; this is
    an outcome regression gate, not a quadruped contact-physics qualification.
    """

    def __init__(
        self,
        scene: str | Path = DEFAULT_CITY_SCENE,
        *,
        control_dt_s: float = 0.1,
        simulation_dt_s: float = 0.01,
        robot_radius_m: float = ROBOT_FOOTPRINT_RADIUS_M,
    ):
        if not math.isfinite(control_dt_s) or control_dt_s <= 0.0:
            raise ValueError("control_dt_s must be positive and finite")
        if not math.isfinite(simulation_dt_s) or simulation_dt_s <= 0.0:
            raise ValueError("simulation_dt_s must be positive and finite")
        if simulation_dt_s > control_dt_s:
            raise ValueError("simulation_dt_s cannot exceed control_dt_s")
        self.scene = Path(scene).expanduser().resolve()
        if not self.scene.is_file():
            raise FileNotFoundError(f"MuJoCo city scene not found: {self.scene}")
        self.model = mujoco.MjModel.from_xml_path(str(self.scene))
        self.data = mujoco.MjData(self.model)
        self.control_dt_s = control_dt_s
        self.simulation_dt_s = simulation_dt_s
        self.robot_radius_m = robot_radius_m
        self._region_specs, self._object_specs = extract_city_semantics(self.model)
        self._canonical_region_specs = copy.deepcopy(self._region_specs)
        self._canonical_object_specs = copy.deepcopy(self._object_specs)
        self._obstacle_geom_ids = self._extract_obstacle_geom_ids()
        # Occlusion-true raycast scan state: robot root body for self-return
        # filtering plus a seeded RNG so headless runs stay deterministic.
        free_joints = [
            j
            for j in range(self.model.njnt)
            if self.model.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE
        ]
        self._robot_body_id = int(self.model.jnt_bodyid[free_joints[0]]) if free_joints else 0
        self._scan_rng = np.random.default_rng(7)
        owner_body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, "owner"
        )
        self._owner_mocap_id = (
            int(self.model.body_mocapid[owner_body_id]) if owner_body_id >= 0 else -1
        )
        self._command = VelocityCommand()
        self._x = 0.0
        self._y = 0.0
        self._z = 0.445
        self._yaw = 0.0
        self._collision_count = 0
        self._in_static_contact = False
        self._minimum_clearance_m = math.inf
        self._path: list[tuple[float, float]] = []
        self.reset()

    @property
    def command(self) -> VelocityCommand:
        return self._command

    @property
    def collision_count(self) -> int:
        return self._collision_count

    @property
    def minimum_clearance_m(self) -> float:
        return self._minimum_clearance_m

    @property
    def path(self) -> tuple[tuple[float, float], ...]:
        return tuple(self._path)

    @property
    def stopped(self) -> bool:
        return (
            abs(self._command.vx) <= 1e-9
            and abs(self._command.vy) <= 1e-9
            and abs(self._command.vyaw) <= 1e-9
        )

    def reset(
        self,
        *,
        robot: tuple[float, float, float] = (0.0, 0.0, 0.0),
        owner: tuple[float, float] | None = None,
        restore_semantics: bool = True,
    ) -> SimObservation:
        if restore_semantics:
            self._region_specs = copy.deepcopy(self._canonical_region_specs)
            self._object_specs = copy.deepcopy(self._canonical_object_specs)
        if self.model.nkey > 0:
            mujoco.mj_resetDataKeyframe(self.model, self.data, 0)
        else:
            mujoco.mj_resetData(self.model, self.data)
        self._x, self._y, self._yaw = (float(value) for value in robot)
        self._z = float(self.data.qpos[2]) if self.model.nq >= 3 else 0.445
        self._command = VelocityCommand()
        self._collision_count = 0
        self._in_static_contact = False
        self._minimum_clearance_m = math.inf
        if self._owner_mocap_id >= 0 and owner is not None:
            self.data.mocap_pos[self._owner_mocap_id, :2] = owner
            self.data.mocap_pos[self._owner_mocap_id, 2] = 0.0
        self._place_robot()
        self.data.time = 0.0
        mujoco.mj_forward(self.model, self.data)
        self._path = [(self._x, self._y)]
        self._minimum_clearance_m = self.truth_minimum_clearance(self._x, self._y)
        return self.observe()

    def apply_placement_overrides(self, placement: dict[str, Any] | None) -> None:
        """Apply episode distractors / removals / pose overrides to semantic specs.

        Geometry in MuJoCo stays put; the perception adapter reads these specs,
        so tier B–E attribution sees the episode's intended world.
        """

        if not placement:
            return
        remove = {
            str(item)
            for item in (placement.get("remove_entities") or [])
            if item is not None
        }
        if remove:
            self._object_specs = [
                item for item in self._object_specs if str(item.get("id")) not in remove
            ]
            self._region_specs = [
                item for item in self._region_specs if str(item.get("id")) not in remove
            ]
        distractors = placement.get("distractors") or {}
        if isinstance(distractors, dict):
            for entity_id, spec in distractors.items():
                if not isinstance(spec, dict):
                    continue
                try:
                    x = float(spec["x"])
                    y = float(spec["y"])
                except (KeyError, TypeError, ValueError):
                    continue
                label = str(spec.get("label") or "bench")
                radius = float(spec.get("radius_m") or 0.7)
                self._object_specs.append(
                    {
                        "id": str(entity_id),
                        "label": label,
                        "position": [x, y, 0.0],
                        "metadata": {
                            "vicinity_radius_m": radius + 1.4,
                            "goal_region": {
                                "kind": "disc",
                                "center": [x, y],
                                "radius_m": radius + 1.4,
                                "anchor_entity": str(entity_id),
                            },
                            "aliases": (),
                        },
                    }
                )
        # Optional direct entity pose overrides (non-distractor keys).
        for key, spec in placement.items():
            if key in {
                "robot",
                "distractors",
                "remove_entities",
                "absent_target",
                "owner_path",
                "pedestrian_distractors",
                "owner",
            }:
                continue
            if not isinstance(spec, dict) or "x" not in spec or "y" not in spec:
                continue
            try:
                x = float(spec["x"])
                y = float(spec["y"])
            except (TypeError, ValueError):
                continue
            for item in self._object_specs:
                if str(item.get("id")) == str(key):
                    item["position"] = [x, y, 0.0]
                    metadata = dict(item.get("metadata") or {})
                    goal = dict(metadata.get("goal_region") or {})
                    if goal.get("kind") == "disc":
                        goal["center"] = [x, y]
                        metadata["goal_region"] = goal
                    item["metadata"] = metadata
            for item in self._region_specs:
                if str(item.get("id")) == str(key) and "polygon" in spec:
                    item["polygon"] = spec["polygon"]

    def apply(self, command: VelocityCommand) -> None:
        values = (command.vx, command.vy, command.vyaw)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("headless city command values must be finite")
        self._command = command

    def stop(self) -> None:
        self._command = VelocityCommand()

    def step(self) -> SimObservation:
        remaining = self.control_dt_s
        while remaining > 1e-9:
            dt = min(self.simulation_dt_s, remaining)
            self._integrate(dt)
            remaining -= dt
        self._path.append((self._x, self._y))
        return self.observe()

    def observe(self) -> SimObservation:
        lidar = self._lidar_obstacles()
        relevant = self._relevant_obstacle(lidar)
        regions, objects = visible_city_semantics(
            self._region_specs,
            self._object_specs,
            robot_x=self._x,
            robot_y=self._y,
            robot_heading=self._yaw,
        )
        owner_x, owner_y = self.owner_position()
        clearance = self.truth_minimum_clearance(self._x, self._y)
        scan = raycast_planar_scan(
            self.model,
            self.data,
            robot_x=self._x,
            robot_y=self._y,
            robot_heading=self._yaw,
            robot_body_id=self._robot_body_id,
            rng=self._scan_rng,
        )
        return SimObservation(
            timestamp=float(self.data.time),
            robot=RobotPose(x=self._x, y=self._y, z=self._z, yaw=self._yaw),
            owner=OwnerTrack(
                owner_id="owner-1",
                x=owner_x,
                y=owner_y,
                visible=True,
                confidence=1.0,
            ),
            nearest_obstacle_m=(relevant.distance_m if relevant else None),
            nearest_obstacle_bearing_rad=(relevant.bearing_rad if relevant else None),
            nearest_obstacle_id=(relevant.obstacle_id if relevant else None),
            lidar_obstacles=tuple(lidar),
            lidar_ranges=scan.ranges_m,
            lidar_angle_min_rad=scan.angle_min_rad,
            lidar_angle_increment_rad=scan.angle_increment_rad,
            lidar_range_min_m=scan.range_min_m,
            lidar_range_max_m=scan.range_max_m,
            semantic_regions=tuple(self._region_track(item) for item in regions),
            semantic_objects=tuple(self._object_track(item) for item in objects),
            collision=clearance <= 0.0,
            backend="headless_mujoco_city",
        )

    def owner_position(self) -> tuple[float, float]:
        if self._owner_mocap_id < 0:
            return 0.0, 0.0
        return (
            float(self.data.mocap_pos[self._owner_mocap_id, 0]),
            float(self.data.mocap_pos[self._owner_mocap_id, 1]),
        )

    def truth_region_polygon(self, region_id: str) -> tuple[tuple[float, float], ...]:
        for item in self._region_specs:
            if str(item["id"]) == region_id:
                return tuple((float(x), float(y)) for x, y in item["polygon"])
        raise KeyError(f"unknown truth region: {region_id}")

    def truth_region_metadata(self, region_id: str) -> dict[str, Any]:
        for item in self._region_specs:
            if str(item["id"]) == region_id:
                return dict(item.get("metadata") or {})
        raise KeyError(f"unknown truth region: {region_id}")

    def truth_object(self, object_id: str) -> tuple[float, float, float]:
        for item in self._object_specs:
            if str(item["id"]) == object_id:
                metadata = item.get("metadata") or {}
                return (
                    float(item["position"][0]),
                    float(item["position"][1]),
                    float(metadata.get("radius_m", 0.0)),
                )
        raise KeyError(f"unknown truth object: {object_id}")

    def truth_object_metadata(self, object_id: str) -> dict[str, Any]:
        for item in self._object_specs:
            if str(item["id"]) == object_id:
                return dict(item.get("metadata") or {})
        raise KeyError(f"unknown truth object: {object_id}")

    def truth_inside_region(
        self,
        point: tuple[float, float],
        region_id: str,
        *,
        clearance_m: float = 0.0,
    ) -> bool:
        return point_in_polygon_with_clearance(
            point,
            self.truth_region_polygon(region_id),
            clearance_m,
        )

    def truth_object_surface_distance(
        self, point: tuple[float, float], object_id: str
    ) -> float:
        x, y, radius = self.truth_object(object_id)
        return math.hypot(point[0] - x, point[1] - y) - radius - self.robot_radius_m

    def truth_minimum_clearance(self, x: float, y: float) -> float:
        if not self._obstacle_geom_ids:
            return math.inf
        clearances = [
            hit.signed_clearance_m
            for geom_id in self._obstacle_geom_ids
            if (
                hit := planar_geom_surface_hit(
                    self.model,
                    self.data,
                    geom_id,
                    robot_x=x,
                    robot_y=y,
                    robot_radius_m=self.robot_radius_m,
                    obstacle_height_m=ROBOT_OBSTACLE_HEIGHT_M,
                )
            )
            is not None
        ]
        return min(clearances, default=math.inf)

    def _integrate(self, dt: float) -> None:
        cosine, sine = math.cos(self._yaw), math.sin(self._yaw)
        proposed_x = self._x + (cosine * self._command.vx - sine * self._command.vy) * dt
        proposed_y = self._y + (sine * self._command.vx + cosine * self._command.vy) * dt
        translating = math.hypot(proposed_x - self._x, proposed_y - self._y) > 1e-12
        proposed_clearance = self.truth_minimum_clearance(proposed_x, proposed_y)
        if translating and proposed_clearance <= 0.0:
            # Edge-detected: one continuous press against an obstacle is one
            # collision event, matching how pedestrian contacts are counted.
            # Counting every blocked 0.01 s substep inflated the eval's
            # hard-collision totals by two orders of magnitude.
            if not self._in_static_contact:
                self._collision_count += 1
                self._in_static_contact = True
        else:
            self._in_static_contact = False
            self._x, self._y = proposed_x, proposed_y
        self._yaw = _wrap(self._yaw + self._command.vyaw * dt)
        self._place_robot()
        self.data.time = float(self.data.time) + dt
        mujoco.mj_forward(self.model, self.data)
        self._minimum_clearance_m = min(
            self._minimum_clearance_m,
            self.truth_minimum_clearance(self._x, self._y),
        )

    def _place_robot(self) -> None:
        if self.model.nq < 7:
            return
        self.data.qpos[:3] = (self._x, self._y, self._z)
        half_yaw = self._yaw * 0.5
        self.data.qpos[3:7] = (math.cos(half_yaw), 0.0, 0.0, math.sin(half_yaw))
        if self.model.nv >= 6:
            self.data.qvel[:6] = 0.0

    def _extract_obstacle_geom_ids(self) -> tuple[int, ...]:
        geom_ids = []
        for geom_id in range(self.model.ngeom):
            name = (
                mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
                or ""
            )
            if name.startswith(_STATIC_OBSTACLE_PREFIXES):
                geom_ids.append(geom_id)
        return tuple(geom_ids)

    def _lidar_obstacles(self) -> list[LidarObstacle]:
        return [
            LidarObstacle(
                distance_m=hit.distance_m,
                bearing_rad=hit.bearing_rad,
                obstacle_id=hit.obstacle_id,
            )
            for hit in scan_mujoco_lidar(
                self.model,
                self.data,
                self._obstacle_geom_ids,
                robot_x=self._x,
                robot_y=self._y,
                robot_heading=self._yaw,
                robot_radius_m=self.robot_radius_m,
                obstacle_height_m=ROBOT_OBSTACLE_HEIGHT_M,
                limit=MAX_LIDAR_OBSTACLES,
            )
        ]

    def _relevant_obstacle(
        self, candidates: list[LidarObstacle]
    ) -> LidarObstacle | None:
        if not candidates:
            return None
        if math.hypot(self._command.vx, self._command.vy) > 1e-6:
            travel_bearing = math.atan2(self._command.vy, self._command.vx)
            directional = [
                item
                for item in candidates
                if abs(_wrap(item.bearing_rad - travel_bearing)) < 1.15
            ]
            if directional:
                return min(directional, key=lambda item: item.distance_m)
        return min(candidates, key=lambda item: item.distance_m)

    @staticmethod
    def _region_track(item: dict[str, Any]) -> SemanticRegionTrack:
        return SemanticRegionTrack(
            region_id=str(item["id"]),
            label=str(item["label"]),
            polygon=tuple((float(x), float(y)) for x, y in item["polygon"]),
            confidence=float(item["confidence"]),
            source=str(item["source"]),
            reachable=bool(item["reachable"]),
            metadata=dict(item.get("metadata") or {}),
        )

    @staticmethod
    def _object_track(item: dict[str, Any]) -> SemanticObjectTrack:
        position = item["position"]
        return SemanticObjectTrack(
            object_id=str(item["id"]),
            label=str(item["label"]),
            position=(float(position[0]), float(position[1]), float(position[2])),
            confidence=float(item["confidence"]),
            source=str(item["source"]),
            reachable=bool(item["reachable"]),
            metadata=dict(item.get("metadata") or {}),
        )


class HeadlessCityQualityHarness:
    """Run production planners against :class:`HeadlessCityWorld` deterministically."""

    def __init__(
        self,
        world: HeadlessCityWorld | None = None,
        *,
        reactive_safety: ReactiveSafetyPolicy | None = None,
        spatial_config: SpatialBehaviorConfig | None = None,
        robot_config: str | Path = DEFAULT_ROBOT_CONFIG,
    ):
        self.world = world or HeadlessCityWorld()
        store = ConfigStore(robot_config)
        self.navigation_config = _navigation_config_from_store(store)
        self.spatial_config = spatial_config or _spatial_config_from_store(store)
        self.reactive_safety = reactive_safety or _reactive_safety_from_store(
            store,
            self.spatial_config,
        )
        control = store.section("control")
        self._settled_linear_speed_mps = float(
            control.get("settled_linear_speed_mps", 0.08)
        )
        self._settled_yaw_speed_rad_s = float(
            control.get("settled_yaw_speed_rad_s", 0.12)
        )
        if any(
            not math.isfinite(value) or value < 0.0
            for value in (
                self._settled_linear_speed_mps,
                self._settled_yaw_speed_rad_s,
            )
        ):
            raise ValueError("headless settled-speed thresholds must be finite and nonnegative")

    def run(self, text: str, *, max_steps: int = 1800) -> HeadlessTaskResult:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if parse_follow_intent(text):
            return self._run_follow(text, max_steps=max_steps)
        spatial_intent = parse_spatial_intent(text)
        if spatial_intent is not None:
            return self._run_spatial(text, max_steps=max_steps)
        directive = navigation_directive_from_text(text)
        if directive is None:
            return self._failure(text, "directive_not_understood")
        return self._run_navigation(text, directive, max_steps=max_steps)

    def _run_navigation(
        self, text: str, directive: str, *, max_steps: int
    ) -> HeadlessTaskResult:
        navigator = DirectiveNavigator.from_config(self.navigation_config)
        mission = navigator.start(directive)
        trace: list[HeadlessTraceSample] = []
        reason = "navigation_step_limit"
        scan_steps = 0
        terminal_status = mission.status
        terminal_command = self.world.command
        required_clearance = self.reactive_safety.obstacle_stop_m
        try:
            for _ in range(max_steps):
                observation = self.world.observe()
                command = navigator.step(
                    _nav_observation(
                        observation,
                        measured_velocity=self.world.command,
                        stop_confirmed=self.world.stopped,
                        settled_linear_speed_mps=self._settled_linear_speed_mps,
                        settled_yaw_speed_rad_s=self._settled_yaw_speed_rad_s,
                    )
                )
                if command.note.startswith("semantic_search_scan"):
                    scan_steps += 1
                requested = (
                    VelocityCommand()
                    if command.stop
                    else VelocityCommand(command.vx, command.vy, command.vyaw)
                )
                velocity, _ = apply_reactive_safety(
                    requested,
                    observation,
                    policy=self.reactive_safety,
                    owner_orbit=False,
                    orbit_radius_m=0.0,
                    now=observation.timestamp,
                    require_fresh_telemetry=False,
                )
                terminal_command = velocity
                trace.append(
                    HeadlessTraceSample(
                        time_s=observation.timestamp,
                        robot=observation.robot,
                        command=velocity,
                        phase=mission.status,
                        note=command.note,
                        progress=0.0,
                    )
                )
                self.world.apply(velocity)
                if (command.stop and mission.status != "verifying") or navigator.done():
                    reason = command.note
                    terminal_status = mission.status
                    break
                self.world.step()
            else:
                mission.status = "failed"
                terminal_status = "timed_out"
        finally:
            self.world.stop()
            navigator.close()
        target_id = (
            str(mission.metadata.get("candidate_id"))
            if mission.metadata.get("candidate_id") is not None
            else (mission.goal.poi_id if mission.goal and mission.goal.poi_id else None)
        )
        relation = mission.semantic_goal.terminal_relation if mission.semantic_goal else None
        return self._result(
            text,
            status=terminal_status,
            reason=reason,
            target_id=target_id,
            terminal_relation=relation,
            trace=trace,
            semantic_scan_steps=scan_steps,
            terminal_command=terminal_command,
            required_obstacle_clearance_m=required_clearance,
        )

    def _run_follow(self, text: str, *, max_steps: int) -> HeadlessTaskResult:
        """Regression-lane owner follow via FollowOwnerController."""

        controller = FollowOwnerController()
        controller.start("direct")
        trace: list[HeadlessTraceSample] = []
        status = "timed_out"
        reason = "follow_step_limit"
        terminal_command = self.world.command
        for _ in range(max_steps):
            observation = self.world.observe()
            decision = controller.step(observation, now=observation.timestamp)
            command, _ = apply_reactive_safety(
                decision.command,
                observation,
                policy=self.reactive_safety,
                owner_orbit=False,
                orbit_radius_m=0.0,
                now=observation.timestamp,
                require_fresh_telemetry=False,
            )
            terminal_command = command
            trace.append(
                HeadlessTraceSample(
                    time_s=observation.timestamp,
                    robot=observation.robot,
                    command=command,
                    phase=decision.state,
                    note=decision.reason,
                    progress=0.0,
                )
            )
            self.world.apply(command)
            # Follow has no natural "done"; treat stable following/holding as success.
            if decision.state in {"following", "holding", "holding_behind"}:
                status = "completed"
                reason = decision.reason or f"follow_{decision.state}"
                if len(trace) >= max(20, max_steps // 4):
                    break
            self.world.step()
        self.world.stop()
        controller.stop()
        return self._result(
            text,
            status=status,
            reason=reason,
            target_id="owner-1",
            terminal_relation="follow",
            trace=trace,
            semantic_scan_steps=0,
            terminal_command=terminal_command,
            required_obstacle_clearance_m=self.reactive_safety.obstacle_stop_m,
        )

    def _run_spatial(self, text: str, *, max_steps: int) -> HeadlessTaskResult:
        intent = parse_spatial_intent(text)
        assert intent is not None
        controller = SpatialBehaviorController(self.spatial_config)
        controller.start(intent, self.world.observe(), now=float(self.world.data.time))
        trace: list[HeadlessTraceSample] = []
        status = "timed_out"
        reason = "spatial_step_limit"
        terminal_command = self.world.command
        detail = controller.snapshot()
        owner_orbit = intent.behavior == "orbit_owner"
        orbit_radius_m = float(detail.get("orbit_radius_m") or 0.0)
        for _ in range(max_steps):
            observation = self.world.observe()
            decision = controller.step(observation, now=observation.timestamp)
            requested = VelocityCommand() if decision.done else decision.command
            command, _ = apply_reactive_safety(
                requested,
                observation,
                policy=self.reactive_safety,
                owner_orbit=owner_orbit,
                orbit_radius_m=orbit_radius_m,
                now=observation.timestamp,
                require_fresh_telemetry=False,
            )
            terminal_command = command
            trace.append(
                HeadlessTraceSample(
                    time_s=observation.timestamp,
                    robot=observation.robot,
                    command=command,
                    phase=decision.state,
                    note=decision.reason,
                    progress=decision.progress,
                )
            )
            self.world.apply(command)
            if decision.done:
                status = decision.state
                reason = decision.reason
                break
            self.world.step()
        self.world.stop()
        controller.stop()
        return self._result(
            text,
            status=status,
            reason=reason,
            target_id="owner-1",
            terminal_relation="orbit",
            trace=trace,
            semantic_scan_steps=0,
            terminal_command=terminal_command,
            required_obstacle_clearance_m=self.reactive_safety.obstacle_stop_m,
        )

    def _failure(self, text: str, reason: str) -> HeadlessTaskResult:
        self.world.stop()
        return self._result(
            text,
            status="failed",
            reason=reason,
            target_id=None,
            terminal_relation=None,
            trace=[],
            semantic_scan_steps=0,
            terminal_command=self.world.command,
            required_obstacle_clearance_m=self.reactive_safety.obstacle_stop_m,
        )

    def _result(
        self,
        directive: str,
        *,
        status: str,
        reason: str,
        target_id: str | None,
        terminal_relation: str | None,
        trace: list[HeadlessTraceSample],
        semantic_scan_steps: int,
        terminal_command: VelocityCommand,
        required_obstacle_clearance_m: float,
    ) -> HeadlessTaskResult:
        return HeadlessTaskResult(
            directive=directive,
            status=status,
            reason=reason,
            target_id=target_id,
            terminal_relation=terminal_relation,
            final_observation=self.world.observe(),
            trace=tuple(trace),
            path=self.world.path,
            collision_count=self.world.collision_count,
            minimum_clearance_m=self.world.minimum_clearance_m,
            required_obstacle_clearance_m=required_obstacle_clearance_m,
            semantic_scan_steps=semantic_scan_steps,
            terminal_command=terminal_command,
        )


def _nav_observation(
    observation: SimObservation,
    *,
    measured_velocity: VelocityCommand,
    stop_confirmed: bool,
    settled_linear_speed_mps: float,
    settled_yaw_speed_rad_s: float,
) -> NavObservation:
    return NavObservation(
        position=(observation.robot.x, observation.robot.y, observation.robot.z),
        heading_deg=math.degrees(observation.robot.yaw),
        nearest_person_m=observation.nearest_person_m,
        nearest_obstacle_m=observation.nearest_obstacle_m,
        lidar=observation.lidar_ranges or None,
        extras={
            "collision": observation.collision,
            "perception_fresh": True,
            "lidar_angle_min_rad": observation.lidar_angle_min_rad,
            "lidar_angle_increment_rad": observation.lidar_angle_increment_rad,
            "lidar_range_min_m": observation.lidar_range_min_m,
            "lidar_range_max_m": observation.lidar_range_max_m,
            "obstacle_bearing_rad": observation.nearest_obstacle_bearing_rad,
            "obstacle_id": observation.nearest_obstacle_id,
            "person_bearing_rad": observation.nearest_person_bearing_rad,
            "person_id": observation.nearest_person_id,
            "person_ttc_s": observation.nearest_person_ttc_s,
            "semantic_candidates": semantic_candidates_from_observation(observation),
            "lidar_obstacles": lidar_payload_from_observation(observation),
            "motion_feedback": {
                "fresh": True,
                "stop_confirmed": stop_confirmed,
                "linear_speed_mps": math.hypot(
                    measured_velocity.vx,
                    measured_velocity.vy,
                ),
                "yaw_speed_rad_s": abs(measured_velocity.vyaw),
                "settled_linear_speed_mps": settled_linear_speed_mps,
                "settled_yaw_speed_rad_s": settled_yaw_speed_rad_s,
            },
        },
    )


def _spatial_config_from_store(store: ConfigStore) -> SpatialBehaviorConfig:
    config = store.section("spatial_behaviors")
    return SpatialBehaviorConfig(
        step_length_m=float(config.get("step_length_m", 0.25)),
        max_steps=int(config.get("max_steps", 12)),
        default_orbit_radius_m=float(config.get("default_orbit_radius_m", 1.6)),
        min_orbit_radius_m=float(config.get("min_orbit_radius_m", 1.3)),
        max_orbit_radius_m=float(config.get("max_orbit_radius_m", 2.0)),
        max_revolutions=float(config.get("max_revolutions", 1.0)),
        owner_collision_envelope_m=float(
            config.get("owner_collision_envelope_m", 0.55)
        ),
        orbit_clearance_margin_m=float(config.get("orbit_clearance_margin_m", 0.10)),
        owner_anchor_tolerance_m=float(config.get("owner_anchor_tolerance_m", 0.60)),
        stall_timeout_s=float(config.get("stall_timeout_s", 20.0)),
        timeout_s=float(config.get("timeout_s", 120.0)),
    )


def _navigation_config_from_store(store: ConfigStore) -> Path:
    config = store.section("navigation")
    if config.get("enabled", True) is not True:
        raise ValueError("headless quality harness requires navigation.enabled=true")
    configured = Path(
        str(config.get("config", "configs/navigation/default.yaml"))
    ).expanduser()
    path = (
        configured.resolve()
        if configured.is_absolute()
        else (Path(__file__).resolve().parents[2] / configured).resolve()
    )
    if not path.is_file():
        raise FileNotFoundError(f"navigation configuration not found: {path}")
    return path


def _reactive_safety_from_store(
    store: ConfigStore,
    spatial: SpatialBehaviorConfig,
) -> ReactiveSafetyPolicy:
    config = store.section("safety")
    policy = ReactiveSafetyPolicy(
        obstacle_stop_m=float(config.get("obstacle_stop_m", 0.65)),
        obstacle_slow_m=float(config.get("obstacle_slow_m", 1.2)),
        person_stop_m=float(config.get("person_stop_m", 1.0)),
        person_slow_m=float(config.get("person_slow_m", 2.0)),
        telemetry_stale_s=float(config.get("telemetry_stale_s", 0.6)),
        owner_collision_envelope_m=spatial.owner_collision_envelope_m,
        orbit_clearance_margin_m=spatial.orbit_clearance_margin_m,
        orbit_waypoint_tolerance_m=spatial.waypoint_tolerance_m,
    )
    minimum_safe_orbit = spatial.minimum_safe_orbit_radius(policy.obstacle_stop_m)
    if spatial.min_orbit_radius_m + 1e-9 < minimum_safe_orbit:
        raise ValueError(
            "headless spatial min_orbit_radius_m does not satisfy production "
            f"safety configuration (minimum {minimum_safe_orbit:.2f} m)"
        )
    return policy


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _is_stopped(command: VelocityCommand) -> bool:
    return (
        abs(command.vx) <= 1e-9
        and abs(command.vy) <= 1e-9
        and abs(command.vyaw) <= 1e-9
    )
