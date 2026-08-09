"""Morphology profile: the single home for robot-specific body constants.

Everything the animation/gait layer needs to know about a quadruped's body —
joint naming, link lengths, stance, footprint — lives here instead of being
scattered as literals. Porting to a new robot means writing one profile (plus
re-authoring pose YAMLs against its joint names), not editing kinematics code.

This module sits at the bottom of the import graph on purpose: it must not
import anything from :mod:`parcel_robot` so that
:mod:`parcel_robot.core.authority` (which builds the SpeedRegime / SafetyEnvelope
authorities on top of it) can be imported from anywhere, including
:mod:`parcel_robot.geometry`'s deprecation shim.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


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
    #: Body-inscribing planar radius. Provenance: this literal was
    #: ``geometry.ROBOT_FOOTPRINT_RADIUS_M`` until 2026-08-07, when the
    #: embodiment authority moved here and ``geometry`` became a deprecation
    #: shim. Value unchanged (Go2 body 0.70 x 0.31 m plus stance spread).
    footprint_radius_m: float = 0.32
    max_vy_mps: float = 0.4
    scan_height_m: float = 0.45
    #: Height below which world geometry blocks this body. Provenance: this
    #: literal was ``geometry.ROBOT_OBSTACLE_HEIGHT_M`` until 2026-08-07;
    #: value unchanged. Scales with the standing body (embodiment bucket).
    obstacle_clearance_height_m: float = 0.9
    #: Comfortable maximum deceleration used by every stopping-distance
    #: envelope. Provenance (derived, 2026-08-07): ``configs/robot.yaml``
    #: ``motion.smoothing.linear_decel = 1.4`` — the jerk-limited shaper's
    #: braking authority, which is the largest deceleration the actuator
    #: hand-off will actually produce. Not measured on hardware.
    decel_max_mps2: float = 1.4
    #: Sense-to-actuate latency used as ``tau`` in every ISO/TS-15066 style
    #: envelope. Provenance (derived, 2026-08-07): the two live reaction
    #: horizons in the stack agree at 0.12 s —
    #: ``navigation/collision.py CollisionPolicy.reaction_time_s`` and
    #: ``navigation/reactive_safety.py ReactiveSafetyPolicy.reaction_time_s``.
    #: One 10 Hz control tick (0.1 s) plus 0.02 s of command hand-off.
    reaction_latency_s: float = 0.12

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
        if (
            not math.isfinite(self.obstacle_clearance_height_m)
            or not 0.05 <= self.obstacle_clearance_height_m <= 5.0
        ):
            raise ValueError("obstacle clearance height must be between 0.05 and 5 meters")
        if not math.isfinite(self.decel_max_mps2) or not 0.05 <= self.decel_max_mps2 <= 20.0:
            raise ValueError("decel_max must be between 0.05 and 20 m/s^2")
        if not math.isfinite(self.reaction_latency_s) or not 0.0 <= self.reaction_latency_s <= 2.0:
            raise ValueError("reaction latency must be between 0 and 2 seconds")

    @property
    def dof(self) -> int:
        return len(self.leg_prefixes) * len(self.joint_suffixes)

    @property
    def leg_length_m(self) -> float:
        """Kinematic leg length — the characteristic length ``L`` for Froude.

        Sum of the existing link lengths (full extension), not the standing hip
        height ``abs(stance_z_m)``. Both conventions appear in the legged
        locomotion literature; this one is used consistently by
        :mod:`parcel_robot.core.authority` so a Froude number computed here is
        comparable across profiles. Go2: 0.213 + 0.213 = 0.426 m.
        """

        return self.upper_link_m + self.lower_link_m

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
            "obstacle_clearance_height_m",
            "decel_max_mps2",
            "reaction_latency_s",
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


#: The module-level default profile. Call sites that have no injection seam yet
#: resolve against this instead of binding a literal as a Python default
#: argument (a default argument is evaluated once at import and can never be
#: reached by an injected profile). Every such site is listed in
#: ``scrum/20260806/task_3/LANE_A_STATUS.md`` for the archon rule.
DEFAULT_ROBOT_PROFILE: RobotProfile = RobotProfile.go2()
