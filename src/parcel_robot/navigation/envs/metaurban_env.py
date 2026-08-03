from __future__ import annotations

import math
from typing import Any, ClassVar

import numpy as np

from parcel_robot.navigation.base import GoalPose, Mission, NavObservation
from parcel_robot.navigation.envs.rewards import social_nav_reward
from parcel_robot.navigation.pipeline import DirectiveNavigator


class MetaUrbanNavEnv:
    """Gym-like kinematic city-navigation scaffold.

    The default kinematic world exercises RL-loop and navigator interfaces
    offline. ``use_metaurban=True`` is fail-closed until a real observation,
    action, reward, and lifecycle adapter is implemented; importing or resetting
    a vendor environment is not presented as functional integration.
    """

    metadata: ClassVar[dict[str, Any]] = {
        "render_modes": ["human", "none"],
        "name": "ParcelMetaUrbanNav-v0",
    }

    def __init__(
        self,
        *,
        navigator: DirectiveNavigator | None = None,
        density_ped: float = 1.0,
        density_obj: float = 0.4,
        mode: str = "social_nav",
        max_episode_steps: int = 400,
        use_metaurban: bool = False,
        seed: int | None = None,
    ):
        self.navigator = navigator or DirectiveNavigator.from_config()
        self.density_ped = density_ped
        self.density_obj = density_obj
        self.mode = mode
        self.max_episode_steps = max_episode_steps
        self.use_metaurban = use_metaurban
        self._rng = np.random.default_rng(seed)
        self._step_count = 0
        self._pos = np.zeros(3, dtype=np.float64)
        self._heading = 0.0
        self._people: list[np.ndarray] = []
        self._obstacles: list[np.ndarray] = []
        self._backend = None
        self.observation_space = {"shape": (8,), "dtype": "float64"}
        self.action_space = {"shape": (3,), "low": [-1, -1, -1], "high": [1, 1, 1]}
        if use_metaurban:
            self._init_metaurban()

    def _init_metaurban(self) -> None:
        try:
            import metaurban as _metaurban  # type: ignore  # noqa: F401
        except ImportError as error:
            raise ImportError(
                "metaurban is not installed. Run ./scripts/setup_metaurban.sh "
                "on a Conda Python 3.9 + GPU host. See docs/NAVIGATION_CITY.md"
            ) from error
        raise NotImplementedError(
            "MetaUrban is installed, but Parcel's real step/observation adapter "
            "is not implemented. Use use_metaurban=False for the kinematic "
            "scaffold and see docs/NAVIGATION_CITY.md."
        )

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        options = options or {}
        self._step_count = 0
        directive = str(options.get("directive", "go to the coffee shop at 42nd street"))
        mission = self.navigator.start(directive)
        self._pos[:] = options.get("start", [0.0, 0.0, 0.0])
        self._heading = float(options.get("heading_deg", 0.0))
        self._spawn_agents(mission.goal)
        if self._backend is not None:
            self._backend.reset()
        obs = self._obs_vector(mission)
        return obs, {"mission": mission, "goal": mission.goal}

    def _spawn_agents(self, goal: GoalPose) -> None:
        n_people = int(max(0, round(8 * self.density_ped)))
        n_obj = int(max(0, round(5 * self.density_obj)))
        self._people = []
        self._obstacles = []
        for _ in range(n_people):
            t = float(self._rng.uniform(0.15, 0.85))
            base = np.array([goal.x * t, goal.y * t, 0.0])
            jitter = self._rng.normal(0.0, 2.0, size=3)
            jitter[2] = 0.0
            self._people.append(base + jitter)
        for _ in range(n_obj):
            span = max(abs(goal.x), abs(goal.y), 10.0)
            xy = self._rng.uniform(-5.0, span, size=2)
            self._obstacles.append(np.array([xy[0], xy[1], 0.0]))

    def _nearest(self, points: list[np.ndarray]) -> float | None:
        if not points:
            return None
        dists = [float(np.linalg.norm(p[:2] - self._pos[:2])) for p in points]
        return min(dists)

    def _as_nav_obs(self) -> NavObservation:
        return NavObservation(
            position=(float(self._pos[0]), float(self._pos[1]), float(self._pos[2])),
            heading_deg=float(self._heading),
            nearest_person_m=self._nearest(self._people),
            nearest_obstacle_m=self._nearest(self._obstacles),
        )

    def _obs_vector(self, mission: Mission) -> np.ndarray:
        dx = mission.goal.x - self._pos[0]
        dy = mission.goal.y - self._pos[1]
        person = self._nearest(self._people)
        obstacle = self._nearest(self._obstacles)
        return np.array(
            [
                self._pos[0],
                self._pos[1],
                self._heading,
                dx,
                dy,
                math.hypot(dx, dy),
                person if person is not None else 99.0,
                obstacle if obstacle is not None else 99.0,
            ],
            dtype=np.float64,
        )

    def _move_people(self) -> None:
        for i, p in enumerate(self._people):
            drift = self._rng.normal(0.0, 0.15, size=2)
            self._people[i] = p + np.array([drift[0], drift[1], 0.0])

    def step(self, action):
        self._step_count += 1
        action = np.asarray(action, dtype=np.float64).reshape(-1)
        nav_obs = self._as_nav_obs()
        if self.navigator.mission is not None and not self.navigator.done():
            cmd = self.navigator.step(nav_obs)
            vx, vy, vyaw = cmd.vx, cmd.vy, cmd.vyaw
            if cmd.stop:
                vx = vy = vyaw = 0.0
        else:
            vx = float(action[0]) if action.size else 0.0
            vy = float(action[1]) if action.size > 1 else 0.0
            vyaw = float(action[2]) if action.size > 2 else 0.0

        if action.size >= 3 and self.navigator.mission is not None:
            vx += 0.1 * float(action[0])
            vyaw += 0.1 * float(action[2])

        dt = 0.1
        rad = math.radians(self._heading)
        self._pos[0] += (vx * math.cos(rad) - vy * math.sin(rad)) * dt
        self._pos[1] += (vx * math.sin(rad) + vy * math.cos(rad)) * dt
        self._heading = (self._heading + math.degrees(vyaw) * dt) % 360.0
        self._move_people()

        mission = self.navigator.mission
        assert mission is not None
        dist = math.hypot(mission.goal.x - self._pos[0], mission.goal.y - self._pos[1])
        person = self._nearest(self._people)
        obstacle = self._nearest(self._obstacles)
        collided = (person is not None and person < 0.4) or (obstacle is not None and obstacle < 0.35)
        arrived = dist <= self.navigator.arrive_radius_m
        if arrived:
            mission.status = "arrived"

        progress = max(0.0, 1.0 - dist / max(1.0, math.hypot(mission.goal.x, mission.goal.y)))
        reward, rinfo = social_nav_reward(
            progress=progress,
            dist_to_goal=dist,
            nearest_person_m=person,
            nearest_obstacle_m=obstacle,
            collided=collided,
            arrived=arrived,
        )
        obs = self._obs_vector(mission)
        terminated = arrived or collided
        truncated = self._step_count >= self.max_episode_steps
        info = {
            "dist_to_goal": dist,
            "collided": collided,
            "arrived": arrived,
            "model_id": self.navigator.model_id,
            **rinfo,
        }
        return obs, reward, terminated, truncated, info

    def close(self) -> None:
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        self.navigator.close()
