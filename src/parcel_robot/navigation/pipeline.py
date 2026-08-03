from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .approach import point_in_polygon, safe_approach_pose
from .base import MidLevelCommand, Mission, NavObservation
from .collision import CollisionPolicy, apply_collision_brake
from .goals import semantic_goal_from_directive
from .grounder import PlaceGrounder
from .registry import ModelRegistry
from .search import ActiveSemanticSearch
from .semantic_map import ObservationSemanticMap, SemanticMap

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
        semantic_map: SemanticMap | None = None,
        search: ActiveSemanticSearch | None = None,
    ):
        self.registry = registry
        self.grounder = grounder
        self.model_id = model_id
        self.arrive_radius_m = arrive_radius_m
        self.collision = collision or CollisionPolicy()
        self.safety = safety or {}
        self.semantic_map = semantic_map or ObservationSemanticMap()
        self.search = search or ActiveSemanticSearch()
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

        models_root = resolve(
            overrides.get("models_root") or data.get("models_root") or "configs/navigation/models"
        )
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
        search_config = dict(data.get("semantic_search") or {})
        stop_m = float(safety.get("stop_distance_m", 0.8))
        max_vyaw = float(safety.get("max_vyaw", 1.5))
        return cls(
            registry=registry,
            grounder=grounder,
            model_id=str(
                overrides.get("model_id")
                or data.get("active_model")
                or data.get("default_model")
                or "stub_v0"
            ),
            arrive_radius_m=float(
                overrides.get("arrive_radius_m") or data.get("arrive_radius_m") or 1.5
            ),
            collision=CollisionPolicy(
                person_stop_m=float(overrides.get("person_stop_m", stop_m + 0.4)),
                person_slow_m=float(overrides.get("person_slow_m", 2.5)),
                obstacle_stop_m=float(overrides.get("obstacle_stop_m", stop_m)),
                obstacle_slow_m=float(overrides.get("obstacle_slow_m", 1.2)),
                slow_scale=float(overrides.get("slow_scale", 0.35)),
            ),
            safety=safety,
            search=ActiveSemanticSearch(
                max_steps=int(overrides.get("search_max_steps", search_config.get("max_steps", 80))),
                yaw_rate=min(
                    max_vyaw,
                    float(overrides.get("search_yaw_rate", search_config.get("yaw_rate", 0.35))),
                ),
            ),
        )

    def set_model(self, model_id: str) -> None:
        if self._navigator is not None:
            self._navigator.close()
        self.model_id = model_id
        self._navigator = self.registry.create(model_id, arrive_radius_m=self.arrive_radius_m)

    def list_models(self):
        return self.registry.list()

    def parse(self, directive: str) -> Mission:
        try:
            goal = self.grounder.ground(directive)
            return Mission(
                directive=directive,
                goal=goal,
                status="idle",
                metadata={"goal_source": "known_poi"},
            )
        except LookupError:
            semantic_goal = semantic_goal_from_directive(directive)
            return Mission(
                directive=directive,
                goal=None,
                status="unresolved",
                semantic_goal=semantic_goal,
                metadata={
                    "goal_source": "semantic_search",
                    "semantic_query": semantic_goal.query,
                    "resolution_state": "unresolved",
                },
            )

    def start(self, directive: str | Mission) -> Mission:
        if isinstance(directive, Mission):
            mission = directive
            if mission.status == "idle":
                mission.status = "running"
        else:
            mission = self.parse(directive)
            mission.status = "running" if mission.goal is not None else "searching"
        self.search.reset()
        if mission.goal is not None:
            self._navigator.reset(mission)
        self.mission = mission
        return mission

    def done(self) -> bool:
        return self.mission is None or self.mission.status in {"arrived", "failed", "idle"}

    def step(self, observation: NavObservation) -> MidLevelCommand:
        if self.mission is None:
            return MidLevelCommand(stop=True, note="no_mission")
        if self.mission.goal is None:
            return self._step_semantic_resolution(observation)
        cmd = self._navigator.act(observation, self.mission)
        if cmd.stop or self.mission.status == "arrived":
            if self._semantic_arrival_verified(observation):
                self.mission.status = "arrived"
                self.mission.metadata["resolution_state"] = "verified"
                return MidLevelCommand(stop=True, note=cmd.note or "arrived_verified")
            self.mission.status = "failed"
            self.mission.metadata["resolution_state"] = "verification_failed"
            return MidLevelCommand(stop=True, note="semantic_arrival_verification_failed")

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

    def _step_semantic_resolution(self, observation: NavObservation) -> MidLevelCommand:
        assert self.mission is not None
        semantic_goal = self.mission.semantic_goal
        if semantic_goal is None:
            self.mission.status = "failed"
            return MidLevelCommand(stop=True, note="semantic_goal_missing")
        result = self.search.observe(semantic_goal, self.semantic_map, observation)
        if isinstance(result, MidLevelCommand):
            if result.stop:
                self.mission.status = "failed"
                self.mission.metadata["resolution_state"] = "not_found"
            else:
                self.mission.status = "searching"
                self.mission.metadata["resolution_state"] = "searching"
            return result
        pose = safe_approach_pose(semantic_goal, result, observation)
        if pose is None:
            self.mission.status = "failed"
            self.mission.metadata["resolution_state"] = "unreachable"
            return MidLevelCommand(stop=True, note="semantic_target_unreachable")
        self.mission.goal = pose
        self.mission.status = "running"
        self.mission.metadata.update(
            {
                "resolution_state": "resolved",
                "candidate_id": result.candidate_id,
                "candidate_confidence": result.confidence,
                "candidate_source": result.source,
                "target_polygon": result.polygon,
                "terminal_relation": semantic_goal.terminal_relation,
            }
        )
        self._navigator.reset(self.mission)
        return MidLevelCommand(vx=0.0, vy=0.0, vyaw=0.0, note="semantic_target_resolved")

    def _semantic_arrival_verified(self, observation: NavObservation) -> bool:
        if self.mission is None or self.mission.semantic_goal is None:
            return True
        if self.mission.semantic_goal.terminal_relation != "inside":
            return True
        polygon = self.mission.metadata.get("target_polygon") or ()
        if not polygon:
            return False
        return point_in_polygon((observation.position[0], observation.position[1]), tuple(polygon))

    def stop(self) -> None:
        if self.mission is not None:
            self.mission.status = "idle"
        self.mission = None

    def close(self) -> None:
        self.stop()
        self._navigator.close()
