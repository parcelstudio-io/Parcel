"""Card A1: expressive liveness — gating, clamps, reaction timing, overlay."""

from __future__ import annotations

import math
import random

import pytest

from parcel_robot.expression import (
    MAX_BODY_HEIGHT_M,
    MAX_BODY_PITCH_RAD,
    MAX_HEAD_PITCH_RAD,
    MAX_HEAD_YAW_RAD,
    MODE_FULL,
    MODE_HEAD_ONLY,
    MODE_OFF,
    ExpressionEngine,
    ExpressionGate,
    ExpressiveOffsets,
    IdleLayer,
    ReactionHooks,
    stance_joint_offsets,
)
from parcel_robot.robot_profile import RobotProfile


def _engine(**kwargs) -> ExpressionEngine:
    return ExpressionEngine(
        RobotProfile.go2(),
        idle=IdleLayer(rng=random.Random(7)),
        reactions=ReactionHooks(),
        **kwargs,
    )


# --- gating -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("gate", "expected"),
    [
        (ExpressionGate(), MODE_FULL),
        (ExpressionGate(emergency_stopped=True), MODE_OFF),
        (ExpressionGate(battery_critical=True), MODE_OFF),
        (ExpressionGate(skill_active=True), MODE_OFF),
        (ExpressionGate(proximity_clear=False), MODE_OFF),
        (ExpressionGate(navigation_active=True), MODE_HEAD_ONLY),
        (ExpressionGate(follow_active=True), MODE_HEAD_ONLY),
        (ExpressionGate(spatial_active=True), MODE_HEAD_ONLY),
        # A hard gate always beats a soft one.
        (ExpressionGate(navigation_active=True, emergency_stopped=True), MODE_OFF),
    ],
)
def test_gate_mode_matrix(gate: ExpressionGate, expected: str) -> None:
    assert gate.mode == expected


def test_gated_off_produces_no_motion_at_all() -> None:
    engine = _engine()
    for tick in range(30):
        offsets = engine.step(tick * 0.1, ExpressionGate(emergency_stopped=True))
        assert offsets.is_zero
        assert engine.joint_offsets() == {}


def test_head_only_mode_keeps_gaze_but_never_moves_the_body() -> None:
    engine = _engine()
    engine.reactions.on_speech_start(0.0, 0.4)
    offsets = engine.step(0.5, ExpressionGate(navigation_active=True))
    assert offsets.head_yaw_rad == pytest.approx(0.4, abs=1e-6)
    assert offsets.body_height_m == 0.0
    assert offsets.body_pitch_rad == 0.0
    # No body channel means no actuated overlay while walking.
    assert engine.joint_offsets() == {}


def test_disabled_engine_is_inert() -> None:
    engine = _engine(enabled=False)
    assert engine.step(1.0, ExpressionGate()).is_zero
    assert engine.snapshot()["producer"] == "disabled"


def test_breathing_phase_continues_while_gated_off() -> None:
    """Expression must resume mid-breath, not snap back to the start."""

    engine = _engine()
    for tick in range(20):
        engine.step(tick * 0.1, ExpressionGate(skill_active=True))
    resumed = engine.step(2.0, ExpressionGate())
    # 2.0 s at 0.25 Hz is a zero crossing; the phase advanced through the gate
    # rather than restarting (a restart would also read ~0, so check the next
    # sample is on the descending side of the wave).
    following = engine.step(2.5, ExpressionGate())
    assert resumed.body_height_m == pytest.approx(0.0, abs=1e-9)
    assert following.body_height_m < 0.0


# --- clamps -----------------------------------------------------------------


def test_clamped_bounds_every_channel() -> None:
    wild = ExpressiveOffsets(
        body_height_m=10.0,
        body_pitch_rad=10.0,
        head_yaw_rad=-10.0,
        head_pitch_rad=10.0,
    ).clamped()
    assert wild.body_height_m == MAX_BODY_HEIGHT_M
    assert wild.body_pitch_rad == MAX_BODY_PITCH_RAD
    assert wild.head_yaw_rad == -MAX_HEAD_YAW_RAD
    assert wild.head_pitch_rad == MAX_HEAD_PITCH_RAD


def test_clamped_scrubs_non_finite_values() -> None:
    scrubbed = ExpressiveOffsets(
        body_height_m=float("nan"), head_yaw_rad=float("inf")
    ).clamped()
    assert scrubbed.is_zero


def test_engine_output_is_always_within_clamps() -> None:
    engine = _engine()
    engine.reactions.on_speech_start(0.0, 99.0)  # absurd bearing
    engine.reactions.on_turn_pending(0.0)
    for tick in range(200):
        offsets = engine.step(tick * 0.05, ExpressionGate())
        assert abs(offsets.body_height_m) <= MAX_BODY_HEIGHT_M + 1e-12
        assert abs(offsets.body_pitch_rad) <= MAX_BODY_PITCH_RAD + 1e-12
        assert abs(offsets.head_yaw_rad) <= MAX_HEAD_YAW_RAD + 1e-12
        assert abs(offsets.head_pitch_rad) <= MAX_HEAD_PITCH_RAD + 1e-12


# --- reaction timing --------------------------------------------------------


def test_speech_onset_orients_within_300ms() -> None:
    hooks = ReactionHooks()
    hooks.on_speech_start(0.0, 0.5)
    assert hooks.step(0.0).head_yaw_rad == pytest.approx(0.0, abs=1e-9)
    midway = hooks.step(0.15).head_yaw_rad
    assert 0.0 < midway < 0.5  # eased, not snapped
    assert hooks.step(0.30).head_yaw_rad == pytest.approx(0.5, abs=1e-6)
    assert hooks.orients_triggered == 1


