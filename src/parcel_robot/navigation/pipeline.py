from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .base import MidLevelCommand, Mission, NavObservation
from .collision import CollisionPolicy, apply_collision_brake
from .grounder import PlaceGrounder
from .registry import ModelRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]


class DirectiveNavigator:
    """NL directive → POI goal → navigator model → collision-filtered mid-level cmd."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        grounder: PlaceGrounder,
        model_id: str = "stub_v0",
        arrive_radius_m: float = 1.5,
        collision: CollisionPolicy | None = None,
        safety: dict[str, float] | None = None,
    ):
        self.registry = registry
        self.grounder = grounder
        self.model_id = model_id
        self.arrive_radius_m = arrive_radius_m
        self.collision = collision or CollisionPolicy()
        self.safety = safety or {}
        self._navigator = registry.create(model_id, arrive_radius_m=arrive_radius_m)
        self.mission: Mission | None = None

    @classmethod
    def from_config(cls, path: str | Path | None = None, **overrides: Any) -> DirectiveNavigator:
        cfg_path = Path(path) if path else REPO_ROOT / "configs" / "navigation" / "default.yaml"
        cfg_path = cfg_path.expanduser().resolve()
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

        def resolve(p: str | Path) -> Path:
            candidate = Path(p).expanduser()
            if candidate.is_absolute():
                return candidate
            from_repo = (REPO_ROOT / candidate).resolve()
            if from_repo.exists():
                return from_repo
            return (cfg_path.parent / candidate).resolve()

        models_root = resolve(overrides.get("models_root") or data.get("models_root") or "configs/navigation/models")
        pois_path = resolve(
            overrides.get("pois_path")
            or overrides.get("pois")
            or data.get("pois_path")
            or data.get("pois")
            or "configs/navigation/cities/demo_pois.yaml"
        )

        registry = ModelRegistry.load(models_root)
        grounder = PlaceGrounder.from_yaml(pois_path)
        safety = dict(data.get("safety") or {})
        stop_m = float(safety.get("stop_distance_m", 0.8))
        return cls(
            registry=registry,
            grounder=grounder,
            model_id=str(overrides.get("model_id") or data.get("active_model") or data.get("default_model") or "stub_v0"),
            arrive_radius_m=float(overrides.get("arrive_radius_m") or data.get("arrive_radius_m") or 1.5),
            collision=CollisionPolicy(
                person_stop_m=float(overrides.get("person_stop_m", stop_m + 0.4)),
                person_slow_m=float(overrides.get("person_slow_m", 2.5)),
                obstacle_stop_m=float(overrides.get("obstacle_stop_m", stop_m)),
                obstacle_slow_m=float(overrides.get("obstacle_slow_m", 1.2)),
                slow_scale=float(overrides.get("slow_scale", 0.35)),
            ),
            safety=safety,
        )

    def set_model(self, model_id: str) -> None:
        if self._navigator is not None:
            self._navigator.close()
        self.model_id = model_id
        self._navigator = self.registry.create(model_id, arrive_radius_m=self.arrive_radius_m)

    def list_models(self):
        return self.registry.list()

    def parse(self, directive: str) -> Mission:
        goal = self.grounder.ground(directive)
        return Mission(directive=directive, goal=goal, status="idle")

    def start(self, directive: str | Mission) -> Mission:
        if isinstance(directive, Mission):
            mission = directive
            if mission.status == "idle":
                mission.status = "running"
        else:
            mission = self.parse(directive)
            mission.status = "running"
        self._navigator.reset(mission)
        self.mission = mission
        return mission

    def done(self) -> bool:
        return self.mission is None or self.mission.status in {"arrived", "failed", "idle"}

    def step(self, observation: NavObservation) -> MidLevelCommand:
        if self.mission is None:
            return MidLevelCommand(stop=True, note="no_mission")
        cmd = self._navigator.act(observation, self.mission)
        if cmd.stop or self.mission.status == "arrived":
            self.mission.status = "arrived"
            return MidLevelCommand(stop=True, note=cmd.note or "arrived")

        obstacle_bearing = observation.extras.get("obstacle_bearing_rad")
        if not isinstance(obstacle_bearing, (int, float)):
            obstacle_bearing = None
        vx, vy, cnote = apply_collision_brake(
            cmd.vx,
            cmd.vy,
            nearest_person_m=observation.nearest_person_m,
            nearest_obstacle_m=observation.nearest_obstacle_m,
            nearest_obstacle_bearing_rad=obstacle_bearing,
            policy=self.collision,
        )
        max_vx = float(self.safety.get("max_vx", 1.0))
        max_vy = float(self.safety.get("max_vy", 1.0))
        max_vyaw = float(self.safety.get("max_vyaw", 1.5))
        vx = max(-max_vx, min(max_vx, vx))
        # Preserve bounded lateral motion from controllers that intentionally
        # use it (for example close repositioning or recovery). The default
        # point-goal controller is forward-preferred and normally emits vy=0.
        vy = max(-max_vy, min(max_vy, vy))
        vyaw = max(-max_vyaw, min(max_vyaw, cmd.vyaw))
        note = f"{cmd.note}|{cnote}" if cmd.note else cnote
        if cnote.endswith("_stop"):
            return MidLevelCommand(vx=0.0, vy=0.0, vyaw=vyaw, stop=False, note=note)
        return MidLevelCommand(vx=vx, vy=vy, vyaw=vyaw, stop=False, note=note)

    def stop(self) -> None:
        if self.mission is not None:
            self.mission.status = "idle"
        self.mission = None

    def close(self) -> None:
        self.stop()
        self._navigator.close()
