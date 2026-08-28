"""CapabilityManifestV1: typed semantics and digest-bound commissioning."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.capabilities.commissioning_lifecycle import (
    CommissioningCurrentStateV1,
    CommissioningLifecycleV1,
)
from parcel_robot.capabilities.manifest import (
    AuthenticatedCapabilityCommissioningV1,
    CapabilityCommissioningV1,
    CapabilityManifestError,
    CapabilityManifestV1,
    CapabilityProfileError,
    CommissionedArtifactV1,
    DeploymentTargetV1,
    EffectiveCapabilityProfileV1,
    GestureCapabilityV1,
    NavigationModeCapabilityV1,
    PoseCapabilityV1,
    ToolCapabilityV1,
    TrustedCommissioningAuthenticatorV1,
    canonical_digest,
)
from parcel_robot.capabilities.manifest import (
    generate_effective_manifest as _generate_effective_manifest,
)
from parcel_robot.core.activities import ActivityContext, ActivityCoordinator
from parcel_robot.models import ActionProposal, AgentDecision, ToolCall
from parcel_robot.runtime import RobotRuntime as _RobotRuntime
from parcel_robot.skills.api import Dog
from parcel_robot.skills.capability_manifest import (
    motion_capability_declarations,
    skill_trajectory_digest,
    tool_capability_declarations,
)
from parcel_robot.skills.catalog import SkillCatalog
from parcel_robot.skills.schema import parse_skill
from parcel_robot.voice.agent import VoiceAgent as _VoiceAgent

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "configs" / "skills"
CONFIG = ROOT / "configs" / "robot.yaml"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
SIM_TARGET = DeploymentTargetV1(
    deployment_id="parcel_sim_1",
    environment="simulation",
    adapter_id="sim_adapter",
    adapter_identity_digest="c" * 64,
)
COMMISSIONING_AUTH = TrustedCommissioningAuthenticatorV1(
    authenticator_id="commissioning_authority",
    key=b"test-only-commissioning-key-material",
)
NOW_NS = 10_000_000_000
LIFECYCLE = CommissioningLifecycleV1(3, NOW_NS - 1, NOW_NS + 1_000_000, "nonce-3", "rev-3")
CURRENT_STATE = CommissioningCurrentStateV1(3, "nonce-3")


class VoiceAgent(_VoiceAgent):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("commissioning_authenticator", COMMISSIONING_AUTH)
        super().__init__(*args, **kwargs)


class RobotRuntime(_RobotRuntime):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("commissioning_authenticator", COMMISSIONING_AUTH)
        super().__init__(*args, **kwargs)


def generate_effective_manifest(**kwargs):
    return _generate_effective_manifest(
        **kwargs,
        commissioning_state_provider=lambda _lifecycle: CURRENT_STATE,
        now_monotonic_ns=NOW_NS,
    )


def _commissioning(
    artifacts: tuple[CommissionedArtifactV1, ...] = (),
    *,
    target: DeploymentTargetV1 = SIM_TARGET,
):
    return COMMISSIONING_AUTH.authenticate(
        CapabilityCommissioningV1(
            target,
            "commissioning_authority",
            "e" * 64,
            LIFECYCLE,
            artifacts,
        )
    )


def _declarations():
    tool = ToolCapabilityV1(
        name="weather",
        schema_digest=DIGEST_A,
        tags=("read_only",),
    )
    gesture = GestureCapabilityV1(
        name="opaque_motion_7",
        tags=("supportive", "social"),
        trajectory_digest=DIGEST_B,
    )
    pose = PoseCapabilityV1(
        name="quiet_pose",
        tags=("stationary", "social"),
        trajectory_digest=DIGEST_A,
    )
    navigation = NavigationModeCapabilityV1(
        name="follow_owner",
        tags=("owner_relative", "locomotion"),
        required_evidence=("owner_track", "fresh_lidar"),
    )
    return tool, gesture, pose, navigation


def _profile() -> EffectiveCapabilityProfileV1:
    return EffectiveCapabilityProfileV1(
        profile_id="sim_profile",
        deployment_target=SIM_TARGET,
        tools=("weather",),
        gestures=("opaque_motion_7",),
        poses=("quiet_pose",),
        navigation_modes=("follow_owner",),
    )


def _generate_for_lifecycle(
    lifecycle: CommissioningLifecycleV1,
    provider,
    *,
    now: int = NOW_NS,
):
    record = CapabilityCommissioningV1(
        SIM_TARGET,
        "commissioning_authority",
        "e" * 64,
        lifecycle,
    )
    return _generate_effective_manifest(
        profile=EffectiveCapabilityProfileV1("lifecycle_test", SIM_TARGET),
        commissioning=COMMISSIONING_AUTH.authenticate(record),
        commissioning_authenticator=COMMISSIONING_AUTH,
        commissioning_state_provider=provider,
        now_monotonic_ns=now,
    )


@pytest.mark.parametrize("bad", (True, False, 1.0, "1"))
def test_commissioning_lifecycle_rejects_non_integer_epoch(bad) -> None:
    with pytest.raises(ValueError, match="epoch must be an integer"):
        CommissioningLifecycleV1(bad, 1, 2, "nonce", "rev")


def test_generation_requires_current_nonrevoked_commissioning_state() -> None:
    with pytest.raises(ValueError, match="state provider is missing"):
        _generate_for_lifecycle(LIFECYCLE, None)
    with pytest.raises(ValueError, match="epoch is not current"):
        _generate_for_lifecycle(
            LIFECYCLE,
            lambda _lifecycle: CommissioningCurrentStateV1(4, "nonce-3"),
        )
    with pytest.raises(ValueError, match="nonce is not active"):
        _generate_for_lifecycle(
            LIFECYCLE,
            lambda _lifecycle: CommissioningCurrentStateV1(3, "other"),
        )
    with pytest.raises(ValueError, match="record is revoked"):
        _generate_for_lifecycle(
            LIFECYCLE,
            lambda _lifecycle: CommissioningCurrentStateV1(3, "nonce-3", {"rev-3"}),
        )
    with pytest.raises(ValueError, match="lookup failed"):
        _generate_for_lifecycle(LIFECYCLE, lambda _lifecycle: 1 / 0)
    with pytest.raises(ValueError, match="not currently valid"):
        _generate_for_lifecycle(LIFECYCLE, lambda _lifecycle: CURRENT_STATE, now=NOW_NS + 1_000_000)


def _voice_navigation_manifest(
    names: tuple[str, ...],
    *,
    commissioned: tuple[str, ...],
) -> CapabilityManifestV1:
    declarations = tuple(
        NavigationModeCapabilityV1(
            name=name,
            tags=("locomotion",),
            required_evidence=("fresh_lidar",),
        )
        for name in names
    )
    by_name = {entry.name: entry for entry in declarations}
    return generate_effective_manifest(
        profile=EffectiveCapabilityProfileV1(
            profile_id="voice_navigation_test",
            deployment_target=SIM_TARGET,
            navigation_modes=names,
        ),
        commissioning=_commissioning(
            tuple(
                CommissionedArtifactV1(
                    "navigation_mode",
                    name,
                    by_name[name].artifact_digest,
                )
                for name in commissioned
            )
        ),
        commissioning_authenticator=COMMISSIONING_AUTH,
        navigation_modes=declarations,
    )


def _voice_gesture_manifest(
    dog: Dog,
    *,
    commissioned: bool,
) -> CapabilityManifestV1:
    gestures, poses = motion_capability_declarations(dog.catalog)
    chuckle = next(entry for entry in gestures if entry.name == "chuckle")
    records = (
        (CommissionedArtifactV1("gesture", chuckle.name, chuckle.artifact_digest),)
        if commissioned
        else ()
    )
    return generate_effective_manifest(
        profile=EffectiveCapabilityProfileV1(
            profile_id="runtime_activity_test",
            deployment_target=SIM_TARGET,
            gestures=(chuckle.name,),
        ),
        commissioning=_commissioning(records),
        commissioning_authenticator=COMMISSIONING_AUTH,
        gestures=gestures,
        poses=poses,
    )


def test_manifest_is_canonical_and_digest_is_order_independent() -> None:
    tool, gesture, pose, navigation = _declarations()
    records = (
        CommissionedArtifactV1("navigation_mode", navigation.name, navigation.artifact_digest),
        CommissionedArtifactV1("pose", pose.name, pose.artifact_digest),
        CommissionedArtifactV1("gesture", gesture.name, gesture.artifact_digest),
        CommissionedArtifactV1("tool", tool.name, tool.artifact_digest),
    )
    first = generate_effective_manifest(
        profile=_profile(),
        commissioning=_commissioning(records),
        commissioning_authenticator=COMMISSIONING_AUTH,
        tools=(tool,),
        gestures=(gesture,),
        poses=(pose,),
        navigation_modes=(navigation,),
    )
    second = generate_effective_manifest(
        profile=EffectiveCapabilityProfileV1.from_mapping(
            {
                "navigation_modes": ["follow_owner"],
                "poses": ["quiet_pose"],
                "gestures": ["opaque_motion_7"],
                "tools": ["weather"],
                "profile_id": "sim_profile",
                "deployment_target": SIM_TARGET.as_dict(),
            }
        ),
        commissioning=_commissioning(tuple(reversed(records))),
        commissioning_authenticator=COMMISSIONING_AUTH,
        navigation_modes=(navigation,),
        poses=(pose,),
        gestures=(gesture,),
        tools=(tool,),
    )

    assert first == second
    assert first.manifest_digest == second.manifest_digest
    assert canonical_digest(first.as_dict()) != first.manifest_digest
    assert first.as_dict()["manifest_digest"] == first.manifest_digest
    assert first.available_embodied_names(required_tags=("social",)) == (
        "opaque_motion_7",
        "quiet_pose",
    )
    with pytest.raises(CapabilityManifestError, match="serialized commissioned state"):
        CapabilityManifestV1.from_mapping(first.as_dict())
    assert CapabilityCommissioningV1.from_mapping(
        _commissioning(records).commissioning.as_dict()
    ) == _commissioning(records).commissioning

    tampered = first.as_dict()
    tampered["profile_id"] = "other_profile"
    for field_name in ("tools", "gestures", "poses", "navigation_modes"):
        for row in tampered[field_name]:
            row["commissioned"] = False
    with pytest.raises(CapabilityManifestError, match="does not match"):
        CapabilityManifestV1.from_mapping(tampered)


def test_missing_commissioning_is_visible_and_never_available() -> None:
    tool, gesture, pose, navigation = _declarations()
    manifest = generate_effective_manifest(
        profile=_profile(),
        commissioning=_commissioning(),
        commissioning_authenticator=COMMISSIONING_AUTH,
        tools=(tool,),
        gestures=(gesture,),
        poses=(pose,),
        navigation_modes=(navigation,),
    )

    assert manifest.available_tools() == ()
    assert manifest.available_embodied_names(required_tags=("social",)) == ()
    assert manifest.available_navigation_modes() == ()
    assert manifest.prompt_context()["gestures"] == [
        {
            "name": "opaque_motion_7",
            "tags": ["social", "supportive"],
            "trajectory_digest": DIGEST_B,
            "commissioned": False,
        }
    ]


def test_commissioned_state_requires_matching_deployment_record() -> None:
    _, gesture, _, _ = _declarations()
    with pytest.raises(TypeError, match="commissioned"):
        GestureCapabilityV1(
            name=gesture.name,
            tags=gesture.tags,
            trajectory_digest=gesture.trajectory_digest,
            commissioned=True,  # type: ignore[call-arg]
        )


def test_unsigned_or_tampered_commissioning_cannot_generate_availability() -> None:
    _, gesture, _, _ = _declarations()
    raw = CapabilityCommissioningV1(
        SIM_TARGET,
        "commissioning_authority",
        "e" * 64,
        LIFECYCLE,
        (CommissionedArtifactV1("gesture", gesture.name, gesture.artifact_digest),),
    )
    parsed = CapabilityCommissioningV1.from_mapping(raw.as_dict())
    with pytest.raises(CapabilityProfileError, match="authentication failed"):
        generate_effective_manifest(
            profile=replace(
                _profile(),
                tools=(),
                poses=(),
                navigation_modes=(),
                gestures=(gesture.name,),
            ),
            commissioning=parsed,  # type: ignore[arg-type]
            commissioning_authenticator=COMMISSIONING_AUTH,
            gestures=(gesture,),
        )

    authenticated = COMMISSIONING_AUTH.authenticate(raw)
    tampered = replace(
        authenticated,
        auth_tag="f" * 64,
    )
    assert isinstance(authenticated, AuthenticatedCapabilityCommissioningV1)
    with pytest.raises(CapabilityProfileError, match="authentication failed"):
        generate_effective_manifest(
            profile=replace(
                _profile(),
                tools=(),
                poses=(),
                navigation_modes=(),
                gestures=(gesture.name,),
            ),
            commissioning=tampered,
            commissioning_authenticator=COMMISSIONING_AUTH,
            gestures=(gesture,),
        )

    physical_target = replace(
        SIM_TARGET,
        environment="physical",
        deployment_id="parcel_go2_1",
    )
    with pytest.raises(CapabilityProfileError, match="does not match profile"):
        generate_effective_manifest(
            profile=replace(_profile(), deployment_target=physical_target),
            commissioning=_commissioning(
                (
                    CommissionedArtifactV1(
                        "gesture", gesture.name, gesture.artifact_digest
                    ),
                ),
            ),
            commissioning_authenticator=COMMISSIONING_AUTH,
            gestures=(gesture,),
        )


def test_stale_or_unknown_commissioning_and_profile_names_fail_closed() -> None:
    tool, gesture, pose, navigation = _declarations()
    with pytest.raises(CapabilityProfileError, match="digest mismatch"):
        generate_effective_manifest(
            profile=_profile(),
            commissioning=_commissioning(
                (CommissionedArtifactV1("gesture", gesture.name, DIGEST_A),)
            ),
            commissioning_authenticator=COMMISSIONING_AUTH,
            tools=(tool,),
            gestures=(gesture,),
            poses=(pose,),
            navigation_modes=(navigation,),
        )

    with pytest.raises(CapabilityProfileError, match="unknown gesture"):
        generate_effective_manifest(
            profile=replace(_profile(), gestures=("invented_bow",)),
            commissioning=_commissioning(),
            commissioning_authenticator=COMMISSIONING_AUTH,
            tools=(tool,),
            gestures=(gesture,),
            poses=(pose,),
            navigation_modes=(navigation,),
        )

    with pytest.raises(CapabilityProfileError, match="undeclared"):
        generate_effective_manifest(
            profile=_profile(),
            commissioning=_commissioning(
                (CommissionedArtifactV1("gesture", "invented_bow", DIGEST_A),)
            ),
            commissioning_authenticator=COMMISSIONING_AUTH,
            tools=(tool,),
            gestures=(gesture,),
            poses=(pose,),
            navigation_modes=(navigation,),
        )


def test_names_never_supply_semantics_that_tags_do_not_declare() -> None:
    misleading = GestureCapabilityV1(
        name="super_social_comfort_bow",
        tags=("decorative",),
        trajectory_digest=DIGEST_A,
    )
    opaque = GestureCapabilityV1(
        name="g7",
        tags=("social", "supportive"),
        trajectory_digest=DIGEST_B,
    )
    profile = EffectiveCapabilityProfileV1(
        profile_id="tag_truth",
        deployment_target=SIM_TARGET,
        gestures=(misleading.name, opaque.name),
    )
    manifest = generate_effective_manifest(
        profile=profile,
        commissioning=_commissioning(
            (
                CommissionedArtifactV1("gesture", misleading.name, misleading.artifact_digest),
                CommissionedArtifactV1("gesture", opaque.name, opaque.artifact_digest),
            ),
        ),
        commissioning_authenticator=COMMISSIONING_AUTH,
        gestures=(misleading, opaque),
    )

    assert manifest.available_embodied_names(required_tags=("social",)) == ("g7",)
    assert not manifest.gesture_available(
        "super_social_comfort_bow",
        required_tags=("social",),
    )
    assert manifest.gesture_available("g7", required_tags=("supportive",))


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (lambda: ToolCapabilityV1("weather", "A" * 64), "lowercase"),
        (
            lambda: GestureCapabilityV1("wave", ("Social",), DIGEST_A),
            "tags must match",
        ),
        (
            lambda: NavigationModeCapabilityV1("follow", (), ()),
            "at least one evidence",
        ),
        (
            lambda: CapabilityManifestV1(
                profile_id="duplicate_kind",
                deployment_target=SIM_TARGET,
                commissioning_authority_id="commissioning_authority",
                commissioning_evidence_digest="e" * 64,
                commissioning_lifecycle=LIFECYCLE,
                gestures=(GestureCapabilityV1("same", (), DIGEST_A),),
                poses=(PoseCapabilityV1("same", (), DIGEST_B),),
            ),
            "span gesture, pose",
        ),
    ],
)
def test_malformed_or_ambiguous_manifests_refuse(factory, match: str) -> None:
    with pytest.raises(CapabilityManifestError, match=match):
        factory()


def test_skill_digests_bind_motion_not_source_path_and_kind_comes_from_tags() -> None:
    catalog = SkillCatalog.load(SKILLS)
    chuckle = catalog.get("chuckle")
    assert skill_trajectory_digest(chuckle) == skill_trajectory_digest(
        replace(chuckle, source_path="/a/different/install/root/chuckle.yaml")
    )
    changed = replace(
        chuckle,
        keyframes=(replace(chuckle.keyframes[0], t=chuckle.keyframes[0].t + 0.01),)
        + chuckle.keyframes[1:],
    )
    assert skill_trajectory_digest(chuckle) != skill_trajectory_digest(changed)

    named_like_a_gesture = parse_skill(
        {
            "id": "friendly_wave",
            "kind": "trajectory",
            "tags": ["social"],
            "keyframes": [
                {"t": 0.0, "joints": {"joint": 0.0}},
                {"t": 1.0, "joints": {"joint": 0.1}},
            ],
        }
    )
    explicit_gesture = replace(named_like_a_gesture, id="g8", tags=("gesture",))
    synthetic = SkillCatalog(
        {named_like_a_gesture.id: named_like_a_gesture, explicit_gesture.id: explicit_gesture},
        order=(named_like_a_gesture.id, explicit_gesture.id),
    )
    gestures, poses = motion_capability_declarations(synthetic)

    assert [entry.name for entry in gestures] == ["g8"]
    assert poses == ()


def test_tool_schema_digest_ignores_mapping_order_but_not_schema_changes() -> None:
    first = tool_capability_declarations(
        [
            {
                "name": "weather",
                "description": "read weather",
                "parameters": {
                    "type": "object",
                    "properties": {"place": {"type": "string"}},
                    "required": ["place"],
                },
            }
        ],
        tags_by_name={"weather": ("read_only",)},
    )[0]
    reordered = tool_capability_declarations(
        [
            {
                "parameters": {
                    "required": ["place"],
                    "properties": {"place": {"type": "string"}},
                    "type": "object",
                },
                "description": "different prose does not change the call schema",
                "name": "weather",
            }
        ],
        tags_by_name={"weather": ("read_only",)},
    )[0]
    changed = tool_capability_declarations(
        [
            {
                "name": "weather",
                "description": "read weather",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
    )[0]

    assert first.schema_digest == reordered.schema_digest
    assert first.schema_digest != changed.schema_digest


def test_voice_action_admission_uses_commissioned_typed_manifest() -> None:
    dog = Dog.from_config(CONFIG)
    gestures, poses = motion_capability_declarations(dog.catalog)
    selected = {entry.name: entry for entry in gestures}
    profile = EffectiveCapabilityProfileV1(
        profile_id="voice_test",
        deployment_target=SIM_TARGET,
        gestures=("chuckle", "head_nod"),
    )
    manifest = generate_effective_manifest(
        profile=profile,
        commissioning=_commissioning(
            (
                CommissionedArtifactV1(
                    "gesture",
                    "chuckle",
                    selected["chuckle"].trajectory_digest,
                ),
            ),
        ),
        commissioning_authenticator=COMMISSIONING_AUTH,
        gestures=gestures,
        poses=poses,
    )
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda _pose: None,
        dog=dog,
        capability_manifest=manifest,
        deployment_target=SIM_TARGET,
        conversation_motion_authorized=True,
        commissioning_state_provider=lambda _lifecycle: CURRENT_STATE,
        commissioning_clock_ns=lambda: NOW_NS,
        action_proposal_publisher=lambda _proposal: "accepted",
    )

    accepted = AgentDecision(
        reply="heh",
        next_action=ActionProposal(
            kind="skill",
            name="chuckle",
            trigger="conversation_reaction",
        ),
    )
    refused = replace(
        accepted,
        next_action=replace(accepted.next_action, name="head_nod"),
    )

    assert agent._validate_action_proposal(accepted, transcript="that was funny") is None
    assert "allowlist" in str(
        agent._validate_action_proposal(refused, transcript="yes")
    )

    live_chuckle = dog.catalog.get("chuckle")
    live_joint_name = next(iter(live_chuckle.keyframes[0].joints))
    original_joint = live_chuckle.keyframes[0].joints[live_joint_name]
    with pytest.raises(TypeError):
        live_chuckle.keyframes[0].joints[live_joint_name] = original_joint + 0.01
    assert agent._validate_action_proposal(accepted, transcript="that was funny") is None

    direct_agent = VoiceAgent(
        dog.poses(),
        [],
        lambda _pose: None,
        dog=dog,
        capability_manifest=manifest,
        deployment_target=SIM_TARGET,
        conversation_motion_authorized=True,
        commissioning_state_provider=lambda _lifecycle: CURRENT_STATE,
        commissioning_clock_ns=lambda: NOW_NS,
    )
    assert "not commissioned" in direct_agent._execute_named_skill("head_nod")

    stale = replace(
        manifest,
        gestures=(
            replace(manifest.gestures[0], trajectory_digest=DIGEST_A),
            *manifest.gestures[1:],
        ),
    )
    direct_agent.capability_manifest = stale
    assert "manifest is stale" in direct_agent._execute_named_skill("chuckle")
    with pytest.raises(ValueError, match="provenance authentication failed"):
        VoiceAgent(
            dog.poses(),
            [],
            lambda _pose: None,
            dog=dog,
            capability_manifest=stale,
            deployment_target=SIM_TARGET,
            conversation_motion_authorized=True,
            commissioning_state_provider=lambda _lifecycle: CURRENT_STATE,
            commissioning_clock_ns=lambda: NOW_NS,
        )


@pytest.mark.parametrize("bad", ("false", 0, 1, None))
def test_voice_conversation_motion_authority_requires_exact_bool(bad: object) -> None:
    with pytest.raises(TypeError, match="conversation_motion_authorized must be a boolean"):
        VoiceAgent({}, [], lambda _pose: None, conversation_motion_authorized=bad)


def test_direct_motion_routes_refuse_uncommissioned_navigation_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ("turn_left", "follow_owner", "navigate", "orbit_owner")
    manifest = _voice_navigation_manifest(names, commissioned=())
    dog = Dog.from_config(CONFIG)
    dispatched: list[str] = []
    monkeypatch.setattr(
        dog,
        "execute",
        lambda *_args, **_kwargs: dispatched.append("walk") or None,
    )
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda _pose: None,
        dog=dog,
        capability_manifest=manifest,
        deployment_target=SIM_TARGET,
        conversation_motion_authorized=True,
        commissioning_state_provider=lambda _lifecycle: CURRENT_STATE,
        commissioning_clock_ns=lambda: NOW_NS,
        behavior_publisher=lambda _mode: dispatched.append("behavior") or "started",
        navigation_publisher=lambda _directive: dispatched.append("navigation") or "started",
        spatial_behavior_publisher=lambda _intent: dispatched.append("spatial") or "started",
    )

    replies = (
        agent.handle_text("turn left"),
        agent.handle_text("follow me"),
        agent.handle_text("go to the sidewalk"),
        agent.handle_text("circle around me"),
    )

    assert all("not commissioned" in reply for reply in replies)
    assert dispatched == []


def test_direct_motion_routes_refuse_missing_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dog = Dog.from_config(CONFIG)
    dispatched: list[str] = []
    monkeypatch.setattr(
        dog,
        "execute",
        lambda *_args, **_kwargs: dispatched.append("walk") or None,
    )
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda _pose: None,
        dog=dog,
        behavior_publisher=lambda _mode: dispatched.append("behavior") or "started",
        navigation_publisher=lambda _directive: dispatched.append("navigation") or "started",
        spatial_behavior_publisher=lambda _intent: dispatched.append("spatial") or "started",
    )

    replies = (
        agent.handle_text("turn left"),
        agent.handle_text("follow me"),
        agent.handle_text("go to the sidewalk"),
        agent.handle_text("circle around me"),
    )

    assert all("manifest is unavailable" in reply for reply in replies)
    assert dispatched == []


def test_missing_manifest_hides_and_refuses_embodied_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dog = Dog.from_config(CONFIG)
    dispatched: list[str] = []
    monkeypatch.setattr(
        dog,
        "execute",
        lambda *_args, **_kwargs: dispatched.append("skill") or None,
    )
    agent = VoiceAgent(dog.poses(), [], lambda _pose: None, dog=dog)

    advertised = {tool["name"] for tool in agent.tool_definitions()}
    assert "run_pose" not in advertised
    assert "run_skill" not in advertised
    assert "manifest is unavailable" in agent._execute_named_skill("chuckle")
    reply = agent._execute(
        AgentDecision(
            "Doing it.",
            (ToolCall("run_skill", {"name": "chuckle"}),),
        ),
        transcript="perform chuckle",
    )
    assert "manifest is unavailable" in reply
    assert dispatched == []


def test_direct_motion_routes_refuse_stale_manifest_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ("turn_left", "follow_owner", "navigate", "orbit_owner")
    manifest = _voice_navigation_manifest(names, commissioned=names)
    dog = Dog.from_config(CONFIG)
    dispatched: list[str] = []
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda _pose: None,
        dog=dog,
        capability_manifest=manifest,
        deployment_target=SIM_TARGET,
        conversation_motion_authorized=True,
        commissioning_state_provider=lambda _lifecycle: CURRENT_STATE,
        commissioning_clock_ns=lambda: NOW_NS,
        behavior_publisher=lambda _mode: dispatched.append("behavior") or "started",
        navigation_publisher=lambda _directive: dispatched.append("navigation") or "started",
        spatial_behavior_publisher=lambda _intent: dispatched.append("spatial") or "started",
    )
    monkeypatch.setattr(
        dog,
        "execute",
        lambda *_args, **_kwargs: dispatched.append("walk") or None,
    )
    object.__setattr__(manifest, "profile_id", "tampered_after_commissioning")

    replies = (
        agent.handle_text("turn left"),
        agent.handle_text("follow me"),
        agent.handle_text("go to the sidewalk"),
        agent.handle_text("circle around me"),
    )

    assert all("manifest is stale" in reply for reply in replies)
    assert dispatched == []


def test_direct_motion_routes_dispatch_only_exact_commissioned_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ("turn_left", "follow_owner", "navigate", "orbit_owner")
    manifest = _voice_navigation_manifest(names, commissioned=names)
    dog = Dog.from_config(CONFIG)
    dispatched: list[str] = []

    class _Accepted:
        accepted = True
        message = "accepted"

    monkeypatch.setattr(
        dog,
        "execute",
        lambda *_args, **_kwargs: dispatched.append("walk") or _Accepted(),
    )
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda _pose: None,
        dog=dog,
        capability_manifest=manifest,
        deployment_target=SIM_TARGET,
        conversation_motion_authorized=True,
        commissioning_state_provider=lambda _lifecycle: CURRENT_STATE,
        commissioning_clock_ns=lambda: NOW_NS,
        behavior_publisher=lambda _mode: dispatched.append("behavior") or "started",
        navigation_publisher=lambda _directive: dispatched.append("navigation") or "started",
        spatial_behavior_publisher=lambda _intent: dispatched.append("spatial") or "started",
    )

    assert agent.handle_text("turn left") == "Turning left."
    assert agent.handle_text("follow me") == "I will follow you."
    assert agent.handle_text("go to the sidewalk").startswith("started")
    assert agent.handle_text("circle around me").startswith("started")
    assert dispatched == ["walk", "behavior", "navigation", "spatial"]


def test_commissioned_manifest_without_conversation_admission_stays_disarmed() -> None:
    manifest = _voice_navigation_manifest(("follow_owner",), commissioned=("follow_owner",))
    dog = Dog.from_config(CONFIG)
    dispatched: list[str] = []
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda _pose: None,
        dog=dog,
        capability_manifest=manifest,
        deployment_target=SIM_TARGET,
        commissioning_state_provider=lambda _lifecycle: CURRENT_STATE,
        commissioning_clock_ns=lambda: NOW_NS,
        behavior_publisher=lambda _mode: dispatched.append("follow") or "started",
    )

    reply = agent.handle_text("follow me")

    assert "Conversation motion authority is unavailable" in reply
    assert dispatched == []


def test_voice_revalidates_expiry_and_revocation_after_manifest_generation() -> None:
    manifest = _voice_navigation_manifest(("follow_owner",), commissioned=("follow_owner",))
    dog = Dog.from_config(CONFIG)
    now = [NOW_NS]
    current = [CURRENT_STATE]
    dispatched: list[str] = []
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda _pose: None,
        dog=dog,
        capability_manifest=manifest,
        deployment_target=SIM_TARGET,
        conversation_motion_authorized=True,
        commissioning_state_provider=lambda _lifecycle: current[0],
        commissioning_clock_ns=lambda: now[0],
        behavior_publisher=lambda _mode: dispatched.append("follow") or "started",
    )

    now[0] = LIFECYCLE.expires_monotonic_ns
    assert "not currently valid" in agent.handle_text("follow me")
    now[0] = NOW_NS
    current[0] = CommissioningCurrentStateV1(3, "nonce-3", {"rev-3"})
    assert "record is revoked" in agent.handle_text("follow me")
    assert dispatched == []


def test_runtime_revalidates_revocation_after_manifest_generation() -> None:
    dog = Dog.from_config(CONFIG)
    manifest = _voice_gesture_manifest(dog, commissioned=True)
    current = [CURRENT_STATE]
    runtime = object.__new__(RobotRuntime)
    runtime.dog = dog
    runtime.capability_manifest = manifest
    runtime.deployment_target = SIM_TARGET
    runtime.commissioning_authenticator = COMMISSIONING_AUTH
    runtime.commissioning_state_provider = lambda _lifecycle: current[0]
    runtime.commissioning_clock_ns = lambda: NOW_NS
    runtime._validate_capability_manifest()

    current[0] = CommissioningCurrentStateV1(3, "nonce-3", {"rev-3"})
    with pytest.raises(ValueError, match="record is revoked"):
        runtime._validate_capability_manifest()


def test_sim_manifest_cannot_enable_physical_conversation_adapter() -> None:
    manifest = _voice_navigation_manifest(("navigate",), commissioned=("navigate",))
    physical = DeploymentTargetV1("parcel_sim_1", "physical", "sim_adapter", "c" * 64)

    with pytest.raises(ValueError, match="restricted to an attested simulation"):
        VoiceAgent(
            {},
            [],
            lambda _pose: None,
            capability_manifest=manifest,
            deployment_target=physical,
            conversation_motion_authorized=True,
        )


def test_runtime_proposal_requires_commissioned_manifest_before_queueing() -> None:
    dog = Dog.from_config(CONFIG)
    runtime = object.__new__(RobotRuntime)
    runtime.dog = dog
    runtime.activities = ActivityCoordinator()
    runtime.capability_manifest = None
    runtime.deployment_target = SIM_TARGET
    runtime.commissioning_authenticator = COMMISSIONING_AUTH
    runtime.commissioning_state_provider = lambda _lifecycle: CURRENT_STATE
    runtime.commissioning_clock_ns = lambda: NOW_NS
    runtime._activity_context = lambda: ActivityContext()
    runtime._emit = lambda *_args: None
    proposal = ActionProposal(
        kind="skill",
        name="chuckle",
        trigger="explicit_command",
    )

    with pytest.raises(RuntimeError, match="manifest is unavailable"):
        runtime.propose_action(proposal)
    assert runtime.activities.snapshot()["pending"] == []

    runtime.capability_manifest = _voice_gesture_manifest(dog, commissioned=False)
    with pytest.raises(RuntimeError, match="not commissioned"):
        runtime.propose_action(proposal)
    assert runtime.activities.snapshot()["pending"] == []


@pytest.mark.parametrize(
    "target",
    (
        DeploymentTargetV1("other_deployment", "simulation", "sim_adapter", "c" * 64),
        DeploymentTargetV1("parcel_sim_1", "physical", "sim_adapter", "c" * 64),
        DeploymentTargetV1("parcel_sim_1", "simulation", "other_adapter", "c" * 64),
        DeploymentTargetV1("parcel_sim_1", "simulation", "sim_adapter", "d" * 64),
    ),
)
def test_runtime_rejects_manifest_for_another_attested_deployment(target) -> None:
    runtime = object.__new__(RobotRuntime)
    runtime.deployment_target = target
    manifest = _voice_navigation_manifest(("navigate",), commissioned=("navigate",))

    with pytest.raises(RuntimeError, match="does not match the attested runtime"):
        runtime._assert_manifest_deployment(manifest)


def test_panel_positive_motion_refuses_without_authenticated_operator() -> None:
    runtime = object.__new__(RobotRuntime)
    runtime.unsafe_simulator_conversation_motion = False

    with pytest.raises(RuntimeError, match="panel motion authority is unavailable"):
        runtime.action("follow")
    with pytest.raises(RuntimeError, match="panel motion authority is unavailable"):
        runtime.action("clear_emergency_stop")


def test_runtime_rechecks_manifest_at_final_activity_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dog = Dog.from_config(CONFIG)
    manifest = _voice_gesture_manifest(dog, commissioned=True)
    executed: list[str] = []
    monkeypatch.setattr(
        dog,
        "execute",
        lambda name, **_kwargs: executed.append(name) or None,
    )
    runtime = object.__new__(RobotRuntime)
    runtime.dog = dog
    runtime.capability_manifest = manifest
    runtime.deployment_target = SIM_TARGET
    runtime.commissioning_authenticator = COMMISSIONING_AUTH
    runtime.commissioning_state_provider = lambda _lifecycle: CURRENT_STATE
    runtime.commissioning_clock_ns = lambda: NOW_NS
    runtime.activities = ActivityCoordinator(cooldown_s=0.0)
    runtime._activity_context = lambda: ActivityContext()
    runtime._narrate_expired_activities = lambda: None
    runtime._narrate_finished_activity = lambda *_args, **_kwargs: False
    runtime._emit = lambda *_args: None
    runtime._command_lock = threading.RLock()
    runtime._activity_complete_at = 0.0
    runtime._activity_dispatch_active = False
    runtime._closed = False
    proposal = ActionProposal(
        kind="skill",
        name="chuckle",
        trigger="explicit_command",
    )
    assert runtime.activities.submit(proposal, ActivityContext()).accepted
    object.__setattr__(manifest, "profile_id", "tampered_before_dispatch")

    runtime._step_activities()

    assert executed == []
    recent = runtime.activities.snapshot()["recent"]
    assert recent[0]["status"] == "cancelled"
    assert "manifest_digest" in str(recent[0]["detail"])