def test_orientation_releases_smoothly_after_speech_ends() -> None:
    hooks = ReactionHooks()
    hooks.on_speech_start(0.0, 0.5)
    hooks.step(0.3)
    hooks.on_speech_end(0.3)
    assert 0.0 < hooks.step(0.45).head_yaw_rad < 0.5
    assert hooks.step(0.7).head_yaw_rad == pytest.approx(0.0, abs=1e-9)


def test_thinking_pose_holds_until_the_reply_starts() -> None:
    hooks = ReactionHooks()
    hooks.on_turn_pending(0.0)
    held = hooks.step(1.5)  # an arbitrarily long reasoning gap
    assert held.head_pitch_rad == pytest.approx(math.radians(8.0), abs=1e-6)
    assert held.body_height_m < 0.0
    assert hooks.active
    hooks.on_reply_started(1.5)
    assert hooks.step(1.9).head_pitch_rad == pytest.approx(0.0, abs=1e-9)
    assert not hooks.active
    assert hooks.thinking_holds == 1


def test_repeated_turn_pending_does_not_stack() -> None:
    hooks = ReactionHooks()
    hooks.on_turn_pending(0.0)
    hooks.on_turn_pending(0.1)
    hooks.on_turn_pending(0.2)
    assert hooks.thinking_holds == 1
    assert hooks.step(1.0).head_pitch_rad == pytest.approx(math.radians(8.0), abs=1e-6)


def test_bearing_is_clamped_and_non_finite_bearing_is_safe() -> None:
    hooks = ReactionHooks()
    hooks.on_speech_start(0.0, float("nan"))
    assert hooks.step(0.5).head_yaw_rad == pytest.approx(0.0, abs=1e-9)
    hooks.on_speech_start(1.0, 3.0)
    assert hooks.step(1.5).head_yaw_rad == pytest.approx(MAX_HEAD_YAW_RAD, abs=1e-6)


def test_idle_yields_the_head_while_a_reaction_owns_it() -> None:
    """Idle look-arounds must not fight an active orient."""

    idle = IdleLayer(rng=random.Random(3), gesture_interval_s=(0.5, 0.5))
    for tick in range(30):
        idle.step(tick * 0.1, suppress_head=True)
    assert idle.gestures_played > 0
    suppressed = idle.step(3.1, suppress_head=True)
    assert suppressed.head_yaw_rad == 0.0


# --- determinism ------------------------------------------------------------


def test_same_seed_animates_identically() -> None:
    def trace() -> list[tuple[float, float]]:
        engine = _engine()
        return [
            (
                engine.step(tick * 0.1, ExpressionGate()).body_height_m,
                engine.offsets.head_yaw_rad,
            )
            for tick in range(120)
        ]

    assert trace() == trace()


def test_idle_eventually_plays_gestures() -> None:
    idle = IdleLayer(rng=random.Random(11), gesture_interval_s=(1.0, 2.0))
    saw_pitch = False
    for tick in range(400):
        if abs(idle.step(tick * 0.05).body_pitch_rad) > 1e-6:
            saw_pitch = True
    assert idle.gestures_played >= 2
    assert saw_pitch  # weight shifts actually reach the body channel


# --- joint mapping ----------------------------------------------------------


def test_height_offset_maps_symmetrically_to_every_leg() -> None:
    profile = RobotProfile.go2()
    offsets = stance_joint_offsets(profile, ExpressiveOffsets(body_height_m=0.004))
    thighs = {name: value for name, value in offsets.items() if "thigh" in name}
    assert len(thighs) == len(profile.leg_prefixes)
    assert len({round(value, 9) for value in thighs.values()}) == 1


def test_pitch_offset_opposes_front_and_rear_legs() -> None:
    offsets = stance_joint_offsets(
        RobotProfile.go2(), ExpressiveOffsets(body_pitch_rad=0.05)
    )
    assert offsets["FL_thigh_joint"] * offsets["RL_thigh_joint"] < 0.0


def test_zero_offsets_produce_no_joint_overlay() -> None:
    assert stance_joint_offsets(RobotProfile.go2(), ExpressiveOffsets()) == {}


def test_joint_mapping_follows_the_configured_morphology() -> None:
    """A different body must produce different joint numbers for one motion."""

    go2 = stance_joint_offsets(RobotProfile.go2(), ExpressiveOffsets(body_height_m=0.004))
    long_legged = stance_joint_offsets(
        RobotProfile(upper_link_m=0.30, lower_link_m=0.30, stance_z_m=-0.40),
        ExpressiveOffsets(body_height_m=0.004),
    )
    assert go2["FL_thigh_joint"] != long_legged["FL_thigh_joint"]


def test_joint_mapping_uses_custom_joint_names() -> None:
    profile = RobotProfile(
        leg_prefixes=("LF", "RF", "LH", "RH"),
        joint_suffixes=("hip", "thigh", "knee"),
        stand_joint_angles_rad=(0.0, 0.9, -1.8),
    )
    offsets = stance_joint_offsets(profile, ExpressiveOffsets(body_height_m=0.004))
    assert set(offsets) == {
        "LF_thigh", "RF_thigh", "LH_thigh", "RH_thigh",
        "LF_knee", "RF_knee", "LH_knee", "RH_knee",
    }


def test_snapshot_reports_mode_and_counters() -> None:
    engine = _engine()
    engine.reactions.on_speech_start(0.0, 0.2)
    engine.step(0.3, ExpressionGate())
    snapshot = engine.snapshot()
    assert snapshot["enabled"] is True
    assert snapshot["mode"] == MODE_FULL
    assert snapshot["producer"] == "reaction"
    assert snapshot["orients_triggered"] == 1
    assert set(snapshot["offsets"]) == {
        "body_height_m",
        "body_pitch_rad",
        "head_yaw_rad",
        "head_pitch_rad",
    }
