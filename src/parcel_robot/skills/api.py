from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import yaml

from parcel_robot.config import ConfigStore
from parcel_robot.models import Pose, VelocityCommand
from parcel_robot.motion import MotionRouter, build_motion_router
from parcel_robot.paths import resolve_config_yaml, resolve_navigation_config

from .catalog import SkillCatalog
from .executor import ExecutionResult, SkillExecutor
from .schema import SkillSpec

REPO_ROOT = Path(__file__).resolve().parents[3]
FALLBACK_CONFIG = Path(__file__).resolve().parents[1] / "config" / "robot.yaml"


def _default_config() -> Path:
    try:
        return resolve_config_yaml("configs/robot.yaml")
    except FileNotFoundError:
        return FALLBACK_CONFIG


def _default_nav_config() -> Path:
    try:
        return resolve_navigation_config("configs/navigation/default.yaml")
    except FileNotFoundError:
        return REPO_ROOT / "configs" / "navigation" / "default.yaml"


DEFAULT_CONFIG = _default_config()
DEFAULT_NAV_CONFIG = _default_nav_config()


class Dog:
    """Public API for selecting and executing Go2 skills."""

    def __init__(
        self,
        catalog: SkillCatalog,
        executor: SkillExecutor,
        *,
        motion: MotionRouter | None = None,
        config_path: Path | None = None,
        navigation_config: Path | None = None,
    ):
        self.catalog = catalog
        self.executor = executor
        self.motion = motion
        self.config_path = config_path
        self.navigation_config = navigation_config
        self._navigator = None
        self._last_action = np.zeros(12, dtype=np.float64)
        self._velocity_cmd = VelocityCommand()
        self._obs_provider: Any = None
        self._nav_pose = (0.0, 0.0, 0.0)
        self._nav_heading_deg = 0.0

    @classmethod
    def from_config(
        cls,
        config_path: str | Path | None = None,
        *,
        sim_socket: str | None = None,
        motion: MotionRouter | None = None,
        on_pose=None,
        on_velocity=None,
        on_trajectory=None,
        on_stop=None,
    ) -> Dog:
        path = Path(config_path) if config_path else _default_config()
        if not path.is_file():
            path = FALLBACK_CONFIG
        store = ConfigStore(path)
        skills_root = store.skills_root()
        catalog = SkillCatalog.load(skills_root)
        router = motion
        if router is None:
            router = build_motion_router(store.motion_config())
        executor = SkillExecutor(
            catalog,
            motion=router,
            sim_socket=sim_socket,
            on_pose=on_pose,
            on_velocity=on_velocity,
            on_trajectory=on_trajectory,
            on_stop=on_stop,
        )
        nav_cfg = None
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        nav_block = raw.get("navigation") or {}
        if nav_block.get("enabled", True):
            configured = nav_block.get("config", "configs/navigation/default.yaml")
            candidate = Path(configured)
            if candidate.is_absolute():
                if candidate.is_file():
                    nav_cfg = candidate
            else:
                try:
                    nav_cfg = resolve_navigation_config(str(configured))
                except FileNotFoundError:
                    fallback = (REPO_ROOT / candidate).resolve()
                    if fallback.is_file():
                        nav_cfg = fallback
        return cls(catalog, executor, motion=router, config_path=path, navigation_config=nav_cfg)

    def list_skills(self, tag: str | None = None, kind: str | None = None) -> list[SkillSpec]:
        return self.catalog.list(tag=tag, kind=kind)

    def select(self, skill_id: str) -> SkillSpec:
        return self.executor.select(skill_id)

    def execute(self, skill_id: str, **overrides: float) -> ExecutionResult:
        result = self.executor.execute(skill_id, **overrides)
        skill = self.catalog.get(skill_id)
        if skill.kind in {"velocity", "gait"}:
            self._velocity_cmd = VelocityCommand(
                vx=float(overrides.get("vx", skill.velocity.vx)),
                vy=float(overrides.get("vy", skill.velocity.vy)),
                vyaw=float(overrides.get("vyaw", skill.velocity.vyaw)),
            )
        return result

    def stop(self) -> ExecutionResult:
        self._velocity_cmd = VelocityCommand()
        if self._navigator is not None:
            self._navigator.stop()
        return self.executor.stop()

    def poses(self) -> dict[str, Pose]:
        return self.catalog.as_pose_map()

    def _ensure_navigator(self):
        if self._navigator is not None:
            return self._navigator
        if self.navigation_config is None:
            raise RuntimeError(
                "navigation config missing; set navigation.config in robot.yaml "
                "or pass configs/navigation/default.yaml"
            )
        from parcel_robot.navigation import DirectiveNavigator

        self._navigator = DirectiveNavigator.from_config(self.navigation_config)
        return self._navigator

    @property
    def navigator(self):
        """Expose the directive navigator for pause/preempt wiring."""

        return self._ensure_navigator()

    def nav_dynamic_cost_active(self) -> bool:
        """Report the dynamic-cost layer without forcing navigator construction."""

        return bool(getattr(self._navigator, "dynamic_cost_active", False))

    def take_pending_ramp_seed(self) -> float | None:
        """Consume the navigator's yield-advance seed, if any (N11).

        Deliberately does not force navigator construction: a runtime with
        navigation disabled has no ramp memory and must not grow one here.
        """

        take = getattr(self._navigator, "take_pending_ramp_seed", None)
        return take() if callable(take) else None

    def list_nav_models(self):
        return self._ensure_navigator().list_models()

    def set_nav_model(self, model_id: str) -> None:
        self._ensure_navigator().set_model(model_id)

    def set_nav_pose(
        self,
        position: tuple[float, float, float] | list[float],
        heading_deg: float = 0.0,
    ) -> None:
        self._nav_pose = (float(position[0]), float(position[1]), float(position[2]))
        self._nav_heading_deg = float(heading_deg)

    def navigate(
        self,
        directive: str,
        *,
        nearest_person_m: float | None = None,
        nearest_obstacle_m: float | None = None,
        lidar: Any = None,
        model_id: str | None = None,
        publish: bool = True,
        extras: dict[str, Any] | None = None,
    ):
        """Ground a language directive and emit one collision-aware mid-level step.

        Returns ``(mission, MidLevelCommand)``. Call repeatedly with updated pose /
        proximity to continue the mission; ``MetaUrbanNavEnv`` currently provides
        only an offline kinematic RL-loop scaffold.
        """
        from parcel_robot.navigation import NavObservation

        nav = self._ensure_navigator()
        if model_id is not None:
            nav.set_model(model_id)
        if nav.mission is None or nav.mission.directive != directive or nav.done():
            mission = nav.start(directive)
        else:
            mission = nav.mission
        obs = NavObservation(
            position=self._nav_pose,
            heading_deg=self._nav_heading_deg,
            nearest_person_m=nearest_person_m,
            nearest_obstacle_m=nearest_obstacle_m,
            lidar=lidar,
            extras=dict(extras or {}),
        )
        cmd = nav.step(obs)
        if not cmd.stop:
            self._velocity_cmd = VelocityCommand(vx=cmd.vx, vy=cmd.vy, vyaw=cmd.vyaw)
            if publish and self.executor.on_velocity is not None:
                self.executor.on_velocity(self._velocity_cmd)
            elif publish and self.motion is not None:
                self.motion.walk(self._velocity_cmd)
        else:
            self._velocity_cmd = VelocityCommand()
        return mission, cmd

    def set_obs_provider(self, provider) -> None:
        self._obs_provider = provider

    def obs(self) -> np.ndarray:
        if self._obs_provider is not None:
            return np.asarray(self._obs_provider(), dtype=np.float64)
        # Offline stub observation for API smoke tests / dry runs.
        obs = np.zeros(48, dtype=np.float64)
        obs[0] = 1.0  # quat w
        skill_index = 0.0
        if self.executor.selected:
            try:
                skill_index = float(self.catalog.ids().index(self.executor.selected))
            except ValueError:
                skill_index = 0.0
        obs[43] = self._velocity_cmd.vx
        obs[44] = self._velocity_cmd.vy
        obs[45] = self._velocity_cmd.vyaw
        obs[46] = skill_index
        obs[31:43] = self._last_action
        return obs

    def step_policy(self, action) -> np.ndarray:
        self._last_action = np.asarray(action, dtype=np.float64).reshape(-1)[:12]
        if self._last_action.shape[0] < 12:
            padded = np.zeros(12, dtype=np.float64)
            padded[: self._last_action.shape[0]] = self._last_action
            self._last_action = padded
        return self.obs()
