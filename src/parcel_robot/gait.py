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

_STYLE = {
    "trot": {"frequency_hz": 1.6, "stride_m": 0.13, "clearance_m": 0.055, "duty": 0.58},
    "run": {"frequency_hz": 2.4, "stride_m": 0.17, "clearance_m": 0.075, "duty": 0.48},
    "crawl": {"frequency_hz": 1.0, "stride_m": 0.075, "clearance_m": 0.035, "duty": 0.72},
}

_TROT_PHASE = {"FL": 0.0, "RR": 0.0, "FR": 0.5, "RL": 0.5}
_CRAWL_PHASE = {"FL": 0.0, "RR": 0.25, "FR": 0.5, "RL": 0.75}


@dataclass
class ScriptedTrotGait:
    """Open-loop kinematic gait preview (trot / run / crawl)."""

    frequency_hz: float = 1.6
    stride_m: float = 0.13
    clearance_m: float = 0.055
    duty_factor: float = 0.58
    phase: float = 0.0
    style: str = "trot"
    _stand: dict[str, float] = field(default_factory=lambda: dict(_STAND))
    _target_frequency_hz: float = 1.6
    _target_stride_m: float = 0.13
    _target_clearance_m: float = 0.055
    _target_duty_factor: float = 0.58
    _motion_scale: float = 0.0

    def set_style(self, style: str, frequency_hz: float | None = None) -> None:
        if style not in _STYLE:
            raise ValueError(f"unsupported gait style: {style!r}")
        params = _STYLE[style]
        frequency = float(frequency_hz if frequency_hz is not None else params["frequency_hz"])
        if not math.isfinite(frequency) or not 0.2 <= frequency <= 5.0:
            raise ValueError("gait frequency must be finite and between 0.2 and 5 Hz")
        self.style = style
        self._target_frequency_hz = frequency
        self._target_stride_m = float(params["stride_m"])
        self._target_clearance_m = float(params["clearance_m"])
        self._target_duty_factor = float(params["duty"])

    def reset(self) -> None:
        self.phase = 0.0
        self._motion_scale = 0.0

    def standing_joints(self) -> dict[str, float]:
        return dict(self._stand)

    def joints_for(self, command: VelocityCommand, dt: float) -> dict[str, float]:
        dt = max(0.0, float(dt))
        speed = abs(command.vx) + abs(command.vy) + 0.35 * abs(command.vyaw)
        response = min(1.0, dt * 6.0)
        self.frequency_hz += (self._target_frequency_hz - self.frequency_hz) * response
        self.stride_m += (self._target_stride_m - self.stride_m) * response
        self.clearance_m += (self._target_clearance_m - self.clearance_m) * response
        self.duty_factor += (self._target_duty_factor - self.duty_factor) * response
        target_scale = min(1.0, speed / 0.35) if speed >= 1e-3 else 0.0
        self._motion_scale += (target_scale - self._motion_scale) * min(1.0, dt * 8.0)
        if self._motion_scale < 1e-3:
            return self.standing_joints()

        cadence = self.frequency_hz * (0.7 + min(speed, 0.7))
        self.phase = (self.phase + cadence * dt) % 1.0
        joints = self.standing_joints()
        phases = _CRAWL_PHASE if self.style == "crawl" else _TROT_PHASE
        for leg, offset in phases.items():
            self._apply_leg(joints, leg, (self.phase + offset) % 1.0, command)
        if self.style == "crawl":
            for leg in ("FL", "FR", "RL", "RR"):
                joints[f"{leg}_thigh_joint"] += 0.12
                joints[f"{leg}_calf_joint"] -= 0.20
        return joints

    def _apply_leg(
        self,
        joints: dict[str, float],
        leg: str,
        phase: float,
        command: VelocityCommand,
    ) -> None:
        stride = self.stride_m * self._motion_scale
        if command.vx < -1e-3:
            stride = -stride
        duty = max(0.35, min(0.8, self.duty_factor))
        if phase < duty:
            # Stance foot travels backward relative to the body at constant
            # velocity, approximating a world-fixed planted paw.
            progress = phase / duty
            foot_x = stride * (0.5 - progress)
            lift = 0.0
        else:
            progress = (phase - duty) / (1.0 - duty)
            blend = progress * progress * (3.0 - 2.0 * progress)
            foot_x = stride * (-0.5 + blend)
            lift = self.clearance_m * math.sin(math.pi * progress) * self._motion_scale
        thigh, calf = self._leg_ik(foot_x, -0.265 + lift)
        turn_sign = 1.0 if leg.endswith("L") else -1.0
        lateral_sign = 1.0 if leg.endswith("L") else -1.0
        joints[f"{leg}_hip_joint"] = (
            lateral_sign * 0.10 * command.vy + turn_sign * 0.08 * command.vyaw
        )
        joints[f"{leg}_thigh_joint"] = thigh
        joints[f"{leg}_calf_joint"] = calf

    @staticmethod
    def _leg_ik(x: float, z: float) -> tuple[float, float]:
        upper = lower = 0.213
        radius_sq = max(0.06**2, min((upper + lower - 1e-4) ** 2, x * x + z * z))
        cosine = max(
            -1.0, min(1.0, (radius_sq - upper * upper - lower * lower) / (2 * upper * lower))
        )
        calf = -math.acos(cosine)
        thigh = math.atan2(x, -z) - math.atan2(
            lower * math.sin(calf), upper + lower * math.cos(calf)
        )
        return thigh, calf


@dataclass
class TrajectoryPlayer:
    """Interpolate authored trajectory keyframes over simulation time."""

    elapsed: float = 0.0
    active: bool = False
    _frames: list[tuple[float, dict[str, float]]] = field(default_factory=list)

    def start(self, keyframes: list[dict]) -> None:
        if not 2 <= len(keyframes) <= 500:
            raise ValueError("trajectory needs between two and 500 keyframes")
        frames: list[tuple[float, dict[str, float]]] = []
        previous = -1.0
        for frame in keyframes:
            timestamp = float(frame["t"])
            joints = {str(k): float(v) for k, v in dict(frame["joints"]).items()}
            if not math.isfinite(timestamp) or not 0.0 <= timestamp <= 30.0:
                raise ValueError("trajectory timestamp is outside the safe range")
            if timestamp <= previous:
                raise ValueError("trajectory timestamps must be strictly increasing")
            if not joints or any(
                not math.isfinite(value) or abs(value) > 3.2 for value in joints.values()
            ):
                raise ValueError("trajectory contains unsafe joint values")
            frames.append((timestamp, joints))
            previous = timestamp
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
