"""Safety and packaging contracts for Parcel's starter body-language palette."""

from __future__ import annotations

from pathlib import Path

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
EMOTION_GESTURES = frozenset(
    {"comfort_bow", "happy_wiggle", "attentive_nod", "curious_look"}
)


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


def test_personality_affect_actions_are_exact_social_gestures() -> None:
    catalog = SkillCatalog.load(SKILLS)
    profiles = {profile.id: profile for profile in PromptLibrary(PROMPTS).list_personalities()}

    assert profiles["gentle_companion"].affect_actions["sad"] == "comfort_bow"
    assert profiles["playful_companion"].affect_actions["happy"] == "happy_wiggle"
    assert profiles["calm_guardian"].affect_actions == {
        "sad": "attentive_nod",
        "happy": "attentive_nod",
    }
    for profile in profiles.values():
        for name in profile.affect_actions.values():
            skill = catalog.get(name)
            assert skill.kind == "trajectory"
            assert "social" in skill.tags


def test_emotion_prompt_assets_are_packaged_and_defaults_expose_gestures() -> None:
    for relative in (
        "system/action_policy.md",
        "personalities/calm_guardian.yaml",
        "personalities/gentle_companion.yaml",
        "personalities/playful_companion.yaml",
    ):
        assert (PROMPTS / relative).read_bytes() == (PACKAGED_PROMPTS / relative).read_bytes()
    assert EMOTION_GESTURES <= set(RobotRuntime.DEFAULT_EMOTES)
