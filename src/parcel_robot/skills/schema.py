from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SkillKind = Literal["pose", "trajectory", "gait", "velocity", "policy"]


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
