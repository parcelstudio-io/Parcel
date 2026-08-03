from __future__ import annotations

import math
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from parcel_robot.skills.api import Dog

from .rewards import compute_reward
from .spaces import OBS_DIM, action_space_spec, observation_space_spec

REPO_ROOT = Path(__file__).resolve().parents[3]


class Go2Env:
    """Gymnasium-like Go2 environment stub for skill / locomotion RL.

    This does not require a display. When MuJoCo and a scene are available it can
    optionally step physics; otherwise it provides API-compatible offline ticks
    for wiring training loops.
    """

    metadata: ClassVar[dict[str, Any]] = {
        "render_modes": ["human", "none"],
        "name": "ParcelGo2-v0",
    }

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        skill_id: str = "stand",
        scene: str | Path | None = None,
        use_mujoco: bool = False,
        max_episode_steps: int = 500,
        action_kp: float = 20.0,
        action_kd: float = 0.5,
    ):
        if not math.isfinite(action_kp) or not math.isfinite(action_kd):
            raise ValueError("action PD gains must be finite")
        if action_kp <= 0.0 or action_kd < 0.0:
            raise ValueError("action PD gains require kp > 0 and kd >= 0")
        self.dog = Dog.from_config(config_path)
        self.skill_id = skill_id
        self.max_episode_steps = max_episode_steps
        self.use_mujoco = use_mujoco
        self.action_kp = action_kp
        self.action_kd = action_kd
        self._step_count = 0
        self._progress = 0.0
        self._model = None
        self._data = None
        self.observation_space = observation_space_spec()
        self.action_space = action_space_spec()
        if use_mujoco:
            self._init_mujoco(scene)

    def _init_mujoco(self, scene: str | Path | None) -> None:
        import mujoco

        if scene is None:
            scene = (
                Path(__file__).resolve().parents[1] / "scenes" / "city_block.xml"
            )
        scene_path = Path(scene)
        if not scene_path.is_file():
            raise FileNotFoundError(scene_path)
        self._model = mujoco.MjModel.from_xml_path(str(scene_path))
        self._data = mujoco.MjData(self._model)
        if self._model.nkey > 0:
            mujoco.mj_resetDataKeyframe(self._model, self._data, 0)
        mujoco.mj_forward(self._model, self._data)

        def provider() -> np.ndarray:
            return self._mujoco_obs()

        self.dog.set_obs_provider(provider)

    def _mujoco_obs(self) -> np.ndarray:
        assert self._model is not None and self._data is not None
        obs = np.zeros(OBS_DIM, dtype=np.float64)
        # Free joint quat starts at qpos[3:7] for Go2.
        if self._model.nq >= 7:
            obs[0:4] = self._data.qpos[3:7]
            obs[4:7] = self._data.qvel[3:6]
        # Approximate joint block from qpos[7:19]
        njoint = min(12, max(0, self._model.nq - 7))
        if njoint:
            obs[7 : 7 + njoint] = self._data.qpos[7 : 7 + njoint]
            obs[19 : 19 + njoint] = self._data.qvel[6 : 6 + njoint]
        obs[31:43] = self.dog._last_action
        obs[43] = self.dog._velocity_cmd.vx
        obs[44] = self.dog._velocity_cmd.vy
        obs[45] = self.dog._velocity_cmd.vyaw
        try:
            obs[46] = float(self.dog.catalog.ids().index(self.skill_id))
        except ValueError:
            obs[46] = 0.0
        obs[47] = self._progress
        return obs

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        if seed is not None:
            np.random.seed(seed)
        self._step_count = 0
        self._progress = 0.0
        options = options or {}
        self.skill_id = str(options.get("skill_id", self.skill_id))
        self.dog.execute(self.skill_id)
        if self._model is not None and self._data is not None:
            import mujoco

            if self._model.nkey > 0:
                mujoco.mj_resetDataKeyframe(self._model, self._data, 0)
            mujoco.mj_forward(self._model, self._data)
        obs = self.dog.obs()
        info = {"skill_id": self.skill_id}
        return obs, info

    def step(self, action):
        self._step_count += 1
        self._progress = min(1.0, self._step_count / max(1, self.max_episode_steps))
        targets = np.asarray(action, dtype=np.float64).reshape(-1)[:12]
        if targets.size and not np.all(np.isfinite(targets)):
            raise ValueError("RL action contains non-finite joint targets")
        targets = np.clip(targets, -3.14, 3.14)
        obs = self.dog.step_policy(targets)
        if self._model is not None and self._data is not None:
            import mujoco

            padded_targets = self.dog._last_action
            count = min(self._model.nu, padded_targets.size)
            for actuator_id in range(count):
                joint_id = int(self._model.actuator_trnid[actuator_id, 0])
                if joint_id < 0:
                    continue
                qpos_adr = int(self._model.jnt_qposadr[joint_id])
                dof_adr = int(self._model.jnt_dofadr[joint_id])
                torque = self.action_kp * (
                    padded_targets[actuator_id] - self._data.qpos[qpos_adr]
                ) - self.action_kd * self._data.qvel[dof_adr]
                if self._model.actuator_ctrllimited[actuator_id]:
                    low, high = self._model.actuator_ctrlrange[actuator_id]
                    torque = float(np.clip(torque, low, high))
                self._data.ctrl[actuator_id] = torque
            mujoco.mj_step(self._model, self._data)
            obs = self._mujoco_obs()
        skill = self.dog.catalog.get(self.skill_id)
        info: dict[str, Any] = {
            "skill_id": self.skill_id,
            "base_height": float(obs[2]) if obs.shape[0] > 2 else 0.0,
            "target_vx": self.dog._velocity_cmd.vx,
            "actual_vx": 0.0,
            "upright": True,
            "pose_error": 0.0,
            "kick_reach": 0.0,
            "gesture_score": 0.0,
        }
        reward = compute_reward(skill.rl.reward, info)
        terminated = False
        truncated = self._step_count >= self.max_episode_steps
        return obs, reward, terminated, truncated, info

    def close(self) -> None:
        self._model = None
        self._data = None
