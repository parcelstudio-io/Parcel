from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from parcel_robot.geometry import ROBOT_FOOTPRINT_RADIUS_M

from .approach import point_in_polygon_with_clearance, safe_approach_pose
from .base import MidLevelCommand, Mission, NavObservation
from .collision import CollisionPolicy, apply_collision_brake
from .goals import navigation_directive_is_blocked, semantic_goal_from_directive
from .grounder import PlaceGrounder
from .registry import ModelRegistry
from .search import ActiveSemanticSearch
from .semantic_map import ObservationSemanticMap, SemanticCandidate, SemanticMap

if TYPE_CHECKING:
    from .experimental_all_ray_shield import V8AllRayShieldConfig

REPO_ROOT = Path(__file__).resolve().parents[3]

# Historical BARN isolated bundles ship an older parcel_robot tree without
# instructnav/. Keep the import soft so grid_v1 sidecars still load.
try:
    from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus, SE2Goal
    from parcel_robot.instructnav.grounding import (
        GroundingOutcome,
        honest_not_found_reply,
        resolve_grounding,
    )
    from parcel_robot.instructnav.memory import SemanticMemory

    _HAS_INSTRUCTNAV = True
except ImportError:  # pragma: no cover — frozen BARN bundle path
    GoalArbiter = None  # type: ignore[misc, assignment]
    ProposerBus = None  # type: ignore[misc, assignment]
    SE2Goal = None  # type: ignore[misc, assignment]
    GroundingOutcome = None  # type: ignore[misc, assignment]
    honest_not_found_reply = None  # type: ignore[misc, assignment]
    resolve_grounding = None  # type: ignore[misc, assignment]
    SemanticMemory = None  # type: ignore[misc, assignment]
    _HAS_INSTRUCTNAV = False


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
        safety: dict[str, Any] | None = None,
        all_ray_shield: V8AllRayShieldConfig | None = None,
        semantic_map: SemanticMap | None = None,
        search: ActiveSemanticSearch | None = None,
        semantic_memory: SemanticMemory | None = None,
        progress_timeout_steps: int = 400,
        max_semantic_replans: int = 2,
        terminal_stop_timeout_steps: int = 30,
        scan_budget_steps: int = 80,
        frontier_budget_steps: int = 300,
        instructnav_recovery: bool = True,
    ):
        if not 10 <= progress_timeout_steps <= 10_000:
            raise ValueError("progress timeout must be between 10 and 10000 steps")
        if not 0 <= max_semantic_replans <= 10:
            raise ValueError("semantic replan limit must be between 0 and 10")
        if not 2 <= terminal_stop_timeout_steps <= 1_000:
            raise ValueError("terminal stop timeout must be between 2 and 1000 steps")
        self.registry = registry
        self.grounder = grounder
        self.model_id = model_id
        self.arrive_radius_m = arrive_radius_m
        self.collision = collision or CollisionPolicy()
        self.safety = safety or {}
        self.all_ray_shield = all_ray_shield
        self.semantic_map = semantic_map or ObservationSemanticMap()
        self.search = search or ActiveSemanticSearch(max_steps=scan_budget_steps)
        if semantic_memory is not None:
            self.memory = semantic_memory
        elif _HAS_INSTRUCTNAV and SemanticMemory is not None:
            self.memory = SemanticMemory()
        else:
            self.memory = None
        self.proposer_bus = ProposerBus() if _HAS_INSTRUCTNAV and ProposerBus is not None else None
        self.goal_arbiter = GoalArbiter() if _HAS_INSTRUCTNAV and GoalArbiter is not None else None
        self.progress_timeout_steps = progress_timeout_steps
        self.max_semantic_replans = max_semantic_replans
        self.terminal_stop_timeout_steps = terminal_stop_timeout_steps
        self.scan_budget_steps = int(scan_budget_steps)
        self.frontier_budget_steps = int(frontier_budget_steps)
        # Baseline / pre-N-O2: frustum only. Candidate: memory → scan → frontier.
        # Without instructnav (historical BARN bundles), recovery stays off.
        self.instructnav_recovery = bool(instructnav_recovery) and _HAS_INSTRUCTNAV
        self._navigator = registry.create(model_id, arrive_radius_m=arrive_radius_m)
        self.mission: Mission | None = None
        self._best_goal_distance_m: float | None = None
        self._steps_without_progress = 0
        self._terminal_verification_steps = 0
        self._paused = False
        self._status_before_pause: str | None = None
        self._frozen_steps_without_progress = 0
        self._frozen_terminal_verification_steps = 0
        self._scan_steps = 0
        self._frontier_steps = 0
        self._recovery_phase = "frustum"  # frustum|memory|scan|frontier|failed
        self._frontier_target: tuple[float, float] | None = None
        self._frontier_viewpoints: list[tuple[float, float]] = []

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
        progress_config = dict(data.get("progress_watchdog") or {})
        terminal_config = dict(data.get("terminal_verification") or {})
        stop_m = float(safety.get("stop_distance_m", 0.8))
        max_vyaw = float(safety.get("max_vyaw", 1.5))
        predictive_mode = str(
            overrides.get("predictive_mode", safety.get("predictive_mode", "stop"))
        )
        # Lazy: keep BARN v8 shield off the default import/grep surface.
        from .experimental_all_ray_shield import V8_ALL_RAY_MODE, V8AllRayShieldConfig

        all_ray_shield: V8AllRayShieldConfig | None = None
        if predictive_mode == V8_ALL_RAY_MODE:
            raw_all_ray_profile = safety.get("all_ray_yaw_swept_cap")
            if not isinstance(raw_all_ray_profile, dict):
                raise ValueError(
                    "all-ray predictive mode requires an exact safety.all_ray_yaw_swept_cap mapping"
                )
            all_ray_shield = V8AllRayShieldConfig.from_mapping(raw_all_ray_profile)
            if not math.isclose(
                all_ray_shield.stop_distance_m,
                stop_m,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError("all-ray and collision stop distances must match exactly")
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
                person_stop_m=float(
                    overrides.get("person_stop_m", safety.get("person_stop_m", stop_m + 0.4))
                ),
                person_slow_m=float(
                    overrides.get("person_slow_m", safety.get("person_slow_m", 2.5))
                ),
                obstacle_stop_m=float(
                    overrides.get("obstacle_stop_m", safety.get("obstacle_stop_m", stop_m))
                ),
                obstacle_slow_m=float(
                    overrides.get("obstacle_slow_m", safety.get("obstacle_slow_m", 1.2))
                ),
                slow_scale=float(overrides.get("slow_scale", safety.get("slow_scale", 0.35))),
                reaction_time_s=float(
                    overrides.get("reaction_time_s", safety.get("reaction_time_s", 0.12))
                ),
                predictive_mode=predictive_mode,
            ),
            safety=safety,
            all_ray_shield=all_ray_shield,
            search=ActiveSemanticSearch(
                max_steps=int(
                    overrides.get("search_max_steps", search_config.get("max_steps", 80))
                ),
                yaw_rate=min(
                    max_vyaw,
                    float(overrides.get("search_yaw_rate", search_config.get("yaw_rate", 0.35))),
                ),
            ),
            progress_timeout_steps=int(
                overrides.get(
                    "progress_timeout_steps",
                    progress_config.get("timeout_steps", 400),
                )
            ),
            max_semantic_replans=int(
                overrides.get(
                    "max_semantic_replans",
                    progress_config.get("max_semantic_replans", 2),
                )
            ),
            terminal_stop_timeout_steps=int(
                overrides.get(
                    "terminal_stop_timeout_steps",
                    terminal_config.get("stop_timeout_steps", 30),
                )
            ),
            scan_budget_steps=int(
                overrides.get(
                    "scan_budget_steps",
                    search_config.get("max_steps", 80),
                )
            ),
            frontier_budget_steps=int(
                overrides.get(
                    "frontier_budget_steps",
                    search_config.get("frontier_budget_steps", 300),
                )
            ),
            instructnav_recovery=bool(
                overrides.get(
                    "instructnav_recovery",
                    data.get("instructnav_recovery", True),
                )
            ),
            semantic_memory=overrides.get("semantic_memory"),
        )

    def set_model(self, model_id: str) -> None:
        if self._navigator is not None:
            self._navigator.close()
        self.model_id = model_id
        self._navigator = self.registry.create(model_id, arrive_radius_m=self.arrive_radius_m)

    def list_models(self):
        return self.registry.list()

    @property
    def dynamic_cost_active(self) -> bool:
        """Whether the active model planned against dynamic-agent costs last tick."""

        return bool(getattr(self._navigator, "dynamic_cost_active", False))

    def parse(self, directive: str) -> Mission:
        if navigation_directive_is_blocked(directive):
            raise ValueError("negated or hypothetical navigation directive")
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
        self._best_goal_distance_m = None
        self._steps_without_progress = 0
        self._terminal_verification_steps = 0
        # Fresh start clears any prior pause (resume-as-fresh-dispatch).
        self._paused = False
        self._status_before_pause = None
        self._frozen_steps_without_progress = 0
        self._frozen_terminal_verification_steps = 0
        self._scan_steps = 0
        self._frontier_steps = 0
        self._frontier_target = None
        self._frontier_viewpoints = []
        self._recovery_phase = "frustum"
        mission.metadata.pop("paused", None)
        mission.metadata.setdefault("replan_count", 0)
        mission.metadata.setdefault(
            "grounding_outcome",
            GroundingOutcome.UNSEEN.value if GroundingOutcome is not None else "UNSEEN",
        )
        mission.metadata.setdefault("recovery_phase", "frustum")
        if mission.goal is not None:
            self._navigator.reset(mission)
        self.mission = mission
        return mission

    def done(self) -> bool:
        return self.mission is None or self.mission.status in {"arrived", "failed", "idle"}

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """Freeze tick budgets and retain the Mission (≠ ``stop()``)."""

        if self.mission is None or self._paused:
            return
        if self.mission.status in {"arrived", "failed", "idle"}:
            return
        self._status_before_pause = self.mission.status_value()
        self._frozen_steps_without_progress = self._steps_without_progress
        self._frozen_terminal_verification_steps = self._terminal_verification_steps
        # String literal keeps BARN historical-bundle base.py import-compatible.
        self.mission.status = "paused"
        self.mission.metadata["paused"] = True
        self._paused = True

    def resume(self) -> None:
        if not self._paused or self.mission is None:
            return
        restored = self._status_before_pause or "running"
        self.mission.status = restored
        self.mission.metadata.pop("paused", None)
        self._steps_without_progress = self._frozen_steps_without_progress
        self._terminal_verification_steps = self._frozen_terminal_verification_steps
        self._status_before_pause = None
        self._paused = False

    def snapshot(self) -> dict[str, object]:
        mission = self.mission
        return {
            "paused": self._paused,
            "steps_without_progress": self._steps_without_progress,
            "terminal_verification_steps": self._terminal_verification_steps,
            "mission_status": None if mission is None else mission.status_value(),
            "has_mission": mission is not None,
        }

    def step(self, observation: NavObservation) -> MidLevelCommand:
        if self.mission is None:
            return MidLevelCommand(stop=True, note="no_mission")
        if self._paused:
            # Budgets stay frozen; do not advance watchdog counters.
            return MidLevelCommand(stop=True, note="mission_paused")
        if self.mission.goal is None:
            return self._step_semantic_resolution(observation)
        if self.mission.status == "verifying":
            return self._step_terminal_verification(observation)
        control_observation = self._control_observation(observation)
        cmd = self._navigator.act(control_observation, self.mission)
        if cmd.stop or self.mission.status == "arrived":
            if self.mission.semantic_goal is None:
                self.mission.status = "arrived"
                return MidLevelCommand(stop=True, note=cmd.note or "arrived")
            # Reaching the geometric tolerance only requests a stop. Semantic
            # success is published after current camera/LiDAR relation checks
            # and the locomotion controller's measured-stop confirmation.
            self.mission.status = "verifying"
            self.mission.metadata["plan_step"] = "verify_relation_and_stopped"
            self._terminal_verification_steps = 0
            return self._step_terminal_verification(observation, entering=True)

        stalled = self._progress_watchdog(control_observation)
        if stalled is not None:
            return stalled

        obstacle_bearing = control_observation.extras.get("obstacle_bearing_rad")
        if not isinstance(obstacle_bearing, (int, float)):
            obstacle_bearing = None
        vx, vy, cnote = apply_collision_brake(
            cmd.vx,
            cmd.vy,
            nearest_person_m=control_observation.nearest_person_m,
            nearest_obstacle_m=control_observation.nearest_obstacle_m,
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
        if self.all_ray_shield is not None:
            from .experimental_all_ray_shield import apply_v8_all_ray_shield

            try:
                shield = apply_v8_all_ray_shield(
                    vx,
                    vy,
                    vyaw,
                    control_observation.lidar,
                    angle_min_rad=control_observation.extras.get("lidar_angle_min_rad"),
                    angle_increment_rad=control_observation.extras.get("lidar_angle_increment_rad"),
                    config=self.all_ray_shield,
                )
            except (TypeError, ValueError, RuntimeError):
                vx = 0.0
                vy = 0.0
                cnote = f"{cnote}|all_ray_contract_invalid_stop"
            else:
                vx = shield.output_vx_mps
                vy = shield.output_vy_mps
                cnote = f"{cnote}|{shield.note}"
        note = f"{cmd.note}|{cnote}" if cmd.note else cnote
        if cnote.endswith("_stop"):
            return MidLevelCommand(vx=0.0, vy=0.0, vyaw=vyaw, stop=False, note=note)
        return MidLevelCommand(vx=vx, vy=vy, vyaw=vyaw, stop=False, note=note)

    def _control_observation(self, observation: NavObservation) -> NavObservation:
        """Exclude only a validated relational target from local obstacle evasion.

        A lamppost remains present in raw LiDAR and terminal verification, but
        the point controller must be allowed to approach its precomputed safe
        stand-off pose. All other returns remain collision obstacles, and the
        runtime's independent final brake still sees the unmodified sensor view.
        """

        if (
            self.mission is None
            or self.mission.semantic_goal is None
            or self.mission.semantic_goal.terminal_relation not in {"near", "next_to", "towards"}
        ):
            return observation
        target_ids = _obstacle_ids(self.mission.metadata)
        if not target_ids:
            return observation
        raw_lidar = observation.extras.get("lidar_obstacles")
        if not isinstance(raw_lidar, (list, tuple)):
            if observation.extras.get("obstacle_id") not in target_ids:
                return observation
            extras = dict(observation.extras)
            extras.update(
                {
                    "obstacle_id": None,
                    "obstacle_bearing_rad": None,
                    "terminal_target_clearance_m": observation.nearest_obstacle_m,
                }
            )
            return replace(observation, nearest_obstacle_m=None, extras=extras)

        alternatives: list[tuple[float, float, str | None]] = []
        target_clearance: float | None = None
        for item in raw_lidar[:64]:
            if not isinstance(item, dict):
                continue
            obstacle_id = str(item["id"]) if item.get("id") else None
            try:
                distance = float(item["distance_m"])
                bearing = float(item["bearing_rad"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                not math.isfinite(distance)
                or not math.isfinite(bearing)
                or distance < 0.0
                or not -math.pi <= bearing <= math.pi
            ):
                continue
            if obstacle_id in target_ids:
                target_clearance = (
                    distance if target_clearance is None else min(target_clearance, distance)
                )
            else:
                alternatives.append((distance, bearing, obstacle_id))
        nearest = min(alternatives, default=None, key=lambda item: item[0])
        extras = dict(observation.extras)
        extras["terminal_target_clearance_m"] = target_clearance
        extras["obstacle_id"] = nearest[2] if nearest is not None else None
        extras["obstacle_bearing_rad"] = nearest[1] if nearest is not None else None
        return replace(
            observation,
            nearest_obstacle_m=nearest[0] if nearest is not None else None,
            extras=extras,
        )

    def _ingest_memory(self, observation: NavObservation) -> None:
        if self.memory is None:
            return
        raw = observation.extras.get("semantic_candidates", [])
        if not isinstance(raw, (list, tuple)):
            return
        now = float(observation.extras.get("time_s") or 0.0)
        if not math.isfinite(now):
            now = 0.0
        entities: list[dict[str, object]] = []
        for item in raw[:64]:
            if not isinstance(item, dict):
                continue
            entities.append(
                {
                    "id": item.get("id"),
                    "label": item.get("label"),
                    "kind": item.get("kind", "object"),
                    "position": item.get("position")
                    or item.get("centroid")
                    or (
                        [
                            sum(float(p[0]) for p in (item.get("polygon") or []))
                            / max(len(item.get("polygon") or []), 1),
                            sum(float(p[1]) for p in (item.get("polygon") or []))
                            / max(len(item.get("polygon") or []), 1),
                        ]
                        if item.get("polygon")
                        else None
                    ),
                    "polygon": item.get("polygon"),
                    "confidence": item.get("confidence", 0.98),
                }
            )
        if entities:
            self.memory.observe(entities, now_s=now)

    def _memory_candidates(
        self, semantic_goal: Any, observation: NavObservation
    ) -> list[SemanticCandidate]:
        if self.memory is None:
            return []
        now = float(observation.extras.get("time_s") or 0.0)
        recalled = self.memory.recall(semantic_goal.query, now_s=now)
        # Also try alias-normalized recalls via frustum matcher on memory snapshots.
        if not recalled:
            for entity in self.memory.recall_all(now_s=now):
                if _label_matches(semantic_goal.query, entity.label, ()):
                    recalled = (*recalled, entity)
        out: list[SemanticCandidate] = []
        for entity in recalled:
            if entity.kind != semantic_goal.kind and not (
                semantic_goal.kind == "region" and entity.kind == "region"
            ):
                # Allow object queries against object memories only.
                if semantic_goal.kind == "object" and entity.kind != "object":
                    continue
                if semantic_goal.kind == "region" and entity.kind != "region":
                    continue
            out.append(
                SemanticCandidate(
                    candidate_id=entity.entity_id,
                    label=entity.label,
                    x=entity.x,
                    y=entity.y,
                    confidence=entity.confidence,
                    kind=entity.kind,
                    polygon=entity.polygon or (),
                    source="semantic_memory",
                    observed_at=entity.last_seen_s,
                    reachable=True,
                    metadata={},
                )
            )
        robot_x, robot_y = observation.position[:2]
        return sorted(
            out,
            key=lambda item: (
                -item.confidence,
                math.hypot(item.x - robot_x, item.y - robot_y),
                item.candidate_id,
            ),
        )

    def _commit_semantic_candidate(
        self,
        semantic_goal: Any,
        result: SemanticCandidate,
        observation: NavObservation,
        *,
        grounding_outcome: str,
    ) -> MidLevelCommand:
        assert self.mission is not None
        pose = safe_approach_pose(
            semantic_goal,
            result,
            observation,
            footprint_clearance_m=ROBOT_FOOTPRINT_RADIUS_M,
            obstacle_stop_m=self.collision.obstacle_stop_m,
        )
        if pose is None:
            self.mission.status = "failed"
            self.mission.metadata["resolution_state"] = "unreachable"
            self.mission.metadata["grounding_outcome"] = grounding_outcome
            return MidLevelCommand(stop=True, note="semantic_target_unreachable")
        self.mission.goal = pose
        self.mission.status = "running"
        self.mission.metadata.update(
            {
                "resolution_state": "resolved",
                "grounding_outcome": grounding_outcome,
                "recovery_phase": self._recovery_phase,
                "candidate_id": result.candidate_id,
                "candidate_confidence": result.confidence,
                "candidate_source": result.source,
                "target_polygon": result.polygon,
                "terminal_relation": semantic_goal.terminal_relation,
                "terminal_behavior": semantic_goal.terminal_behavior,
                "candidate_position": (result.x, result.y, result.z),
                "candidate_radius_m": _metadata_float(
                    result.metadata, "radius_m", default=0.0, minimum=0.0, maximum=5.0
                ),
                "associated_lidar_ids": sorted(_candidate_obstacle_ids(result)),
                "terminal_clearance_m": _metadata_float(
                    result.metadata,
                    "terminal_clearance_m",
                    default=0.32,
                    minimum=0.10,
                    maximum=1.0,
                ),
                "vicinity_radius_m": _metadata_float(
                    result.metadata,
                    "vicinity_radius_m",
                    default=math.hypot(pose.x - result.x, pose.y - result.y)
                    + (pose.arrival_radius_m or 0.12),
                    minimum=0.5,
                    maximum=4.0,
                ),
                "minimum_vicinity_radius_m": _metadata_float(
                    result.metadata,
                    "minimum_vicinity_radius_m",
                    default=_metadata_float(
                        result.metadata,
                        "radius_m",
                        default=0.0,
                        minimum=0.0,
                        maximum=2.0,
                    )
                    + ROBOT_FOOTPRINT_RADIUS_M
                    + max(
                        self.collision.obstacle_stop_m,
                        _metadata_float(
                            result.metadata,
                            "target_min_surface_clearance_m",
                            default=self.collision.obstacle_stop_m,
                            minimum=0.1,
                            maximum=2.0,
                        ),
                    ),
                    minimum=0.4,
                    maximum=4.0,
                ),
                "terminal_support_clearance_m": _metadata_float(
                    result.metadata,
                    "terminal_support_clearance_m",
                    default=0.32,
                    minimum=0.1,
                    maximum=1.0,
                ),
                "support_polygon": result.metadata.get("support_polygon") or (),
                "plan": (
                    "confirm_target_from_camera_depth",
                    "choose_collision_free_terminal_pose",
                    "align_then_translate",
                    f"verify_{semantic_goal.terminal_relation}_and_stopped",
                ),
                "plan_step": "align_then_translate",
            }
        )
        now_s = float(observation.extras.get("time_s") or 0.0)
        if (
            _HAS_INSTRUCTNAV
            and SE2Goal is not None
            and self.proposer_bus is not None
            and self.goal_arbiter is not None
        ):
            proposed = SE2Goal(
                source="grounder",
                pose=(pose.x, pose.y, math.radians(pose.heading_deg)),
                confidence=float(result.confidence),
                ttl_s=2.0,
                plan_step_id="align_then_translate",
                issued_s=now_s,
                priority=10,
            )
            self.proposer_bus.publish(proposed)
            self.goal_arbiter.set_plan_step("align_then_translate")
            chosen = self.goal_arbiter.resolve((proposed,), now_s=now_s)
            if chosen is None:
                self.mission.status = "failed"
                self.mission.metadata["resolution_state"] = "arbiter_veto"
                return MidLevelCommand(stop=True, note="semantic_goal_vetoed")
        self._navigator.reset(self.mission)
        self._best_goal_distance_m = math.hypot(
            pose.x - observation.position[0],
            pose.y - observation.position[1],
        )
        self._steps_without_progress = 0
        self._terminal_verification_steps = 0
        return MidLevelCommand(vx=0.0, vy=0.0, vyaw=0.0, note="semantic_target_resolved")

    def _step_semantic_resolution(self, observation: NavObservation) -> MidLevelCommand:
        """Frustum → memory → ScanForTarget → frontier → honest refusal.

        When ``instructnav_recovery`` is False (``--mode baseline``), only the
        current frustum is considered — no memory, scan, or frontier.
        """

        assert self.mission is not None
        semantic_goal = self.mission.semantic_goal
        if semantic_goal is None:
            self.mission.status = "failed"
            return MidLevelCommand(stop=True, note="semantic_goal_missing")

        if self.instructnav_recovery:
            self._ingest_memory(observation)
        frustum = self.semantic_map.query(semantic_goal, observation)
        memory_hits = (
            self._memory_candidates(semantic_goal, observation)
            if self.instructnav_recovery
            else []
        )
        robot_x, robot_y = observation.position[:2]
        grounded = resolve_grounding(
            frustum=[
                {
                    "id": c.candidate_id,
                    "label": c.label,
                    "confidence": c.confidence,
                    "x": c.x,
                    "y": c.y,
                    "distance_m": math.hypot(c.x - robot_x, c.y - robot_y),
                    "candidate": c,
                }
                for c in frustum
            ],
            memory=[
                {
                    "id": c.candidate_id,
                    "label": c.label,
                    "confidence": c.confidence,
                    "x": c.x,
                    "y": c.y,
                    "distance_m": math.hypot(c.x - robot_x, c.y - robot_y),
                    "candidate": c,
                }
                for c in memory_hits
            ],
        )
        self.mission.metadata["grounding_outcome"] = grounded.outcome.value

        if grounded.outcome == GroundingOutcome.AMBIGUOUS:
            self.mission.status = "failed"
            self.mission.metadata["resolution_state"] = "ambiguous"
            self.mission.metadata["reply"] = (
                f"I can see more than one {semantic_goal.query}; "
                "please say which one you mean."
            )
            return MidLevelCommand(stop=True, note="semantic_target_ambiguous")

        if not self.instructnav_recovery:
            if grounded.outcome == GroundingOutcome.RESOLVED and grounded.candidate is not None:
                candidate = grounded.candidate.get("candidate")
                if isinstance(candidate, SemanticCandidate):
                    return self._commit_semantic_candidate(
                        semantic_goal,
                        candidate,
                        observation,
                        grounding_outcome=GroundingOutcome.RESOLVED.value,
                    )
            # Baseline: frustum miss → honest grounding refusal (no recovery).
            reply = honest_not_found_reply(
                semantic_goal.query, scanned=False, searched=False
            )
            self.mission.status = "failed"
            self.mission.metadata.update(
                {
                    "resolution_state": "unseen",
                    "grounding_outcome": GroundingOutcome.UNSEEN.value,
                    "recovery_phase": "baseline_frustum_only",
                    "reply": reply,
                }
            )
            return MidLevelCommand(stop=True, note="semantic_target_not_found")

        if grounded.outcome == GroundingOutcome.MEMORY_HIT and self._recovery_phase != "scan":
            assert grounded.candidate is not None
            candidate = grounded.candidate.get("candidate")
            if not isinstance(candidate, SemanticCandidate):
                self.mission.status = "failed"
                return MidLevelCommand(stop=True, note="semantic_candidate_invalid")
            self._recovery_phase = "memory"
            return self._commit_semantic_candidate(
                semantic_goal,
                candidate,
                observation,
                grounding_outcome=GroundingOutcome.MEMORY_HIT.value,
            )

        # ScanForTarget: in-place yaw search (ActiveSemanticSearch), then
        # SearchOwner-style frontier rings toward last memory / robot pose.
        if self._recovery_phase != "frontier":
            if grounded.outcome == GroundingOutcome.UNSEEN:
                self._recovery_phase = "scan"
            else:
                self._recovery_phase = "frustum"
            self.mission.status = "searching"
            self.mission.metadata["recovery_phase"] = self._recovery_phase
            self.mission.metadata["resolution_state"] = "searching"
            result = self.search.observe(semantic_goal, self.semantic_map, observation)
            self._scan_steps += 1
            if isinstance(result, SemanticCandidate):
                return self._commit_semantic_candidate(
                    semantic_goal,
                    result,
                    observation,
                    grounding_outcome=GroundingOutcome.RESOLVED.value,
                )
            if isinstance(result, MidLevelCommand) and not result.stop:
                return MidLevelCommand(
                    vx=0.0,
                    vy=0.0,
                    vyaw=result.vyaw,
                    note=result.note or "semantic_search_scan",
                )
            if self.frontier_budget_steps <= 0:
                reply = honest_not_found_reply(
                    semantic_goal.query, scanned=self._scan_steps > 0, searched=False
                )
                self.mission.status = "failed"
                self.mission.metadata.update(
                    {
                        "resolution_state": "not_found",
                        "grounding_outcome": GroundingOutcome.UNSEEN.value,
                        "recovery_phase": "failed",
                        "reply": reply,
                    }
                )
                return MidLevelCommand(stop=True, note="semantic_target_not_found")
            self._recovery_phase = "frontier"
            self.mission.metadata["recovery_phase"] = "frontier"
            self._frontier_target = None

        return self._step_scan_for_target_frontier(semantic_goal, observation)

    def _step_scan_for_target_frontier(
        self,
        semantic_goal: Any,
        observation: NavObservation,
    ) -> MidLevelCommand:
        """Bounded frontier crawl using SearchOwner-style ring scoring."""

        assert self.mission is not None
        self._frontier_steps += 1
        robot_xy = (float(observation.position[0]), float(observation.position[1]))
        self._record_frontier_viewpoint(robot_xy)

        frontier_hits = self.semantic_map.query(semantic_goal, observation)
        if frontier_hits:
            return self._commit_semantic_candidate(
                semantic_goal,
                frontier_hits[0],
                observation,
                grounding_outcome=GroundingOutcome.RESOLVED.value,
            )
        mem = self._memory_candidates(semantic_goal, observation)
        if mem:
            return self._commit_semantic_candidate(
                semantic_goal,
                mem[0],
                observation,
                grounding_outcome=GroundingOutcome.MEMORY_HIT.value,
            )

        if self._frontier_steps >= self.frontier_budget_steps:
            scanned = self._scan_steps > 0
            searched = self._frontier_steps > 0
            reply = honest_not_found_reply(
                semantic_goal.query, scanned=scanned, searched=searched
            )
            self.mission.status = "failed"
            self.mission.metadata.update(
                {
                    "resolution_state": "not_found",
                    "grounding_outcome": GroundingOutcome.UNSEEN.value,
                    "recovery_phase": "failed",
                    "reply": reply,
                }
            )
            return MidLevelCommand(stop=True, note="semantic_target_not_found")

        origin = robot_xy
        if self.mission.metadata.get("last_seen_xy"):
            raw = self.mission.metadata["last_seen_xy"]
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                origin = (float(raw[0]), float(raw[1]))

        if self._frontier_target is None or math.hypot(
            self._frontier_target[0] - robot_xy[0],
            self._frontier_target[1] - robot_xy[1],
        ) < 0.35:
            self._frontier_target = self._select_semantic_frontier(origin, robot_xy)

        if self._frontier_target is None:
            # No uncovered ring sample — spin in place (still named ScanForTarget).
            return MidLevelCommand(
                vx=0.0,
                vy=0.0,
                vyaw=0.35,
                note="semantic_scan_for_target",
            )

        dx = self._frontier_target[0] - robot_xy[0]
        dy = self._frontier_target[1] - robot_xy[1]
        heading = float(observation.position[2]) if len(observation.position) > 2 else 0.0
        bearing = math.atan2(dy, dx) - heading
        while bearing > math.pi:
            bearing -= 2.0 * math.pi
        while bearing < -math.pi:
            bearing += 2.0 * math.pi
        if abs(bearing) > 0.45:
            return MidLevelCommand(
                vx=0.0,
                vy=0.0,
                vyaw=max(-0.6, min(0.6, 1.6 * bearing)),
                note="semantic_scan_for_target",
            )
        return MidLevelCommand(
            vx=0.22,
            vy=0.0,
            vyaw=max(-0.35, min(0.35, 0.8 * bearing)),
            note="semantic_frontier_search",
        )

    def _select_semantic_frontier(
        self,
        origin: tuple[float, float],
        robot_xy: tuple[float, float],
        *,
        rings: int = 3,
        bearings: int = 8,
        ring_step_m: float = 1.2,
        travel_weight: float = 0.15,
    ) -> tuple[float, float] | None:
        """SearchOwner-style ring candidates scored by novelty − travel."""

        scored: list[tuple[float, int, tuple[float, float]]] = []
        index = 0
        for ring in range(1, rings + 1):
            radius = ring * ring_step_m
            for step in range(bearings):
                angle = 2.0 * math.pi * step / bearings
                candidate = (
                    origin[0] + math.cos(angle) * radius,
                    origin[1] + math.sin(angle) * radius,
                )
                index += 1
                if self._frontier_already_covered(candidate):
                    continue
                travel = math.hypot(candidate[0] - robot_xy[0], candidate[1] - robot_xy[1])
                gain = 1.0  # no occupancy grid here — coverage novelty only
                scored.append((gain - travel_weight * travel, index, candidate))
        if not scored:
            return None
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][2]

    def _frontier_already_covered(self, candidate: tuple[float, float]) -> bool:
        radius = 1.5
        return any(
            math.hypot(candidate[0] - x, candidate[1] - y) <= radius
            for x, y in self._frontier_viewpoints
        )

    def _record_frontier_viewpoint(self, position: tuple[float, float]) -> None:
        spacing = 0.8
        if not self._frontier_viewpoints or all(
            math.hypot(position[0] - x, position[1] - y) > spacing
            for x, y in self._frontier_viewpoints[-4:]
        ):
            self._frontier_viewpoints.append(position)
        if len(self._frontier_viewpoints) > 256:
            del self._frontier_viewpoints[:128]

    def _progress_watchdog(self, observation: NavObservation) -> MidLevelCommand | None:
        assert self.mission is not None and self.mission.goal is not None
        distance = math.hypot(
            self.mission.goal.x - observation.position[0],
            self.mission.goal.y - observation.position[1],
        )
        if self._best_goal_distance_m is None or distance < self._best_goal_distance_m - 0.025:
            self._best_goal_distance_m = distance
            self._steps_without_progress = 0
            return None
        self._steps_without_progress += 1
        if self._steps_without_progress < self.progress_timeout_steps:
            return None

        replans = int(self.mission.metadata.get("replan_count", 0))
        if self.mission.semantic_goal is not None and replans < self.max_semantic_replans:
            return self._begin_semantic_replan(
                replans,
                note="semantic_replan_after_no_progress",
            )

        self.mission.status = "failed"
        self.mission.metadata["resolution_state"] = "stalled"
        self.mission.metadata["plan_step"] = "failed"
        return MidLevelCommand(stop=True, note="navigation_no_progress")

    def _begin_semantic_replan(self, replans: int, *, note: str) -> MidLevelCommand:
        assert self.mission is not None and self.mission.semantic_goal is not None
        self.mission.goal = None
        self.mission.status = "searching"
        self.mission.metadata.update(
            {
                "replan_count": replans + 1,
                "resolution_state": note,
                "plan_step": "confirm_target_from_camera_depth",
            }
        )
        self.search.reset()
        self._best_goal_distance_m = None
        self._steps_without_progress = 0
        self._terminal_verification_steps = 0
        self._recovery_phase = "frustum"
        self._scan_steps = 0
        self._frontier_steps = 0
        self._frontier_target = None
        self._frontier_viewpoints = []
        return MidLevelCommand(note=note)

    def _step_terminal_verification(
        self,
        observation: NavObservation,
        *,
        entering: bool = False,
    ) -> MidLevelCommand:
        """Hold zero until both the live relation and physical stop are true."""

        assert self.mission is not None and self.mission.semantic_goal is not None
        relation_verified = self._semantic_arrival_verified(observation)
        self.mission.metadata["terminal_relation_verified"] = relation_verified
        if _motion_feedback_is_settled(observation):
            if relation_verified:
                self.mission.status = "arrived"
                self.mission.metadata["resolution_state"] = "verified"
                self.mission.metadata["plan_step"] = "completed"
                return MidLevelCommand(stop=True, note="arrived_verified")
            replans = int(self.mission.metadata.get("replan_count", 0))
            if replans < self.max_semantic_replans:
                return self._begin_semantic_replan(
                    replans,
                    note="semantic_replan_after_verification_failure",
                )
            self.mission.status = "failed"
            self.mission.metadata["resolution_state"] = "verification_failed"
            self.mission.metadata["plan_step"] = "failed"
            return MidLevelCommand(stop=True, note="semantic_arrival_verification_failed")

        self._terminal_verification_steps += 1
        if self._terminal_verification_steps >= self.terminal_stop_timeout_steps:
            self.mission.status = "failed"
            self.mission.metadata["resolution_state"] = "stop_not_confirmed"
            self.mission.metadata["plan_step"] = "failed"
            return MidLevelCommand(stop=True, note="terminal_stop_not_confirmed")
        return MidLevelCommand(
            stop=True,
            note=(
                "semantic_stop_requested" if entering else "semantic_waiting_for_stop_confirmation"
            ),
        )

    def _semantic_arrival_verified(self, observation: NavObservation) -> bool:
        if self.mission is None or self.mission.semantic_goal is None:
            return True
        relation = self.mission.semantic_goal.terminal_relation
        position = (observation.position[0], observation.position[1])
        if observation.extras.get("perception_fresh") is not True:
            return False
        if not self._terminal_environment_is_clear(observation, relation=relation):
            return False
        candidate = _current_semantic_candidate(
            observation,
            self.mission.metadata,
            expected_kind=self.mission.semantic_goal.kind,
            minimum_confidence=self.mission.semantic_goal.minimum_confidence,
        )
        if candidate is None:
            return False
        if relation == "inside":
            polygon = _polygon(candidate.get("polygon"))
            clearance = float(self.mission.metadata.get("terminal_clearance_m", 0.32))
            return bool(polygon) and point_in_polygon_with_clearance(position, polygon, clearance)
        if relation in {"near", "next_to", "towards"}:
            candidate_position = _position(candidate.get("position"))
            if candidate_position is None:
                return False
            distance = math.hypot(
                position[0] - candidate_position[0],
                position[1] - candidate_position[1],
            )
            if relation == "towards":
                # Stop-short success: within ~2.5 m and not past the object.
                return 0.6 <= distance <= 2.5
            if relation == "next_to":
                return 0.35 <= distance <= 1.6
            minimum = float(self.mission.metadata.get("minimum_vicinity_radius_m", 0.0))
            maximum = float(self.mission.metadata.get("vicinity_radius_m", 1.35))
            if not minimum <= distance <= maximum:
                return False
            target_clearance = _current_target_clearance(
                observation,
                _obstacle_ids(self.mission.metadata),
            )
            radius = float(self.mission.metadata.get("candidate_radius_m", 0.0))
            minimum_surface = max(
                0.0,
                minimum - radius - ROBOT_FOOTPRINT_RADIUS_M,
            )
            maximum_surface = maximum - radius - ROBOT_FOOTPRINT_RADIUS_M
            if (
                target_clearance is None
                or maximum_surface < minimum_surface
                or not minimum_surface - 1e-6 <= target_clearance <= maximum_surface + 1e-6
            ):
                return False
            support = _polygon(self.mission.metadata.get("support_polygon"))
            support_clearance = float(
                self.mission.metadata.get("terminal_support_clearance_m", 0.32)
            )
            return not support or point_in_polygon_with_clearance(
                position, support, support_clearance
            )
        return False

    def _terminal_environment_is_clear(
        self,
        observation: NavObservation,
        *,
        relation: str,
    ) -> bool:
        if observation.extras.get("collision") is not False:
            return False
        if (
            observation.nearest_person_m is not None
            and observation.nearest_person_m < self.collision.person_stop_m
        ):
            return False
        target_ids = (
            _obstacle_ids(self.mission.metadata)
            if self.mission is not None and relation in {"near", "next_to", "towards"}
            else frozenset()
        )
        raw = observation.extras.get("lidar_obstacles")
        if isinstance(raw, (list, tuple)):
            for item in raw[:64]:
                if not isinstance(item, dict):
                    return False
                if item.get("id") in target_ids:
                    continue
                distance = item.get("distance_m")
                if (
                    isinstance(distance, bool)
                    or not isinstance(distance, (int, float))
                    or not math.isfinite(float(distance))
                    or float(distance) < 0.0
                ):
                    return False
                if float(distance) < self.collision.obstacle_stop_m:
                    return False
        return (
            observation.nearest_obstacle_m is None
            or observation.extras.get("obstacle_id") in target_ids
            or observation.nearest_obstacle_m >= self.collision.obstacle_stop_m
        )

    def stop(self) -> None:
        if self.mission is not None:
            self.mission.status = "idle"
        self.mission = None
        self._best_goal_distance_m = None
        self._steps_without_progress = 0
        self._terminal_verification_steps = 0
        self._paused = False
        self._status_before_pause = None
        self._frozen_steps_without_progress = 0
        self._frozen_terminal_verification_steps = 0

    def close(self) -> None:
        self.stop()
        self._navigator.close()


def _label_matches(query: str, label: str, aliases: tuple[str, ...] | list[str]) -> bool:
    from .semantic_map import _matches

    return _matches(query, label, aliases)


def _metadata_float(
    metadata: dict[str, Any],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(metadata.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and minimum <= value <= maximum else default


def _polygon(value: object) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return ()
    try:
        polygon = tuple((float(point[0]), float(point[1])) for point in value)
    except (IndexError, TypeError, ValueError):
        return ()
    return polygon if all(math.isfinite(axis) for point in polygon for axis in point) else ()


def _position(value: object) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        position = (
            float(value[0]),
            float(value[1]),
            float(value[2]) if len(value) > 2 else 0.0,
        )
    except (TypeError, ValueError):
        return None
    return position if all(math.isfinite(axis) for axis in position) else None


def _current_semantic_candidate(
    observation: NavObservation,
    metadata: dict[str, Any],
    *,
    expected_kind: str,
    minimum_confidence: float,
) -> dict[str, Any] | None:
    candidate_id = metadata.get("candidate_id")
    raw = observation.extras.get("semantic_candidates")
    if not isinstance(candidate_id, str) or not isinstance(raw, (list, tuple)):
        return None
    for item in raw[:64]:
        if not isinstance(item, dict) or item.get("id") != candidate_id:
            continue
        confidence = item.get("confidence")
        reachable = item.get("reachable", True)
        if (
            item.get("kind") != expected_kind
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not minimum_confidence <= float(confidence) <= 1.0
            or reachable is not True
        ):
            return None
        return item
    return None


def _current_target_clearance(
    observation: NavObservation,
    target_ids: frozenset[str],
) -> float | None:
    if not target_ids:
        return None
    raw = observation.extras.get("lidar_obstacles")
    if not isinstance(raw, (list, tuple)):
        return None
    clearances: list[float] = []
    for item in raw[:64]:
        if not isinstance(item, dict) or item.get("id") not in target_ids:
            continue
        value = item.get("distance_m")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0.0
        ):
            return None
        clearances.append(float(value))
    return min(clearances, default=None)


def _motion_feedback_is_settled(observation: NavObservation) -> bool:
    feedback = observation.extras.get("motion_feedback")
    if not isinstance(feedback, dict):
        return False
    if feedback.get("fresh") is not True or feedback.get("stop_confirmed") is not True:
        return False
    values = (
        feedback.get("linear_speed_mps"),
        feedback.get("yaw_speed_rad_s"),
        feedback.get("settled_linear_speed_mps"),
        feedback.get("settled_yaw_speed_rad_s"),
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
        for value in values
    ):
        return False
    linear, yaw, linear_limit, yaw_limit = (float(value) for value in values)
    return linear <= linear_limit and yaw <= yaw_limit


def _candidate_obstacle_ids(candidate: object) -> frozenset[str]:
    candidate_id = getattr(candidate, "candidate_id", None)
    metadata = getattr(candidate, "metadata", {})
    ids = {candidate_id} if isinstance(candidate_id, str) and candidate_id else set()
    values = metadata.get("associated_lidar_ids") if isinstance(metadata, dict) else None
    if isinstance(values, (list, tuple)):
        ids.update(
            value for value in values[:16] if isinstance(value, str) and 0 < len(value) <= 128
        )
    return frozenset(ids)


def _obstacle_ids(metadata: dict[str, Any]) -> frozenset[str]:
    ids: set[str] = set()
    candidate_id = metadata.get("candidate_id")
    if isinstance(candidate_id, str) and candidate_id:
        ids.add(candidate_id)
    values = metadata.get("associated_lidar_ids")
    if isinstance(values, (list, tuple)):
        ids.update(
            value for value in values[:16] if isinstance(value, str) and 0 < len(value) <= 128
        )
    return frozenset(ids)
