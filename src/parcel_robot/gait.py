from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import VelocityCommand

_STAND = {
    "FL_hip_joint": 0.0,
    "FL_thigh_joint": 0.9,
    "FL_calf_joint": -1.8,
    "FR_hip_joint": 0.0,
    "FR_thigh_joint": 0.9,
    "FR_calf_joint": -1.8,
    "RL_hip_joint": 0.0,
    "RL_thigh_joint": 0.9,
    "RL_calf_joint": -1.8,
    "RR_hip_joint": 0.0,
    "RR_thigh_joint": 0.9,
    "RR_calf_joint": -1.8,
}

_PAIR_A = ("FL", "RR")
_PAIR_B = ("FR", "RL")

_STYLE = {
    "trot": {"frequency_hz": 1.6, "step_amplitude": 0.35, "lift_amplitude": 0.45},
    "run": {"frequency_hz": 2.4, "step_amplitude": 0.45, "lift_amplitude": 0.55},
    "crawl": {"frequency_hz": 1.0, "step_amplitude": 0.18, "lift_amplitude": 0.2},
}


@dataclass
class ScriptedTrotGait:
    """Open-loop kinematic gait preview (trot / run / crawl)."""

    frequency_hz: float = 1.6
    step_amplitude: float = 0.35
    lift_amplitude: float = 0.45
    phase: float = 0.0
    style: str = "trot"
    _stand: dict[str, float] = field(default_factory=lambda: dict(_STAND))

    def set_style(self, style: str, frequency_hz: float | None = None) -> None:
        params = _STYLE.get(style, _STYLE["trot"])
        self.style = style if style in _STYLE else "trot"
        self.frequency_hz = float(frequency_hz if frequency_hz is not None else params["frequency_hz"])
        self.step_amplitude = float(params["step_amplitude"])
        self.lift_amplitude = float(params["lift_amplitude"])

    def reset(self) -> None:
        self.phase = 0.0

    def standing_joints(self) -> dict[str, float]:
        return dict(self._stand)

    def joints_for(self, command: VelocityCommand, dt: float) -> dict[str, float]:
        speed = abs(command.vx) + abs(command.vy) + 0.35 * abs(command.vyaw)
        if speed < 1e-3:
            return self.standing_joints()

        direction = 1.0 if command.vx >= 0.0 else -1.0
        cadence = self.frequency_hz * (0.6 + min(speed, 0.8))
        self.phase = (self.phase + 2.0 * math.pi * cadence * float(dt) * direction) % (
            2.0 * math.pi
        )
        joints = self.standing_joints()
        self._apply_pair(joints, _PAIR_A, self.phase, command)
        self._apply_pair(joints, _PAIR_B, self.phase + math.pi, command)
        if self.style == "crawl":
            for leg in ("FL", "FR", "RL", "RR"):
                joints[f"{leg}_thigh_joint"] += 0.25
                joints[f"{leg}_calf_joint"] -= 0.25
        return joints

    def _apply_pair(
        self,
        joints: dict[str, float],
        legs: tuple[str, str],
        phase: float,
        command: VelocityCommand,
    ) -> None:
        swing = math.sin(phase)
        step = self.step_amplitude * swing
        lift = max(0.0, swing) * self.lift_amplitude
        yaw_lean = 0.12 * command.vyaw
        side = 0.08 * command.vy
        for leg in legs:
            sign = 1.0 if leg.startswith("F") else -1.0
            joints[f"{leg}_hip_joint"] = side + (yaw_lean if leg.endswith("L") else -yaw_lean)
            joints[f"{leg}_thigh_joint"] = self._stand[f"{leg}_thigh_joint"] - sign * step + 0.55 * lift
            joints[f"{leg}_calf_joint"] = self._stand[f"{leg}_calf_joint"] + sign * 0.55 * step - 0.85 * lift


@dataclass
class TrajectoryPlayer:
    """Interpolate authored trajectory keyframes over simulation time."""

    elapsed: float = 0.0
    active: bool = False
    _frames: list[tuple[float, dict[str, float]]] = field(default_factory=list)

    def start(self, keyframes: list[dict]) -> None:
        frames = sorted(
            (
                (float(frame["t"]), {str(k): float(v) for k, v in dict(frame["joints"]).items()})
                for frame in keyframes
            ),
            key=lambda item: item[0],
        )
        if len(frames) < 2:
            raise ValueError("trajectory needs at least two keyframes")
        self._frames = frames
        self.elapsed = 0.0
        self.active = True

    def stop(self) -> None:
        self.active = False
        self._frames = []
        self.elapsed = 0.0

    def joints_for(self, dt: float) -> dict[str, float] | None:
        if not self.active or not self._frames:
            return None
        self.elapsed += float(dt)
        if self.elapsed >= self._frames[-1][0]:
            self.active = False
            return dict(self._frames[-1][1])
        for index in range(len(self._frames) - 1):
            t0, j0 = self._frames[index]
            t1, j1 = self._frames[index + 1]
            if t0 <= self.elapsed <= t1:
                alpha = 0.0 if t1 <= t0 else (self.elapsed - t0) / (t1 - t0)
                blend = alpha * alpha * (3.0 - 2.0 * alpha)
                keys = set(j0) | set(j1)
                return {
                    key: (1.0 - blend) * j0.get(key, j1.get(key, 0.0))
                    + blend * j1.get(key, j0.get(key, 0.0))
                    for key in keys
                }
        return dict(self._frames[0][1])
