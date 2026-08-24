"""RobotProfile: the single home for morphology constants."""

from __future__ import annotations

import math

import pytest

from parcel_robot.models import VelocityCommand
from parcel_robot.motion.gait import ScriptedTrotGait
from parcel_robot.robot_profile import RobotProfile


def test_go2_profile_matches_legacy_constants() -> None:
    profile = RobotProfile.go2()
    assert profile.dof == 12
    stand = profile.stand_joints()
    assert stand["FL_hip_joint"] == 0.0
    assert stand["RR_thigh_joint"] == pytest.approx(0.9)
    assert stand["RL_calf_joint"] == pytest.approx(-1.8)
    assert profile.upper_link_m == pytest.approx(0.213)
    assert profile.stance_z_m == pytest.approx(-0.265)


def test_profile_validation_fails_closed() -> None:
    with pytest.raises(ValueError, match="full leg extension"):
        RobotProfile(stance_z_m=-0.9)
    with pytest.raises(ValueError, match="stand angles"):
        RobotProfile(stand_joint_angles_rad=(0.0, 0.9))
    with pytest.raises(ValueError, match="unique"):
        RobotProfile(leg_prefixes=("FL", "FL", "RL", "RR"))


def test_from_config_applies_bounded_overrides() -> None:
    profile = RobotProfile.from_config(
        {
            "model": "lite3",
            "profile": {"upper_link_m": 0.25, "lower_link_m": 0.25, "stance_z_m": -0.30},
        }
    )
    assert profile.name == "lite3"
    assert profile.upper_link_m == pytest.approx(0.25)
    with pytest.raises(ValueError, match="unsupported robot.profile keys"):
        RobotProfile.from_config({"profile": {"nonsense": 1}})
    with pytest.raises(ValueError, match="unsupported robot config keys"):
        RobotProfile.from_config({"model": "go2", "extra": True})


def test_gait_uses_profile_geometry_not_literals() -> None:
    go2 = ScriptedTrotGait()
    long_leg = ScriptedTrotGait(
        profile=RobotProfile(
            name="longshank",
            upper_link_m=0.30,
            lower_link_m=0.30,
            stance_z_m=-0.40,
        )
    )
    command = VelocityCommand(vx=0.4)
    for gait in (go2, long_leg):
        for _ in range(20):
            gait.joints_for(command, 0.02)  # warm the motion-scale filter
    go2_joints = go2.joints_for(command, 0.02)
    long_joints = long_leg.joints_for(command, 0.02)
    # Different morphology must produce different kinematics for the same
    # command; identical output would mean literals are still baked in.
    assert go2_joints.keys() == long_joints.keys()
    assert any(
        abs(go2_joints[name] - long_joints[name]) > 1e-3
        for name in go2_joints
        if name.endswith(("thigh_joint", "calf_joint"))
    )
    assert all(math.isfinite(value) for value in long_joints.values())


def test_gait_respects_custom_joint_naming() -> None:
    custom = ScriptedTrotGait(
        profile=RobotProfile(
            name="custom",
            joint_suffixes=("abduct", "hip", "knee"),
            stand_joint_angles_rad=(0.0, 0.8, -1.6),
        )
    )
    joints = custom.standing_joints()
    assert "FL_abduct" in joints
    assert "RR_knee" in joints
    moving = custom.joints_for(VelocityCommand(vx=0.3), 0.05)
    assert "FL_knee" in moving
