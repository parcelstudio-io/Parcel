"""Morphology profile: the single home for robot-specific body constants.

Everything the animation/gait layer needs to know about a quadruped's body —
joint naming, link lengths, stance, footprint — lives here instead of being
scattered as literals. Porting to a new robot means writing one profile (plus
re-authoring pose YAMLs against its joint names), not editing kinematics code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from parcel_robot.geometry import ROBOT_FOOTPRINT_RADIUS_M


@dataclass(frozen=True)
class RobotProfile:
    """Vendor-neutral quadruped morphology description."""

    name: str = "go2"
    leg_prefixes: tuple[str, ...] = ("FL", "FR", "RL", "RR")
    joint_suffixes: tuple[str, ...] = ("hip_joint", "thigh_joint", "calf_joint")
    stand_joint_angles_rad: tuple[float, ...] = (0.0, 0.9, -1.8)
    upper_link_m: float = 0.213
    lower_link_m: float = 0.213
    stance_z_m: float = -0.265
    footprint_radius_m: float = ROBOT_FOOTPRINT_RADIUS_M
    max_vy_mps: float = 0.4
    scan_height_m: float = 0.45

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("robot profile name cannot be empty")
        if not 2 <= len(self.leg_prefixes) <= 8:
            raise ValueError("robot profile requires between two and eight legs")
        if len(set(self.leg_prefixes)) != len(self.leg_prefixes):
            raise ValueError("robot profile leg prefixes must be unique")
        if not 2 <= len(self.joint_suffixes) <= 6:
            raise ValueError("robot profile requires between two and six joints per leg")
        if len(self.stand_joint_angles_rad) != len(self.joint_suffixes):
            raise ValueError("stand angles must match the joints-per-leg count")
        lengths = (self.upper_link_m, self.lower_link_m)
        if any(not math.isfinite(v) or not 0.02 <= v <= 1.5 for v in lengths):
            raise ValueError("link lengths must be between 0.02 and 1.5 meters")
        if not math.isfinite(self.stance_z_m) or not -1.5 <= self.stance_z_m <= -0.02:
            raise ValueError("stance height must be negative (hip above foot)")
        if abs(self.stance_z_m) >= self.upper_link_m + self.lower_link_m:
            raise ValueError("stance height cannot exceed full leg extension")
        if not math.isfinite(self.footprint_radius_m) or not 0.05 <= self.footprint_radius_m <= 1.5:
            raise ValueError("footprint radius must be between 0.05 and 1.5 meters")
        if not math.isfinite(self.max_vy_mps) or self.max_vy_mps < 0.0:
            raise ValueError("max_vy must be finite and non-negative")
        if not math.isfinite(self.scan_height_m) or not 0.05 <= self.scan_height_m <= 2.0:
            raise ValueError("scan height must be between 0.05 and 2 meters")

    @property
    def dof(self) -> int:
        return len(self.leg_prefixes) * len(self.joint_suffixes)

    def joint_name(self, leg: str, joint_index: int) -> str:
        if leg not in self.leg_prefixes:
            raise KeyError(f"unknown leg prefix: {leg!r}")
        return f"{leg}_{self.joint_suffixes[joint_index]}"

    def stand_joints(self) -> dict[str, float]:
        return {
            self.joint_name(leg, index): angle
            for leg in self.leg_prefixes
            for index, angle in enumerate(self.stand_joint_angles_rad)
        }

    @classmethod
    def go2(cls) -> RobotProfile:
        return cls()

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> RobotProfile:
        """Build from the ``robot:`` config section; unknown keys fail closed."""

        config = dict(config or {})
        model = str(config.pop("model", "go2")).strip().lower()
        overrides = config.pop("profile", {}) or {}
        if config:
            raise ValueError(f"unsupported robot config keys: {sorted(config)}")
        if not isinstance(overrides, dict):
            raise TypeError("robot.profile must be a mapping")
        base = cls.go2() if model == "go2" else cls(name=model)
        allowed = {
            "upper_link_m",
            "lower_link_m",
            "stance_z_m",
            "footprint_radius_m",
            "max_vy_mps",
            "scan_height_m",
            "leg_prefixes",
            "joint_suffixes",
            "stand_joint_angles_rad",
        }
        unknown = set(overrides) - allowed
        if unknown:
            raise ValueError(f"unsupported robot.profile keys: {sorted(unknown)}")
        cleaned: dict[str, Any] = {}
        for key, value in overrides.items():
            if key in {"leg_prefixes", "joint_suffixes"}:
                cleaned[key] = tuple(str(item) for item in value)
            elif key == "stand_joint_angles_rad":
                cleaned[key] = tuple(float(item) for item in value)
            else:
                cleaned[key] = float(value)
        from dataclasses import replace

        return replace(base, **cleaned)
