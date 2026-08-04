from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from parcel_robot.geometry import ROBOT_FOOTPRINT_RADIUS_M

from ..base import MidLevelCommand, Mission, ModelSpec, Navigator, NavObservation


@dataclass(frozen=True)
class _LidarReturn:
    obstacle_id: str
    distance_m: float
    bearing_rad: float


class StubNavigator:
    """Deterministic forward-preferred navigator with rotate-first hysteresis.

    The quadruped and navigation pipeline support lateral velocity. This simple
    point-goal controller deliberately leaves ``vy`` at zero because sustained
    strafing is not its preferred way to make progress toward a destination.
    """

    def __init__(
        self,
        spec: ModelSpec,
        *,
        arrive_radius_m: float = 1.5,
        cruise_vx: float = 0.6,
        align_enter_deg: float = 30.0,
        align_exit_deg: float = 7.0,
        max_yaw_rate: float = 0.8,
        min_align_yaw_rate: float = 0.18,
        yaw_gain: float = 1.25,
        slowdown_radius_m: float = 2.0,
        control_dt_s: float = 0.1,
        max_linear_accel: float = 0.8,
        max_yaw_accel: float = 1.6,
        avoid_enter_m: float = 1.2,
        avoid_exit_m: float = 1.35,
        avoid_corridor_rad: float = 1.15,
        avoid_tangent_deg: float = 80.0,
        avoid_path_half_width_m: float = 1.15,
    ):
        if not 0.0 < align_exit_deg < align_enter_deg < 180.0:
            raise ValueError("heading thresholds must satisfy 0 < exit < enter < 180")
        if (
            not math.isfinite(avoid_enter_m)
            or not math.isfinite(avoid_exit_m)
            or not 0.0 < avoid_enter_m < avoid_exit_m
        ):
            raise ValueError("avoidance distances must satisfy 0 < enter < exit")
        if not 0.0 < avoid_corridor_rad < math.pi / 2.0:
            raise ValueError("avoidance corridor must be between zero and pi/2")
        if not 45.0 <= avoid_tangent_deg < 90.0:
            raise ValueError("avoidance tangent must be between 45 and 90 degrees")
        if not math.isfinite(avoid_path_half_width_m) or avoid_path_half_width_m <= 0.0:
            raise ValueError("avoidance path half-width must be positive and finite")
        self.spec = spec
        self.arrive_radius_m = arrive_radius_m
        self.cruise_vx = cruise_vx
        self.align_enter_deg = align_enter_deg
        self.align_exit_deg = align_exit_deg
        self.max_yaw_rate = max_yaw_rate
        self.min_align_yaw_rate = min_align_yaw_rate
        self.yaw_gain = yaw_gain
        self.slowdown_radius_m = max(slowdown_radius_m, arrive_radius_m + 1e-6)
        self.control_dt_s = control_dt_s
        self.max_linear_accel = max_linear_accel
        self.max_yaw_accel = max_yaw_accel
        self.avoid_enter_m = avoid_enter_m
        self.avoid_exit_m = avoid_exit_m
        self.avoid_corridor_rad = avoid_corridor_rad
        self.avoid_tangent_deg = avoid_tangent_deg
        self.avoid_path_half_width_m = avoid_path_half_width_m
        self._mission: Mission | None = None
        self._avoiding = False
        self._avoid_direction = 0.0
        self._avoid_heading_deg = 0.0
        self._avoid_obstacle_id: str | None = None
        self._aligning = True
        self._last_vx = 0.0
        self._last_vyaw = 0.0

    def reset(self, mission: Mission) -> None:
        self._mission = mission
        self._avoiding = False
        self._avoid_direction = 0.0
        self._avoid_heading_deg = 0.0
        self._avoid_obstacle_id = None
        self._aligning = True
        self._last_vx = 0.0
        self._last_vyaw = 0.0
        mission.status = "running"

    def act(self, observation: NavObservation, mission: Mission) -> MidLevelCommand:
        assert mission.goal is not None
        dx = mission.goal.x - observation.position[0]
        dy = mission.goal.y - observation.position[1]
        dist = math.hypot(dx, dy)
        arrival_radius = (
            self.arrive_radius_m
            if mission.goal.arrival_radius_m is None
            else mission.goal.arrival_radius_m
        )
        if not 0.0 < arrival_radius < self.slowdown_radius_m:
            raise ValueError("goal arrival radius must be positive and below slowdown radius")
        if dist <= arrival_radius:
            terminal_error = self._wrap_degrees(
                mission.goal.heading_deg - observation.heading_deg
            )
            if abs(terminal_error) > self.align_exit_deg:
                mission.status = "running"
                self._last_vx = 0.0
                target_vyaw = max(
                    -self.max_yaw_rate,
                    min(self.max_yaw_rate, math.radians(terminal_error) * self.yaw_gain),
                )
                self._last_vyaw = self._slew(
                    self._last_vyaw,
                    target_vyaw,
                    self.max_yaw_accel * self.control_dt_s,
                )
                return MidLevelCommand(
                    vyaw=self._last_vyaw,
                    note=f"align_terminal err={terminal_error:.1f}",
                )
            mission.status = "arrived"
            self._last_vx = 0.0
            self._last_vyaw = 0.0
            return MidLevelCommand(stop=True, note="arrived")

        # Soft social / obstacle brake
        brake = 1.0
        if observation.nearest_person_m is not None and observation.nearest_person_m < 1.2:
            brake = 0.0
        elif observation.nearest_obstacle_m is not None and observation.nearest_obstacle_m < 0.8:
            brake = 0.25

        target_heading = math.degrees(math.atan2(dy, dx))
        lidar = self._validated_lidar(observation)
        excluded_targets = self._near_target_ids(mission)
        avoidance_lidar = tuple(
            item for item in lidar if item.obstacle_id not in excluded_targets
        )
        goal_bearing = math.radians(self._wrap_degrees(target_heading - observation.heading_deg))
        corridor = self._corridor_obstacles(
            avoidance_lidar,
            goal_bearing,
            dist,
            local_distance_limit_m=None,
        )

        if self._avoiding:
            active = next(
                (item for item in avoidance_lidar if item.obstacle_id == self._avoid_obstacle_id),
                None,
            )
            active_clear = active is None or active.distance_m > self.avoid_exit_m
            if active_clear and not corridor:
                self._clear_avoidance()
            else:
                # The heading is latched in the world frame. A different return
                # becoming nearest cannot reverse the chosen side mid-manoeuvre.
                target_heading = self._avoid_heading_deg
        else:
            entering = self._corridor_obstacles(
                avoidance_lidar,
                goal_bearing,
                dist,
                local_distance_limit_m=self.avoid_enter_m,
            )
            if entering:
                blocker = min(
                    entering,
                    key=lambda item: (item.distance_m, item.obstacle_id),
                )
                self._begin_avoidance(
                    observation,
                    blocker,
                    avoidance_lidar,
                    target_heading,
                )
                target_heading = self._avoid_heading_deg

        err = ((target_heading - observation.heading_deg + 180.0) % 360.0) - 180.0
        abs_err = abs(err)
        if self._aligning:
            if abs_err <= self.align_exit_deg:
                self._aligning = False
        elif abs_err >= self.align_enter_deg:
            self._aligning = True

        phase_target = "avoid" if self._avoiding else "goal"
        desired_yaw = max(
            -self.max_yaw_rate,
            min(self.max_yaw_rate, math.radians(err) * self.yaw_gain),
        )
        if self._aligning and abs(desired_yaw) < self.min_align_yaw_rate:
            desired_yaw = math.copysign(self.min_align_yaw_rate, err)
        vyaw = self._slew(
            self._last_vyaw,
            desired_yaw,
            self.max_yaw_accel * self.control_dt_s,
        )

        if self._aligning:
            # Alignment must brake immediately; otherwise the body still cuts
            # sideways while acquiring a new path heading.
            vx = 0.0
            note = f"align_{phase_target} err={err:.1f} dist={dist:.1f}"
        else:
            distance_scale = min(
                1.0,
                max(
                    0.12,
                    (dist - arrival_radius) / (self.slowdown_radius_m - arrival_radius),
                ),
            )
            curvature_scale = max(0.0, math.cos(math.radians(err))) ** 2
            desired_vx = self.cruise_vx * brake * distance_scale * curvature_scale
            if self._avoiding:
                desired_vx = min(desired_vx, 0.22)
            vx = self._slew(
                self._last_vx,
                desired_vx,
                self.max_linear_accel * self.control_dt_s,
            )
            note = f"track_{phase_target} err={err:.1f} dist={dist:.1f}"

        self._last_vx = vx
        self._last_vyaw = vyaw
        return MidLevelCommand(vx=vx, vy=0.0, vyaw=vyaw, note=note)

    @staticmethod
    def _slew(current: float, target: float, maximum_delta: float) -> float:
        return current + max(-maximum_delta, min(maximum_delta, target - current))

    def _begin_avoidance(
        self,
        observation: NavObservation,
        blocker: _LidarReturn,
        lidar: tuple[_LidarReturn, ...],
        goal_heading_deg: float,
    ) -> None:
        preferred_direction = -1.0 if blocker.bearing_rad >= 0.0 else 1.0
        obstacle_heading = self._wrap_degrees(
            observation.heading_deg + math.degrees(blocker.bearing_rad)
        )
        candidates = []
        for direction in (preferred_direction, -preferred_direction):
            heading = self._wrap_degrees(obstacle_heading + direction * self.avoid_tangent_deg)
            body_bearing = math.radians(self._wrap_degrees(heading - observation.heading_deg))
            forward_returns = [
                item.distance_m
                for item in lidar
                if abs(self._wrap_radians(item.bearing_rad - body_bearing)) < math.radians(40.0)
            ]
            clearance = min(forward_returns, default=self.avoid_exit_m + 1.0)
            goal_alignment = math.cos(math.radians(self._wrap_degrees(heading - goal_heading_deg)))
            candidates.append((clearance + 0.15 * goal_alignment, direction, heading))
        _, self._avoid_direction, self._avoid_heading_deg = max(
            candidates,
            key=lambda item: (item[0], item[1] == preferred_direction),
        )
        self._avoid_obstacle_id = blocker.obstacle_id
        self._avoiding = True

    def _clear_avoidance(self) -> None:
        self._avoiding = False
        self._avoid_direction = 0.0
        self._avoid_heading_deg = 0.0
        self._avoid_obstacle_id = None

    def _validated_lidar(self, observation: NavObservation) -> tuple[_LidarReturn, ...]:
        raw = observation.extras.get("lidar_obstacles")
        returns: list[_LidarReturn] = []
        if isinstance(raw, (list, tuple)):
            for index, item in enumerate(raw[:64]):
                if not isinstance(item, dict):
                    continue
                distance = item.get("distance_m")
                bearing = item.get("bearing_rad")
                if (
                    isinstance(distance, bool)
                    or not isinstance(distance, (int, float))
                    or isinstance(bearing, bool)
                    or not isinstance(bearing, (int, float))
                ):
                    continue
                distance = float(distance)
                bearing = float(bearing)
                if (
                    not math.isfinite(distance)
                    or distance < 0.0
                    or not math.isfinite(bearing)
                    or not -math.pi <= bearing <= math.pi
                ):
                    continue
                obstacle_id = item.get("id")
                if obstacle_id is None:
                    normalized_id = "<anonymous>"
                elif (
                    not isinstance(obstacle_id, str)
                    or not obstacle_id.strip()
                    or len(obstacle_id) > 128
                ):
                    continue
                else:
                    normalized_id = obstacle_id.strip()
                returns.append(_LidarReturn(normalized_id, distance, bearing))
        if returns:
            return tuple(returns)

        distance = observation.nearest_obstacle_m
        bearing = observation.extras.get("obstacle_bearing_rad")
        if (
            isinstance(distance, bool)
            or not isinstance(distance, (int, float))
            or isinstance(bearing, bool)
            or not isinstance(bearing, (int, float))
        ):
            return ()
        distance = float(distance)
        bearing = float(bearing)
        if (
            not math.isfinite(distance)
            or distance < 0.0
            or not math.isfinite(bearing)
            or not -math.pi <= bearing <= math.pi
        ):
            return ()
        obstacle_id = observation.extras.get("obstacle_id")
        normalized_id = (
            obstacle_id.strip()
            if isinstance(obstacle_id, str) and 0 < len(obstacle_id.strip()) <= 128
            else "<legacy>"
        )
        return (_LidarReturn(normalized_id, distance, bearing),)

    def _corridor_obstacles(
        self,
        lidar: tuple[_LidarReturn, ...],
        goal_bearing_rad: float,
        goal_distance_m: float,
        *,
        local_distance_limit_m: float | None,
    ) -> tuple[_LidarReturn, ...]:
        blockers = []
        for item in lidar:
            if local_distance_limit_m is not None and item.distance_m > local_distance_limit_m:
                continue
            error = self._wrap_radians(item.bearing_rad - goal_bearing_rad)
            if abs(error) >= self.avoid_corridor_rad:
                continue
            surface_range = item.distance_m + ROBOT_FOOTPRINT_RADIUS_M
            forward = surface_range * math.cos(error)
            lateral = abs(surface_range * math.sin(error))
            if 0.0 <= forward <= goal_distance_m and lateral <= self.avoid_path_half_width_m:
                blockers.append(item)
        return tuple(blockers)

    @staticmethod
    def _near_target_ids(mission: Mission) -> frozenset[str]:
        semantic_goal = mission.semantic_goal
        if semantic_goal is None or semantic_goal.terminal_relation != "near":
            return frozenset()
        target_ids: set[str] = set()
        candidate_id = mission.metadata.get("candidate_id")
        if isinstance(candidate_id, str) and candidate_id.strip():
            target_ids.add(candidate_id.strip())
        associated = mission.metadata.get("associated_lidar_ids")
        if isinstance(associated, (list, tuple)):
            target_ids.update(
                value.strip()
                for value in associated[:16]
                if isinstance(value, str) and 0 < len(value.strip()) <= 128
            )
        return frozenset(target_ids)

    @staticmethod
    def _wrap_degrees(angle: float) -> float:
        return (angle + 180.0) % 360.0 - 180.0

    @staticmethod
    def _wrap_radians(angle: float) -> float:
        return (angle + math.pi) % (2.0 * math.pi) - math.pi

    def close(self) -> None:
        self._mission = None
        self._clear_avoidance()
        self._last_vx = 0.0
        self._last_vyaw = 0.0


def build_navigator(spec: ModelSpec, **kwargs: Any) -> Navigator:
    kind = spec.type.lower()
    if kind == "stub":
        return StubNavigator(spec, **kwargs)
    if kind == "grid":
        from ..grid_navigator import GridNavigator

        return GridNavigator(spec, **kwargs)
    # Learned-navigator adapters (CityWalker / NaVILA / NoMaD / ViNT) were
    # registry metadata that unconditionally raised NotImplementedError. They
    # were removed rather than left implying a live model; re-add a type here
    # only together with a working inference adapter and tests.
    raise ValueError(f"unsupported navigator type: {spec.type}")
