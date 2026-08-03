from __future__ import annotations

import math
from typing import Any

from ..base import MidLevelCommand, Mission, ModelSpec, Navigator, NavObservation


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
    ):
        if not 0.0 < align_exit_deg < align_enter_deg < 180.0:
            raise ValueError("heading thresholds must satisfy 0 < exit < enter < 180")
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
        self._mission: Mission | None = None
        self._avoiding = False
        self._avoid_direction = 0.0
        self._avoid_heading_deg = 0.0
        self._aligning = True
        self._last_vx = 0.0
        self._last_vyaw = 0.0

    def reset(self, mission: Mission) -> None:
        self._mission = mission
        self._avoiding = False
        self._avoid_direction = 0.0
        self._avoid_heading_deg = 0.0
        self._aligning = True
        self._last_vx = 0.0
        self._last_vyaw = 0.0
        mission.status = "running"

    def act(self, observation: NavObservation, mission: Mission) -> MidLevelCommand:
        dx = mission.goal.x - observation.position[0]
        dy = mission.goal.y - observation.position[1]
        dist = math.hypot(dx, dy)
        if dist <= self.arrive_radius_m:
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
        obstacle_bearing = observation.extras.get("obstacle_bearing_rad")
        if (
            observation.nearest_obstacle_m is not None
            and observation.nearest_obstacle_m < 1.2
            and isinstance(obstacle_bearing, (int, float))
            and abs(float(obstacle_bearing)) < 1.15
            and not self._avoiding
        ):
            self._avoiding = True
            self._avoid_direction = -1.0 if float(obstacle_bearing) >= 0.0 else 1.0
            self._avoid_heading_deg = (
                observation.heading_deg + self._avoid_direction * 80.0 + 180.0
            ) % 360.0 - 180.0

        if self._avoiding:
            clearance = observation.nearest_obstacle_m
            if clearance is None or clearance > 1.35:
                self._avoiding = False
            else:
                # A tiny deterministic Bug-style fallback: align to a fixed
                # tangent heading, then walk that line until clearance grows.
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
                    (dist - self.arrive_radius_m) / (self.slowdown_radius_m - self.arrive_radius_m),
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

    def close(self) -> None:
        self._mission = None
        self._last_vx = 0.0
        self._last_vyaw = 0.0


class CheckpointNavigator:
    """Lazy weight loader — raises until checkpoint + optional deps are present."""

    def __init__(self, spec: ModelSpec, **_: Any):
        self.spec = spec
        self._loaded = False
        self._impl: Navigator | None = None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        from pathlib import Path

        ckpt = Path(self.spec.checkpoint).expanduser() if self.spec.checkpoint else None
        if ckpt is None or not ckpt.exists():
            raise FileNotFoundError(
                f"checkpoint missing for {self.spec.id}: {self.spec.checkpoint}. "
                f"See {self.spec.homepage or 'docs/NAVIGATION_CITY.md'}"
            )
        # Real backends (CityWalker / NaVILA / NoMaD / ViNT) plug in here once
        # third_party wheels + weights are installed on a CUDA host.
        raise NotImplementedError(
            f"weights found for {self.spec.id} but runtime adapter is not wired yet. "
            f"Install vendor package from {self.spec.homepage} and extend "
            f"parcel_robot.navigation.models.{self.spec.type}"
        )

    def reset(self, mission: Mission) -> None:
        self._ensure_loaded()
        assert self._impl is not None
        self._impl.reset(mission)

    def act(self, observation: NavObservation, mission: Mission) -> MidLevelCommand:
        self._ensure_loaded()
        assert self._impl is not None
        return self._impl.act(observation, mission)

    def close(self) -> None:
        if self._impl is not None:
            self._impl.close()


def build_navigator(spec: ModelSpec, **kwargs: Any) -> Navigator:
    kind = spec.type.lower()
    if kind == "stub":
        return StubNavigator(spec, **kwargs)
    if kind in {"citywalker", "navila", "nomad", "vint"}:
        return CheckpointNavigator(spec, **kwargs)
    raise ValueError(f"unsupported navigator type: {spec.type}")
