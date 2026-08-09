"""Safety and packaging contracts for Parcel's starter body-language palette."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from parcel_robot.gait import TrajectoryPlayer
from parcel_robot.prompting.loader import PromptLibrary
from parcel_robot.robot_profile import RobotProfile
from parcel_robot.runtime import RobotRuntime
from parcel_robot.skills.catalog import SkillCatalog

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "configs" / "skills"
PACKAGED_SKILLS = REPO / "src" / "parcel_robot" / "runtime_assets" / "configs" / "skills"
PROMPTS = REPO / "prompts"
PACKAGED_PROMPTS = REPO / "src" / "parcel_robot" / "runtime_assets" / "prompts"

EMOTION_POSES = frozenset({"attentive_stand", "relaxed_crouch"})
EXPRESSIVE_REACTIONS = frozenset(
    {
        "chuckle",
        "confused_head_tilt",
        "head_nod",
        "head_shake",
        "observing_head_tilt",
        "shrug",
    }
)
EMOTION_GESTURES = frozenset(
    {
        "attentive_nod",
        "comfort_bow",
        "curious_look",
        "excited_paw_taps",
        "happy_wiggle",
    }
) | EXPRESSIVE_REACTIONS


def test_emotion_palette_is_catalogued_and_packaged() -> None:
    catalog = SkillCatalog.load(SKILLS)
    assert EMOTION_POSES | EMOTION_GESTURES <= set(catalog.ids())

    for relative in (
        "catalog.yaml",
        *(f"poses/{name}.yaml" for name in sorted(EMOTION_POSES)),
        *(f"trajectories/{name}.yaml" for name in sorted(EMOTION_GESTURES)),
    ):
        assert (SKILLS / relative).read_bytes() == (PACKAGED_SKILLS / relative).read_bytes()


def test_emotion_poses_are_bounded_and_not_automatic_reactions() -> None:
    catalog = SkillCatalog.load(SKILLS)
    stand = RobotProfile.go2().stand_joints()
    for name in EMOTION_POSES:
        skill = catalog.get(name)
        assert skill.kind == "pose"
        assert 0.0 <= skill.speed <= 1.0
        assert set(skill.joints) == set(stand)
        assert "hardware_unverified" in skill.tags
        assert max(abs(skill.joints[joint] - stand[joint]) for joint in stand) <= 0.20

    # Inferred reactions must self-return. Persistent poses remain explicit
    # posture choices and are never selected by a personality affect map.
    selected = {
        gesture
        for profile in PromptLibrary(PROMPTS).list_personalities()
        for gesture in profile.affect_actions.values()
    }
    assert EMOTION_POSES.isdisjoint(selected)


def test_emotion_gestures_are_short_social_trajectories_that_return_to_stand() -> None:
    catalog = SkillCatalog.load(SKILLS)
    stand = RobotProfile.go2().stand_joints()
    for name in EMOTION_GESTURES:
        skill = catalog.get(name)
        assert skill.kind == "trajectory"
        assert 0.0 <= skill.speed <= 1.0
        assert {"social", "gesture", "returns_to_stand", "hardware_unverified"} <= set(
            skill.tags
        )
        assert tuple(frame.t for frame in skill.keyframes) == tuple(
            sorted(frame.t for frame in skill.keyframes)
        )
        assert 0.0 < skill.keyframes[-1].t <= 1.5
        assert skill.keyframes[0].joints == stand
        assert skill.keyframes[-1].joints == stand
        assert all(set(frame.joints) == set(stand) for frame in skill.keyframes)
        assert max(
            abs(frame.joints[joint] - stand[joint])
            for frame in skill.keyframes
            for joint in stand
        ) <= 0.30


def test_excited_paw_taps_has_four_rapid_bend_return_cycles() -> None:
    skill = SkillCatalog.load(SKILLS).get("excited_paw_taps")
    stand = RobotProfile.go2().stand_joints()
    front_left = {"FL_hip_joint", "FL_thigh_joint", "FL_calf_joint"}
    other_joints = set(stand) - front_left

    assert tuple(frame.t for frame in skill.keyframes) == pytest.approx(
        (0.0, 0.12, 0.24, 0.36, 0.48, 0.60, 0.72, 0.84, 0.96)
    )
    bent_frames = skill.keyframes[1::2]
    returned_frames = skill.keyframes[2::2]
    assert len(bent_frames) == 4
    assert len(bent_frames) <= 5
    assert all(frame.joints["FL_thigh_joint"] < stand["FL_thigh_joint"] for frame in bent_frames)
    assert all(frame.joints["FL_calf_joint"] > stand["FL_calf_joint"] for frame in bent_frames)
    assert all(frame.joints == stand for frame in returned_frames)
    assert all(
        frame.joints[joint] == stand[joint]
        for frame in bent_frames
        for joint in other_joints
    )


def test_expressive_reactions_have_distinct_semantics_and_finite_playback() -> None:
    catalog = SkillCatalog.load(SKILLS)
    stand = RobotProfile.go2().stand_joints()
    semantic_tags = {
        "head_shake": "disagreement",
        "head_nod": "acknowledgement",
        "chuckle": "amusement",
        "shrug": "uncertainty",
        "confused_head_tilt": "confusion",
        "observing_head_tilt": "observing",
    }

    assert EXPRESSIVE_REACTIONS <= set(catalog.ids())
    for name, semantic_tag in semantic_tags.items():
        skill = catalog.get(name)
        assert semantic_tag in skill.tags
        assert "embodiment_proxy" in skill.tags
        player = TrajectoryPlayer()
        player.start(
            [
                {"t": frame.t, "joints": frame.joints}
                for frame in skill.keyframes
            ]
        )
        midpoint = player.joints_for(skill.keyframes[-1].t / 2.0)
        assert midpoint is not None
        assert all(math.isfinite(value) for value in midpoint.values())
        final = player.joints_for(skill.keyframes[-1].t)
        assert final == stand
        assert player.active is False

    for name in (
        "head_shake",
        "head_nod",
        "confused_head_tilt",
        "observing_head_tilt",
    ):
        assert "head_proxy" in catalog.get(name).tags


def test_personality_affect_actions_are_exact_social_gestures() -> None:
    catalog = SkillCatalog.load(SKILLS)
    profiles = {profile.id: profile for profile in PromptLibrary(PROMPTS).list_personalities()}

    assert profiles["gentle_companion"].affect_actions["sad"] == "comfort_bow"
    assert profiles["playful_companion"].affect_actions["happy"] == "happy_wiggle"
    assert all(
        profile.affect_actions["excited"] == "excited_paw_taps"
        for profile in profiles.values()
    )
    assert profiles["calm_guardian"].affect_actions == {
        "sad": "attentive_nod",
        "happy": "attentive_nod",
        "excited": "excited_paw_taps",
    }
    for profile in profiles.values():
        for name in profile.affect_actions.values():
            skill = catalog.get(name)
            assert skill.kind == "trajectory"
            assert "social" in skill.tags


def test_emotion_prompt_assets_are_packaged_and_defaults_expose_gestures() -> None:
    for relative in (
        "system/action_policy.md",
        "functions/companion.yaml",
        "personalities/calm_guardian.yaml",
        "personalities/gentle_companion.yaml",
        "personalities/playful_companion.yaml",
        "schemas/agent_decision.schema.json",
        "schemas/intent_frame_v1.schema.json",
    ):
        assert (PROMPTS / relative).read_bytes() == (PACKAGED_PROMPTS / relative).read_bytes()
    assert EMOTION_GESTURES <= set(RobotRuntime.DEFAULT_EMOTES)
