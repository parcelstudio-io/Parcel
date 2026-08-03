from __future__ import annotations

import math
from typing import Any

from ..base import MidLevelCommand, Mission, ModelSpec, Navigator, NavObservation


class StubNavigator:
    """Deterministic mid-level navigator for offline tests (no weights)."""

    def __init__(self, spec: ModelSpec, *, arrive_radius_m: float = 1.5, cruise_vx: float = 0.6):
        self.spec = spec
        self.arrive_radius_m = arrive_radius_m
        self.cruise_vx = cruise_vx
        self._mission: Mission | None = None
        self._avoiding = False
        self._avoid_direction = 0.0
        self._avoid_heading_deg = 0.0

    def reset(self, mission: Mission) -> None:
        self._mission = mission
        self._avoiding = False
        self._avoid_direction = 0.0
        self._avoid_heading_deg = 0.0
        mission.status = "running"

    def act(self, observation: NavObservation, mission: Mission) -> MidLevelCommand:
        dx = mission.goal.x - observation.position[0]
        dy = mission.goal.y - observation.position[1]
        dist = math.hypot(dx, dy)
        if dist <= self.arrive_radius_m:
            mission.status = "arrived"
            return MidLevelCommand(stop=True, note="arrived")

        # Soft social / obstacle brake
        brake = 1.0
        if observation.nearest_person_m is not None and observation.nearest_person_m < 1.2:
            brake = 0.0
        elif observation.nearest_obstacle_m is not None and observation.nearest_obstacle_m < 0.8:
            brake = 0.25

        target_heading = math.degrees(math.atan2(dy, dx))
        err = ((target_heading - observation.heading_deg + 180.0) % 360.0) - 180.0
        vyaw = max(-0.8, min(0.8, err / 45.0))
        vx = self.cruise_vx * brake * max(0.15, 1.0 - abs(err) / 90.0)
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

        if self._avoiding and isinstance(obstacle_bearing, (int, float)):
            clearance = observation.nearest_obstacle_m
            if clearance is None or clearance > 1.35:
                self._avoiding = False
            else:
                # A tiny deterministic Bug-style fallback: align to a fixed
                # tangent heading, then walk that line until clearance grows.
                heading_error = (
                    self._avoid_heading_deg - observation.heading_deg + 180.0
                ) % 360.0 - 180.0
                vyaw = max(-0.7, min(0.7, heading_error / 45.0))
                vx = 0.22 if abs(heading_error) < 25.0 else 0.0
        if self._avoiding:
            note = f"stub avoid_obstacle dist={dist:.1f}"
        else:
            note = f"stub dist={dist:.1f}"
        return MidLevelCommand(vx=vx, vy=0.0, vyaw=vyaw, note=note)

    def close(self) -> None:
        self._mission = None


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
