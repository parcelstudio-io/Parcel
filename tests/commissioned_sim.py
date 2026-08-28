"""Explicit authenticated simulation capability fixtures for motion tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from parcel_robot.capabilities.commissioning_lifecycle import (
    CommissioningCurrentStateV1,
    CommissioningLifecycleV1,
)
from parcel_robot.capabilities.manifest import (
    CapabilityCommissioningV1,
    CommissionedArtifactV1,
    DeploymentTargetV1,
    EffectiveCapabilityProfileV1,
    NavigationModeCapabilityV1,
    TrustedCommissioningAuthenticatorV1,
    generate_effective_manifest,
)
from parcel_robot.realtime.voice_identity import CODE_ARMED, VoiceArmingDecision
from parcel_robot.skills.api import Dog
from parcel_robot.skills.capability_manifest import motion_capability_declarations

if TYPE_CHECKING:
    from parcel_robot.runtime import RobotRuntime

NOW_NS = 10_000_000_000
TARGET = DeploymentTargetV1(
    "adjacent_test_sim",
    "simulation",
    "adjacent_test_adapter",
    "c" * 64,
)
LIFECYCLE = CommissioningLifecycleV1(
    1,
    NOW_NS - 1,
    NOW_NS + 1_000_000,
    "adjacent-test-nonce",
    "adjacent-test-revocation",
)
CURRENT_STATE = CommissioningCurrentStateV1(1, LIFECYCLE.nonce)
AUTHENTICATOR = TrustedCommissioningAuthenticatorV1(
    authenticator_id="adjacent_test_authority",
    key=b"test-only-adjacent-commissioning-key",
)
NAVIGATION_MODES = (
    "follow_owner",
    "move_steps",
    "navigate",
    "orbit_owner",
    "owner_search",
    "roam",
    "turn_left",
    "turn_right",
    "walk_backward",
    "walk_forward",
)


def _current_state(
    _lifecycle: CommissioningLifecycleV1,
) -> CommissioningCurrentStateV1:
    return CURRENT_STATE


def commissioned_manifest(config_path: Path, *, include_embodied: bool = True):
    if include_embodied:
        dog = Dog.from_config(config_path)
        gestures, poses = motion_capability_declarations(dog.catalog)
    else:
        gestures, poses = (), ()
    navigation = tuple(
        NavigationModeCapabilityV1(name, ("locomotion",), ("fresh_lidar",))
        for name in NAVIGATION_MODES
    )
    artifacts = tuple(
        CommissionedArtifactV1(kind, item.name, item.artifact_digest)
        for kind, entries in (
            ("gesture", gestures),
            ("pose", poses),
            ("navigation_mode", navigation),
        )
        for item in entries
    )
    commissioning = AUTHENTICATOR.authenticate(
        CapabilityCommissioningV1(
            TARGET,
            AUTHENTICATOR.authenticator_id,
            "e" * 64,
            LIFECYCLE,
            artifacts,
        )
    )
    return generate_effective_manifest(
        profile=EffectiveCapabilityProfileV1(
            "adjacent_test_sim",
            TARGET,
            gestures=tuple(item.name for item in gestures),
            poses=tuple(item.name for item in poses),
            navigation_modes=NAVIGATION_MODES,
        ),
        commissioning=commissioning,
        commissioning_authenticator=AUTHENTICATOR,
        commissioning_state_provider=_current_state,
        now_monotonic_ns=NOW_NS,
        gestures=gestures,
        poses=poses,
        navigation_modes=navigation,
    )


def commissioned_runtime_kwargs(config_path: Path) -> dict[str, object]:
    """Return the explicit process-local seams needed for simulated motion."""

    return {
        "capability_manifest": commissioned_manifest(config_path),
        "deployment_target": TARGET,
        "commissioning_authenticator": AUTHENTICATOR,
        "commissioning_state_provider": _current_state,
        "commissioning_clock_ns": lambda: NOW_NS,
        "unsafe_simulator_conversation_motion": True,
    }


def commissioned_agent_kwargs(
    config_path: Path, *, include_embodied: bool = True
) -> dict[str, object]:
    """Return the equivalent explicit seams for a standalone ``VoiceAgent``."""

    return {
        "capability_manifest": commissioned_manifest(
            config_path, include_embodied=include_embodied
        ),
        "deployment_target": TARGET,
        "commissioning_authenticator": AUTHENTICATOR,
        "commissioning_state_provider": _current_state,
        "commissioning_clock_ns": lambda: NOW_NS,
        "conversation_motion_authorized": True,
    }


def authorize_commissioned_voice_binding(runtime: RobotRuntime) -> None:
    """Model an authenticated owner binding only on a commissioned test simulator."""

    target = runtime.deployment_target
    if (
        runtime.capability_manifest is None
        or target is None
        or target.environment != "simulation"
        or not runtime.unsafe_simulator_conversation_motion
    ):
        raise ValueError(
            "test voice binding requires an explicitly commissioned simulation runtime"
        )

    def _authorized(kind: str) -> VoiceArmingDecision:
        return VoiceArmingDecision(
            armed=True,
            code=CODE_ARMED,
            reason="authenticated one-shot commissioned-simulation test binding",
            kind=str(kind),
        )

    runtime._voice_arming_for = _authorized  # type: ignore[method-assign]
