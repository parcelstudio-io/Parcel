from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

SkillKind = Literal["pose", "trajectory", "gait", "velocity", "policy"]

# A normalized speed is a style control rather than an unconstrained motor
# rate.  Keeping a non-zero playback floor makes speed=0 useful while ensuring
# every bounded motion still finishes.  Stop remains the way to halt motion.
MIN_PLAYBACK_RATE = 0.25
MAX_POSE_PLAYBACK_S = 10.0
MAX_TRAJECTORY_PLAYBACK_S = 30.0


def validate_playback_speed(value: object) -> float:
    """Return a finite normalized playback speed, rejecting bool/string coercion."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("speed must be a number between 0 and 1")
    speed = float(value)
    if not math.isfinite(speed) or not 0.0 <= speed <= 1.0:
        raise ValueError("speed must be finite and between 0 and 1")
    return speed


def playback_timing(
    authored_duration_s: float,
    speed: object,
    *,
    maximum_duration_s: float,
) -> tuple[float, float]:
    """Map normalized speed to a safe rate and effective duration.

    ``speed=1`` preserves authored timing. ``speed=0`` selects the slowest
    admitted playback.  The duration-derived floor keeps retimed commands
    inside the transport's bounded-duration contract.
    """

    duration = float(authored_duration_s)
    maximum = float(maximum_duration_s)
    if not math.isfinite(duration) or duration <= 0.0:
        raise ValueError("authored motion duration must be positive and finite")
    if not math.isfinite(maximum) or maximum <= 0.0:
        raise ValueError("maximum motion duration must be positive and finite")
    if duration > maximum:
        raise ValueError("authored motion duration exceeds the safe maximum")
    normalized = validate_playback_speed(speed)
    rate_floor = max(MIN_PLAYBACK_RATE, duration / maximum)
    rate = rate_floor + normalized * (1.0 - rate_floor)
    return rate, duration / rate


@dataclass(frozen=True)
class Keyframe:
    t: float
    joints: dict[str, float]


@dataclass(frozen=True)
class VelocityParams:
    vx: float = 0.0
    vy: float = 0.0
    vyaw: float = 0.0


@dataclass(frozen=True)
class GaitParams:
    style: str = "trot"
    frequency_hz: float = 1.6


@dataclass(frozen=True)
class RLMeta:
    enabled: bool = False
    policy_path: str = ""
    action_dim: int = 12
    obs_dim: int = 48
    reward: str = "default"
    control_dt: float = 0.02


@dataclass(frozen=True)
class SkillSpec:
    id: str
    name: str
    kind: SkillKind
    enabled: bool = True
    tags: tuple[str, ...] = ()
    duration: float = 1.0
    joints: dict[str, float] = field(default_factory=dict)
    keyframes: tuple[Keyframe, ...] = ()
    velocity: VelocityParams = field(default_factory=VelocityParams)
    gait: GaitParams = field(default_factory=GaitParams)
    rl: RLMeta = field(default_factory=RLMeta)
    source_path: str = ""
    speed: float = 1.0

    def as_pose_joints(self) -> dict[str, float]:
        if self.kind == "pose":
            return dict(self.joints)
        if self.kind == "trajectory" and self.keyframes:
            return dict(self.keyframes[-1].joints)
        return {}


def parse_skill(data: dict[str, Any], source_path: str = "") -> SkillSpec:
    kind = str(data["kind"])
    if kind not in {"pose", "trajectory", "gait", "velocity", "policy"}:
        raise ValueError(f"unsupported skill kind: {kind}")
    velocity_raw = data.get("velocity") or {}
    gait_raw = data.get("gait") or {}
    rl_raw = data.get("rl") or {}
    keyframes = tuple(
        Keyframe(
            t=float(frame["t"]),
            joints={str(k): float(v) for k, v in dict(frame.get("joints", {})).items()},
        )
        for frame in data.get("keyframes", []) or []
    )
    joints = {str(k): float(v) for k, v in dict(data.get("joints", {}) or {}).items()}
    if kind == "pose" and not joints:
        raise ValueError(f"pose skill {data.get('id')!r} requires joints")
    if kind == "trajectory" and len(keyframes) < 2:
        raise ValueError(f"trajectory skill {data.get('id')!r} needs >= 2 keyframes")
    return SkillSpec(
        id=str(data["id"]),
        name=str(data.get("name", data["id"])),
        kind=kind,  # type: ignore[arg-type]
        enabled=bool(data.get("enabled", True)),
        tags=tuple(str(tag) for tag in data.get("tags", []) or []),
        duration=float(data.get("duration", 1.0)),
        speed=validate_playback_speed(data.get("speed", 1.0)),
        joints=joints,
        keyframes=keyframes,
        velocity=VelocityParams(
            vx=float(velocity_raw.get("vx", 0.0)),
            vy=float(velocity_raw.get("vy", 0.0)),
            vyaw=float(velocity_raw.get("vyaw", 0.0)),
        ),
        gait=GaitParams(
            style=str(gait_raw.get("style", "trot")),
            frequency_hz=float(gait_raw.get("frequency_hz", 1.6)),
        ),
        rl=RLMeta(
            enabled=bool(rl_raw.get("enabled", False)),
            policy_path=str(rl_raw.get("policy_path", "")),
            action_dim=int(rl_raw.get("action_dim", 12)),
            obs_dim=int(rl_raw.get("obs_dim", 48)),
            reward=str(rl_raw.get("reward", "default")),
            control_dt=float(rl_raw.get("control_dt", 0.02)),
        ),
        source_path=source_path,
    )
