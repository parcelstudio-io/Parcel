from __future__ import annotations

from dataclasses import dataclass

import mujoco
import numpy as np

from .models import Pose


@dataclass
class ActuatorBinding:
    actuator_id: int
    joint_name: str
    qpos_adr: int
    qvel_adr: int


def bind_actuators(model: mujoco.MjModel) -> list[ActuatorBinding]:
    bindings: list[ActuatorBinding] = []
    for actuator_id in range(model.nu):
        joint_id = int(model.actuator_trnid[actuator_id, 0])
        joint_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint_id)
        if joint_name is None:
            raise ValueError(f"actuator {actuator_id} is not attached to a named joint")
        bindings.append(
            ActuatorBinding(
                actuator_id=actuator_id,
                joint_name=joint_name,
                qpos_adr=int(model.jnt_qposadr[joint_id]),
                qvel_adr=int(model.jnt_dofadr[joint_id]),
            )
        )
    return bindings


class PoseController:
    """Interpolate and hold joint targets for pose preview in MuJoCo.

    Joint angles are written kinematically so ``robot.yaml`` poses are visible
    even without a full Unitree low-level controller. Optional PD torques keep
    the actuators consistent with the held posture.
    """

    def __init__(
        self,
        model: mujoco.MjModel,
        *,
        kp: float = 60.0,
        kd: float = 2.0,
    ):
        self.model = model
        self.bindings = bind_actuators(model)
        self.kp = float(kp)
        self.kd = float(kd)
        self._targets = np.zeros(model.nu, dtype=np.float64)
        self._start = np.zeros(model.nu, dtype=np.float64)
        self._goal = np.zeros(model.nu, dtype=np.float64)
        self._elapsed = 0.0
        self._duration = 0.0
        self._active = False
        self._hold = False

    def sync_from_state(self, data: mujoco.MjData) -> None:
        for binding in self.bindings:
            self._targets[binding.actuator_id] = data.qpos[binding.qpos_adr]
        self._start[:] = self._targets
        self._goal[:] = self._targets

    def apply_pose(self, pose: Pose, data: mujoco.MjData) -> None:
        self.sync_from_state(data)
        goal = self._targets.copy()
        missing = []
        for joint_name, value in pose.joints.items():
            matched = False
            for binding in self.bindings:
                if binding.joint_name == joint_name:
                    goal[binding.actuator_id] = float(value)
                    matched = True
                    break
            if not matched:
                missing.append(joint_name)
        if missing:
            raise KeyError(f"unknown joints for this model: {', '.join(missing)}")
        self._start[:] = self._targets
        self._goal[:] = goal
        self._elapsed = 0.0
        self._duration = max(float(pose.duration), 1e-3)
        self._active = True
        self._hold = True

    def stop(self, data: mujoco.MjData) -> None:
        self.sync_from_state(data)
        self._active = False
        self._hold = True

    def step(self, data: mujoco.MjData, dt: float) -> None:
        if self._active:
            self._elapsed += float(dt)
            alpha = min(1.0, self._elapsed / self._duration)
            blend = alpha * alpha * (3.0 - 2.0 * alpha)
            self._targets[:] = (1.0 - blend) * self._start + blend * self._goal
            if alpha >= 1.0:
                self._active = False

        if not self._hold and not self._active:
            data.ctrl[:] = 0.0
            return

        for binding in self.bindings:
            target = self._targets[binding.actuator_id]
            data.qpos[binding.qpos_adr] = target
            data.qvel[binding.qvel_adr] = 0.0
            lo, hi = self.model.actuator_ctrlrange[binding.actuator_id]
            # Hold near zero torque; joint angles are set kinematically above.
            data.ctrl[binding.actuator_id] = float(np.clip(0.0, lo, hi))
