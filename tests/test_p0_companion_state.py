"""P0 companion-state contracts: proposals are weak, local receipts are facts."""

from __future__ import annotations

from copy import copy
from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest

from parcel_robot.capabilities.commissioning_lifecycle import (
    CommissioningCurrentStateV1,
    CommissioningLifecycleV1,
)
from parcel_robot.capabilities.manifest import (
    CapabilityCommissioningV1,
    CommissionedArtifactV1,
    DeploymentTargetV1,
    EffectiveCapabilityProfileV1,
    GestureCapabilityV1,
    NavigationModeCapabilityV1,
    PoseCapabilityV1,
    TrustedCommissioningAuthenticatorV1,
)
from parcel_robot.capabilities.manifest import (
    generate_effective_manifest as _generate_effective_manifest,
)
from parcel_robot.contracts.companion_v1 import (
    ActionReceiptV1,
    ConsentDecisionV1,
    ConsentScopesV1,
    ConversationActionProposalV1,
    EmbodimentEnvelopeV1,
    OperatorEvidenceV1,
    OwnerEvidenceV1,
)
from parcel_robot.contracts.dialogue_state_v1 import (
    DialogueMemoryRecordV1,
    DialogueStateV1,
    RetrievalStateV1,
)
from parcel_robot.contracts.opportunity_v1 import OpportunityCandidateV1
from parcel_robot.contracts.terminal_claim_v1 import TerminalClaimProposalV1
from parcel_robot.voice.companion_state import (
    ActionBindingRegistryV1,
    ActionScopeBindingV1,
    AuthenticatedActionReceiptV1,
    AuthenticatedEmbodimentEnvelopeV1,
    TrustedEmbodimentAuthenticatorV1,
    TrustedOperatorAuthenticatorV1,
    TrustedReceiptAuthenticatorV1,
    admit_opportunity,
    admit_opportunity_mapping,
    apply_action_receipt,
    license_terminal_claim,
    resolve_repeat_action,
    retrieval_answers,
)
from parcel_robot.voice.companion_state import (
    admit_conversation_action as _admit_conversation_action,
)
from parcel_robot.voice.companion_state import (
    begin_admitted_action as _begin_admitted_action,
)

NOW = 1_000_000_000
TARGET = DeploymentTargetV1("sim_1", "simulation", "sim_adapter", "d" * 64)
_GESTURE_DECLARATIONS = (
    GestureCapabilityV1("chuckle", ("social",), "b" * 64),
)
_POSE_DECLARATIONS = (
    PoseCapabilityV1("quiet_pose", ("social",), "d" * 64),
)
_NAVIGATION_DECLARATIONS = tuple(
    NavigationModeCapabilityV1(
        name,
        ("locomotion", "owner_relative"),
        ("fresh_lidar", "owner_track"),
    )
    for name in ("approach_owner", "follow_owner")
)
COMMISSIONING_AUTH = TrustedCommissioningAuthenticatorV1(
    authenticator_id="commissioning_authority",
    key=b"test-only-commissioning-key-material",
)
LIFECYCLE = CommissioningLifecycleV1(1, NOW - 1, NOW + 1_000_000, "nonce", "rev")
CURRENT_STATE = CommissioningCurrentStateV1(1, "nonce")


def _commissioning_state_provider(
    _lifecycle: CommissioningLifecycleV1,
) -> CommissioningCurrentStateV1:
    return CURRENT_STATE


def generate_effective_manifest(**kwargs):
    return _generate_effective_manifest(
        **kwargs,
        commissioning_state_provider=_commissioning_state_provider,
        now_monotonic_ns=NOW,
    )


def admit_conversation_action(*args: Any, **kwargs: Any):
    kwargs.setdefault("commissioning_authenticator", COMMISSIONING_AUTH)
    kwargs.setdefault("commissioning_state_provider", _commissioning_state_provider)
    return _admit_conversation_action(*args, **kwargs)


def begin_admitted_action(*args: Any, **kwargs: Any):
    kwargs.setdefault("commissioning_authenticator", COMMISSIONING_AUTH)
    kwargs.setdefault("commissioning_state_provider", _commissioning_state_provider)
    return _begin_admitted_action(*args, **kwargs)


CAPABILITY_MANIFEST = generate_effective_manifest(
    profile=EffectiveCapabilityProfileV1(
        "companion_test",
        TARGET,
        gestures=tuple(item.name for item in _GESTURE_DECLARATIONS),
        poses=tuple(item.name for item in _POSE_DECLARATIONS),
        navigation_modes=tuple(item.name for item in _NAVIGATION_DECLARATIONS),
    ),
    commissioning=COMMISSIONING_AUTH.authenticate(
        CapabilityCommissioningV1(
            TARGET,
            "commissioning_authority",
            "e" * 64,
            LIFECYCLE,
            (
                *(
                CommissionedArtifactV1("gesture", item.name, item.artifact_digest)
                    for item in _GESTURE_DECLARATIONS
                ),
                *(
                    CommissionedArtifactV1("pose", item.name, item.artifact_digest)
                    for item in _POSE_DECLARATIONS
                ),
                *(
                    CommissionedArtifactV1(
                        "navigation_mode", item.name, item.artifact_digest
                    )
                    for item in _NAVIGATION_DECLARATIONS
                ),
            ),
        ),
    ),
    commissioning_authenticator=COMMISSIONING_AUTH,
    gestures=_GESTURE_DECLARATIONS,
    poses=_POSE_DECLARATIONS,
    navigation_modes=_NAVIGATION_DECLARATIONS,
)
MANIFEST = CAPABILITY_MANIFEST.manifest_digest
AUTH = TrustedReceiptAuthenticatorV1(
    authenticator_id="local_executive_channel",
    key=b"test-only-receipt-key-material-32b",
)
OPERATOR_AUTH = TrustedOperatorAuthenticatorV1(
    authenticator_id="operator_identity_channel",
    key=b"test-only-operator-identity-key-32b",
)
EMBODIMENT_AUTH = TrustedEmbodimentAuthenticatorV1(
    authenticator_id="embodiment_snapshot_channel",
    key=b"test-only-embodiment-snapshot-key-32b",
)


def _consent(
    status: str = "granted",
    *,
    principal: str = "owner-1",
    evidence: str = "consent-1",
    epoch: int = 4,
    decided: int | None = 100,
    expires: int | None = 10_000_000_000,
) -> ConsentDecisionV1:
    if status == "unknown":
        principal = ""
        evidence = ""
        decided = None
        expires = None
    return ConsentDecisionV1(
        status=status,
        principal_id=principal,
        evidence_id=evidence,
        source_epoch=epoch,
        decided_at_monotonic_ns=decided,
        expires_at_monotonic_ns=expires,
    )


def _scopes(*, epoch: int = 4, **overrides: ConsentDecisionV1) -> ConsentScopesV1:
    values = {
        "speech": _consent(evidence="speech-consent", epoch=epoch),
        "proactive_speech": _consent(evidence="proactive-consent", epoch=epoch),
        "stationary_expression": _consent(evidence="expression-consent", epoch=epoch),
        "approach": _consent(evidence="approach-consent", epoch=epoch),
        "following": _consent(evidence="following-consent", epoch=epoch),
        "owner_search": _consent(evidence="search-consent", epoch=epoch),
        "navigation": _consent(evidence="navigation-consent", epoch=epoch),
    }
    values.update(overrides)
    return ConsentScopesV1(**values)


def _owner(
    *,
    verified: bool = True,
    confidence: float = 0.98,
    epoch: int = 4,
    expires: int = 10_000_000_000,
) -> OwnerEvidenceV1:
    return OwnerEvidenceV1(
        principal_id="owner-1" if verified else "",
        verified=verified,
        confidence=confidence,
        evidence_id="voice-owner-1" if verified else "",
        source_epoch=epoch,
        received_monotonic_ns=NOW - 10_000_000,
        expires_monotonic_ns=expires,
    )


def _operator(*, verified: bool = True) -> OperatorEvidenceV1:
    return OperatorEvidenceV1(
        principal_id="operator-1" if verified else "",
        verified=verified,
        confidence=0.99 if verified else 0.0,
        evidence_id="operator-auth-1" if verified else "",
        source_epoch=4,
        received_monotonic_ns=NOW - 10_000_000,
        expires_monotonic_ns=2_000_000_000,
    )


def _envelope(
    *,
    initiator: str = "owner",
    owner: OwnerEvidenceV1 | None = None,
    operator: OperatorEvidenceV1 | None = None,
    consent: ConsentScopesV1 | None = None,
    manifest: str = MANIFEST,
    action_bindings_digest: str | None = None,
    actions: tuple[str, ...] = (
        "approach_owner",
        "chuckle",
        "follow_owner",
        "quiet_pose",
    ),
    expires: int = 2_000_000_000,
    body_mode: str = "idle",
    estop_state: str = "clear",
    pending_action_id: str | None = None,
    pending_action_status: str = "",
    busy_reason: str = "",
) -> EmbodimentEnvelopeV1:
    return EmbodimentEnvelopeV1(
        envelope_id="body-1",
        manifest_digest=manifest,
        commissioned_actions=actions,
        action_bindings_digest=(
            _bindings().registry_digest
            if action_bindings_digest is None
            else action_bindings_digest
        ),
        snapshot_monotonic_ns=NOW - 20_000_000,
        expires_monotonic_ns=expires,
        initiator=initiator,
        owner=owner or _owner(),
        operator=operator,
        body_mode=body_mode,
        estop_state=estop_state,
        locomotion_commissioned=True,
        locomotion_healthy=True,
        affordance_state="ready",
        space_state="clear",
        pending_action_id=pending_action_id,
        pending_action_status=pending_action_status,
        last_terminal_receipt_id=None,
        busy_reason=busy_reason,
        consent=consent or _scopes(),
    )


def _proposal(
    action: str = "chuckle",
    *,
    initiator: str = "owner",
    principal: str = "owner-1",
    manifest: str = MANIFEST,
    proposal_id: str = "proposal-1",
    turn_id: str = "turn-1",
) -> ConversationActionProposalV1:
    return ConversationActionProposalV1(
        proposal_id=proposal_id,
        turn_id=turn_id,
        action_name=action,
        manifest_digest=manifest,
        initiator=initiator,
        requested_by_principal_id=principal,
        created_at_monotonic_ns=NOW - 1,
        expires_monotonic_ns=NOW + 1_000_000_000,
    )


def _authenticated(
    envelope: EmbodimentEnvelopeV1,
) -> AuthenticatedEmbodimentEnvelopeV1:
    return EMBODIMENT_AUTH.authenticate(envelope)


def _binding(
    scope: str = "stationary_expression",
    *,
    initiators: tuple[str, ...] = ("owner", "system"),
    verified: bool = True,
    idle: bool = True,
    locomotion: bool = False,
    clear_space: bool = False,
    repeatable: bool = True,
) -> ActionScopeBindingV1:
    return ActionScopeBindingV1(
        consent_scope=scope,
        allowed_initiators=initiators,
        requires_verified_owner=verified,
        requires_idle_body=idle,
        requires_locomotion=locomotion,
        requires_clear_space=clear_space,
        repeatable=repeatable,
    )


def _registry(
    bindings: dict[str, ActionScopeBindingV1],
) -> ActionBindingRegistryV1:
    return ActionBindingRegistryV1(tuple(bindings.items()))


def _bindings() -> ActionBindingRegistryV1:
    return _registry({
        "chuckle": _binding(),
        "approach_owner": _binding(
            "approach",
            initiators=("owner", "system"),
            locomotion=True,
            clear_space=True,
        ),
        "follow_owner": _binding(
            "following",
            initiators=("owner",),
            locomotion=True,
            clear_space=True,
        ),
    })


def _admission(action: str = "chuckle"):
    return admit_conversation_action(
        _proposal(action),
        _authenticated(_envelope()),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )


def _begin(
    state: DialogueStateV1,
    admission,
    *,
    now: int = NOW,
    proposal: ConversationActionProposalV1 | None = None,
    envelope: EmbodimentEnvelopeV1 | None = None,
    commissioning_state_provider: Any = _commissioning_state_provider,
) -> DialogueStateV1:
    current_proposal = proposal or _proposal(
        admission.action_name,
        manifest=admission.manifest_digest,
        proposal_id=admission.proposal_id,
        turn_id=admission.turn_id,
    )
    return begin_admitted_action(
        state,
        admission,
        proposal=current_proposal,
        authenticated_envelope=_authenticated(envelope or _envelope()),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        commissioning_state_provider=commissioning_state_provider,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=now,
    )


def _receipt(
    admission, status: str, sequence: int, *, issued: int
) -> AuthenticatedActionReceiptV1:
    assert admission.mission_id is not None
    assert admission.action_id is not None
    return AUTH.authenticate(
        ActionReceiptV1.mint(
            mission_id=admission.mission_id,
            action_id=admission.action_id,
            action_name=admission.action_name,
            manifest_digest=admission.manifest_digest,
            status=status,
            sequence=sequence,
            issued_at_monotonic_ns=issued,
            claimable_until_monotonic_ns=NOW + 2_000_000_000,
            evidence_refs=(f"executive-{sequence}",),
        )
    )


def _claim(
    receipt: ActionReceiptV1 | AuthenticatedActionReceiptV1,
    *,
    status: str | None = None,
) -> TerminalClaimProposalV1:
    return TerminalClaimProposalV1(
        claim_id="claim-1",
        mission_id=receipt.mission_id,
        action_id=receipt.action_id,
        action_name=receipt.action_name,
        manifest_digest=receipt.manifest_digest,
        terminal_receipt_id=receipt.receipt_id,
        claimed_status=status or receipt.status,
        proposed_at_monotonic_ns=receipt.issued_at_monotonic_ns + 1,
    )


def _started_state():
    admission = _admission()
    state = _begin(
        DialogueStateV1.empty(session_id="session-1", now_monotonic_ns=NOW - 100),
        admission,
        now=NOW,
    )
    started = _receipt(admission, "started", 1, issued=NOW + 10)
    reduction = apply_action_receipt(
        state, started, receipt_authenticator=AUTH, now_monotonic_ns=NOW + 10
    )
    assert reduction.accepted
    return admission, reduction.state, started


def _opportunity(**changes: object) -> OpportunityCandidateV1:
    values = {
        "candidate_id": "opportunity-1",
        "source_epoch": 4,
        "subject_id": "front-door",
        "event_class": "owner-arrival",
        "evidence_id": "scene-4",
        "observed_monotonic_ns": NOW - 30_000_000,
        "received_monotonic_ns": NOW - 20_000_000,
        "expires_monotonic_ns": NOW + 500_000_000,
        "novelty": 0.9,
        "confidence": 0.95,
        "owner": _owner(),
        "privacy_state": "public",
        "quiet_state": "normal",
        "owner_speaking": False,
        "tts_active": False,
        "proactive_consent": _consent(evidence="proactive-consent"),
    }
    values.update(changes)
    return OpportunityCandidateV1(**values)


def test_contracts_are_frozen_strict_and_round_trip() -> None:
    envelope = _envelope()
    assert EmbodimentEnvelopeV1.from_mapping(envelope.as_dict()) == envelope
    proposal = _proposal()
    assert ConversationActionProposalV1.from_mapping(proposal.as_dict()) == proposal
    candidate = _opportunity()
    assert OpportunityCandidateV1.from_mapping(candidate.as_dict()) == candidate
    with pytest.raises(FrozenInstanceError):
        proposal.action_name = "follow_owner"  # type: ignore[misc]

    unknown = candidate.as_dict()
    unknown["model_says_safe"] = True
    with pytest.raises(ValueError, match="unknown"):
        OpportunityCandidateV1.from_mapping(unknown)
    wrong_bool = candidate.as_dict()
    wrong_bool["owner_speaking"] = "false"
    with pytest.raises(TypeError, match="boolean"):
        OpportunityCandidateV1.from_mapping(wrong_bool)
    nonfinite = candidate.as_dict()
    nonfinite["novelty"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        OpportunityCandidateV1.from_mapping(nonfinite)


def test_scoped_consent_is_complete_and_does_not_alias_permissions() -> None:
    denied = _scopes(stationary_expression=_consent("denied"))
    result = admit_conversation_action(
        _proposal("chuckle"),
        _authenticated(_envelope(consent=denied)),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert not result.admitted
    assert result.reason == "consent_not_granted:stationary_expression"
    assert denied.speech.status == "granted"

    payload = _scopes().as_dict()
    del payload["following"]
    with pytest.raises(ValueError, match="missing"):
        ConsentScopesV1.from_mapping(payload)

    stale_epoch = _scopes(following=_consent(epoch=3))
    with pytest.raises(ValueError, match="source epochs"):
        _envelope(consent=stale_epoch)


def test_model_proposal_is_not_authority_and_ids_are_locally_deterministic() -> None:
    proposal = _proposal()
    first = admit_conversation_action(
        proposal,
        _authenticated(_envelope()),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    second = admit_conversation_action(
        proposal,
        _authenticated(_envelope()),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert not proposal.authorizes_actuation
    assert first.admitted and first == second
    assert type(first).from_mapping(first.as_dict()) == first
    assert not first.authorizes_actuation
    assert first.expires_monotonic_ns == proposal.expires_monotonic_ns
    assert first.mission_id is not None and first.mission_id.startswith("mission-")
    assert first.action_id is not None and first.action_id.startswith("action-")
    forged = first.as_dict()
    forged["mission_id"] = "mission-" + "b" * 24
    with pytest.raises(ValueError, match="do not match proposal content"):
        type(first).from_mapping(forged)


@pytest.mark.parametrize(
    ("proposal", "envelope", "reason"),
    [
        (_proposal(manifest="f" * 64), _envelope(), "proposal_manifest_not_trusted"),
        (_proposal("not_installed"), _envelope(), "action_not_commissioned"),
        (_proposal(principal="stranger"), _envelope(), "request_principal_mismatch"),
        (_proposal(), _envelope(estop_state="active"), "estop_not_clear"),
        (
            _proposal(),
            _envelope(pending_action_id="existing-action", pending_action_status="started"),
            "action_pending_or_busy",
        ),
    ],
)
def test_action_admission_fails_closed(proposal, envelope, reason: str) -> None:
    result = admit_conversation_action(
        proposal,
        _authenticated(envelope),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert not result.admitted
    assert result.reason == reason
    assert result.mission_id is None and result.action_id is None


def test_action_admission_fences_prior_source_epoch_even_while_envelope_is_fresh() -> None:
    prior_epoch = _envelope(owner=_owner(epoch=3), consent=_scopes(epoch=3))
    result = admit_conversation_action(
        _proposal(),
        _authenticated(prior_epoch),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert not result.admitted
    assert result.reason == "source_epoch_mismatch"


def test_action_admission_requires_current_trusted_commissioning_state() -> None:
    revoked = CommissioningCurrentStateV1(1, "nonce", frozenset({"rev"}))

    with pytest.raises(ValueError, match="state provider is missing"):
        admit_conversation_action(
            _proposal(),
            _authenticated(_envelope()),
            embodiment_authenticator=EMBODIMENT_AUTH,
            capability_manifest=CAPABILITY_MANIFEST,
            commissioning_state_provider=None,
            action_bindings=_bindings(),
            current_source_epoch=4,
            now_monotonic_ns=NOW,
        )
    with pytest.raises(ValueError, match="record is revoked"):
        admit_conversation_action(
            _proposal(),
            _authenticated(_envelope()),
            embodiment_authenticator=EMBODIMENT_AUTH,
            capability_manifest=CAPABILITY_MANIFEST,
            commissioning_state_provider=lambda _lifecycle: revoked,
            action_bindings=_bindings(),
            current_source_epoch=4,
            now_monotonic_ns=NOW,
        )
    with pytest.raises(ValueError, match="not currently valid"):
        admit_conversation_action(
            _proposal(),
            _authenticated(_envelope()),
            embodiment_authenticator=EMBODIMENT_AUTH,
            capability_manifest=CAPABILITY_MANIFEST,
            commissioning_state_provider=_commissioning_state_provider,
            action_bindings=_bindings(),
            current_source_epoch=4,
            now_monotonic_ns=LIFECYCLE.expires_monotonic_ns,
        )


def test_model_cannot_downgrade_travel_to_a_weaker_scope() -> None:
    # The proposal has no consent-scope field. The trusted exact-name binding
    # selects `approach`, so granted expression consent cannot substitute.
    scopes = _scopes(approach=_consent("denied"))
    result = admit_conversation_action(
        _proposal("approach_owner"),
        _authenticated(_envelope(consent=scopes)),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert not result.admitted
    assert result.consent_scope == "approach"
    assert result.reason == "consent_not_granted:approach"


def test_sealed_binding_registry_blocks_movement_consent_scope_substitution() -> None:
    sealed = _authenticated(_envelope())
    swapped = dict(_bindings().bindings)
    swapped["approach_owner"] = _binding(
        "following", locomotion=True, clear_space=True
    )
    result = admit_conversation_action(
        _proposal("approach_owner"),
        sealed,
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_registry(swapped),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert not result.admitted
    assert result.reason == "action_binding_registry_digest_mismatch"


def test_post_construction_binding_mutation_cannot_preserve_cached_authority() -> None:
    registry = _bindings()
    sealed = _authenticated(
        _envelope(action_bindings_digest=registry.registry_digest)
    )
    object.__setattr__(
        registry,
        "bindings",
        (
            (
                "approach_owner",
                _binding("approach", locomotion=True, clear_space=False),
            ),
        ),
    )
    result = admit_conversation_action(
        _proposal("approach_owner"),
        sealed,
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=registry,
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert not result.admitted
    assert result.reason == "action_binding_registry_integrity_failed"


def test_post_construction_manifest_mutation_cannot_preserve_cached_authority() -> None:
    tampered_manifest = copy(CAPABILITY_MANIFEST)
    object.__setattr__(tampered_manifest, "navigation_modes", ())
    with pytest.raises(ValueError, match="manifest_digest no longer matches"):
        admit_conversation_action(
            _proposal("approach_owner"),
            _authenticated(_envelope()),
            embodiment_authenticator=EMBODIMENT_AUTH,
            capability_manifest=tampered_manifest,
            action_bindings=_bindings(),
            current_source_epoch=4,
            now_monotonic_ns=NOW,
        )


def test_system_initiated_travel_is_refused_even_if_commissioned_and_consented() -> None:
    result = admit_conversation_action(
        _proposal("approach_owner", initiator="system", principal=""),
        _authenticated(_envelope(initiator="system")),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert not result.admitted
    assert result.reason == "system_initiated_travel_forbidden"


def test_bridge_rejects_caller_asserted_commissioned_action_set() -> None:
    forged = _envelope(actions=("chuckle",))
    result = admit_conversation_action(
        _proposal("chuckle"),
        _authenticated(forged),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert not result.admitted
    assert result.reason == "commissioned_action_set_not_trusted"


def test_raw_tampered_or_wrong_channel_envelope_cannot_admit_movement() -> None:
    proposal = _proposal("approach_owner")
    raw = _envelope()
    with pytest.raises(TypeError, match="authenticated_envelope"):
        admit_conversation_action(  # type: ignore[arg-type]
            proposal,
            raw,
            embodiment_authenticator=EMBODIMENT_AUTH,
            capability_manifest=CAPABILITY_MANIFEST,
            action_bindings=_bindings(),
            current_source_epoch=4,
            now_monotonic_ns=NOW,
        )

    signed_blocked = _authenticated(_envelope(estop_state="active"))
    tampered = replace(
        signed_blocked,
        envelope=replace(signed_blocked.envelope, estop_state="clear"),
    )
    rejected = admit_conversation_action(
        proposal,
        tampered,
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert rejected.reason == "embodiment_authentication_failed"

    wrong_channel = TrustedEmbodimentAuthenticatorV1(
        authenticator_id="other_embodiment_channel",
        key=b"different-embodiment-snapshot-key-32b",
    )
    rejected = admit_conversation_action(
        proposal,
        _authenticated(raw),
        embodiment_authenticator=wrong_channel,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert rejected.reason == "embodiment_authentication_failed"
    assert not _authenticated(raw).authorizes_actuation


def test_operator_actions_require_authenticated_operator_evidence() -> None:
    operator_binding = _binding(initiators=("operator",))
    registry = _registry({"chuckle": operator_binding})
    proposal = _proposal(
        "chuckle", initiator="operator", principal="operator-1"
    )
    missing = admit_conversation_action(
        proposal,
        _authenticated(
            _envelope(
                initiator="operator",
                action_bindings_digest=registry.registry_digest,
            )
        ),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=registry,
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert missing.reason == "operator_evidence_not_authenticated"

    operator = _operator()
    admitted = admit_conversation_action(
        proposal,
        _authenticated(
            _envelope(
                initiator="operator",
                operator=operator,
                action_bindings_digest=registry.registry_digest,
            )
        ),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=registry,
        current_source_epoch=4,
        now_monotonic_ns=NOW,
        authenticated_operator=OPERATOR_AUTH.authenticate(operator),
        operator_authenticator=OPERATOR_AUTH,
    )
    assert admitted.admitted


def test_movement_binding_structurally_requires_verified_owner() -> None:
    with pytest.raises(ValueError, match="verified owner"):
        _binding("following", verified=False, locomotion=True)


def test_manifest_category_blocks_navigation_as_stationary_expression() -> None:
    registry = _registry({"approach_owner": _binding()})
    result = admit_conversation_action(
        _proposal("approach_owner"),
        _authenticated(_envelope(action_bindings_digest=registry.registry_digest)),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=registry,
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert not result.admitted
    assert result.reason == "navigation_action_requires_movement_scope"


def test_manifest_category_blocks_pose_as_navigation() -> None:
    registry = _registry(
        {
            "quiet_pose": _binding(
                "navigation", locomotion=True, clear_space=True
            )
        }
    )
    result = admit_conversation_action(
        _proposal("quiet_pose"),
        _authenticated(_envelope(action_bindings_digest=registry.registry_digest)),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=registry,
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert not result.admitted
    assert result.reason == "stationary_action_cannot_use_movement_scope"


@pytest.mark.parametrize(
    ("proposal", "envelope", "reason"),
    [
        (
            replace(_proposal(), expires_monotonic_ns=NOW + 6_000_000_000),
            _envelope(),
            "proposal_ttl_exceeds_limit",
        ),
        (
            _proposal(),
            _envelope(expires=NOW + 3_000_000_000),
            "envelope_ttl_exceeds_limit",
        ),
        (
            _proposal(),
            _envelope(owner=_owner(expires=NOW + 11_000_000_000)),
            "owner_evidence_ttl_exceeds_limit",
        ),
        (
            _proposal(),
            _envelope(
                consent=_scopes(
                    stationary_expression=_consent(
                        decided=100, expires=70_000_000_101
                    )
                )
            ),
            "consent_ttl_exceeds_limit",
        ),
    ],
)
def test_action_admission_enforces_conservative_ttl_limits(
    proposal, envelope, reason: str
) -> None:
    result = admit_conversation_action(
        proposal,
        _authenticated(envelope),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert result.reason == reason


def test_admission_expiry_is_capped_by_current_consent_and_envelope_evidence() -> None:
    consent = _scopes(
        stationary_expression=_consent(expires=NOW + 50),
    )
    result = admit_conversation_action(
        _proposal(),
        _authenticated(_envelope(consent=consent, expires=NOW + 500)),
        embodiment_authenticator=EMBODIMENT_AUTH,
        capability_manifest=CAPABILITY_MANIFEST,
        action_bindings=_bindings(),
        current_source_epoch=4,
        now_monotonic_ns=NOW,
    )
    assert result.admitted
    assert result.expires_monotonic_ns == NOW + 50


def test_action_begin_atomically_rechecks_revocation_and_source_evidence() -> None:
    admission = _admission()
    revoked = _envelope(
        consent=_scopes(stationary_expression=_consent("revoked")),
    )
    state = DialogueStateV1.empty(
        session_id="session-revoked",
        now_monotonic_ns=NOW,
    )
    with pytest.raises(ValueError, match="consent_not_granted"):
        _begin(state, admission, now=NOW + 1, envelope=revoked)
    assert state.pending_action is None


def test_action_begin_revalidates_commissioning_lifecycle_without_mutation() -> None:
    admission = _admission()
    state = DialogueStateV1.empty(
        session_id="session-commissioning",
        now_monotonic_ns=NOW,
    )
    revoked = CommissioningCurrentStateV1(1, "nonce", frozenset({"rev"}))

    with pytest.raises(ValueError, match="state provider is missing"):
        _begin(state, admission, now=NOW + 1, commissioning_state_provider=None)
    with pytest.raises(ValueError, match="record is revoked"):
        _begin(
            state,
            admission,
            now=NOW + 1,
            commissioning_state_provider=lambda _lifecycle: revoked,
        )
    with pytest.raises(ValueError, match="not currently valid"):
        _begin(
            state,
            admission,
            now=LIFECYCLE.expires_monotonic_ns,
        )
    assert state.pending_action is None


def test_action_begin_uses_recheck_time_and_cannot_regress_state_clock() -> None:
    admission = _admission()
    newer_state = DialogueStateV1.empty(
        session_id="session-newer",
        now_monotonic_ns=NOW + 5,
    )
    begun = _begin(newer_state, admission, now=NOW + 10)
    assert begun.updated_at_monotonic_ns == NOW + 10
    assert begun.pending_action is not None
    assert begun.pending_action.admitted_at_monotonic_ns == NOW + 10

    with pytest.raises(ValueError, match="regress dialogue state time"):
        _begin(newer_state, admission, now=NOW + 4)


def test_receipt_id_is_content_derived_but_not_treated_as_authentication() -> None:
    admission = _admission()
    receipt = _receipt(admission, "started", 1, issued=NOW + 10)
    assert ActionReceiptV1.from_mapping(receipt.as_dict()) == receipt.receipt
    tampered = receipt.as_dict()
    tampered["status"] = "succeeded"
    with pytest.raises(ValueError, match="does not match"):
        ActionReceiptV1.from_mapping(tampered)


def test_untrusted_serialized_or_wrong_channel_receipt_cannot_enter_state() -> None:
    admission = _admission()
    initial = _begin(
        DialogueStateV1.empty(session_id="session-1", now_monotonic_ns=NOW - 100),
        admission,
        now=NOW,
    )
    trusted = _receipt(admission, "started", 1, issued=NOW + 10)
    parsed = ActionReceiptV1.from_mapping(trusted.as_dict())
    raw_result = apply_action_receipt(  # type: ignore[arg-type]
        initial,
        parsed,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 10,
    )
    assert raw_result.reason == "receipt_authentication_failed"
    assert raw_result.state == initial

    other_channel = TrustedReceiptAuthenticatorV1(
        authenticator_id="other_executive_channel",
        key=b"different-test-receipt-key-material",
    )
    wrong_result = apply_action_receipt(
        initial,
        trusted,
        receipt_authenticator=other_channel,
        now_monotonic_ns=NOW + 10,
    )
    assert wrong_result.reason == "receipt_authentication_failed"


def test_receipt_and_terminal_claim_ttl_limits_fail_closed() -> None:
    admission, started_state, _ = _started_state()
    long_lived = AUTH.authenticate(
        ActionReceiptV1.mint(
            mission_id=admission.mission_id,
            action_id=admission.action_id,
            action_name=admission.action_name,
            manifest_digest=admission.manifest_digest,
            status="succeeded",
            sequence=2,
            issued_at_monotonic_ns=NOW + 20,
            claimable_until_monotonic_ns=NOW + 31_000_000_021,
        )
    )
    refused = apply_action_receipt(
        started_state,
        long_lived,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 20,
    )
    assert refused.reason == "receipt_ttl_exceeds_limit"

    terminal = _receipt(admission, "succeeded", 2, issued=NOW + 20)
    state = apply_action_receipt(
        started_state,
        terminal,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 20,
    ).state
    stale_claim = replace(
        _claim(terminal), proposed_at_monotonic_ns=NOW + 21
    )
    license_result = license_terminal_claim(
        stale_claim,
        state,
        authenticated_receipt=terminal,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 5_000_000_022,
    )
    assert license_result.reason == "claim_proposal_ttl_exceeds_limit"


def test_expired_authenticated_start_and_terminal_receipts_do_not_mutate_state() -> None:
    admission = _admission()
    initial = _begin(
        DialogueStateV1.empty(session_id="session-1", now_monotonic_ns=NOW - 100),
        admission,
        now=NOW,
    )
    expired_start = _receipt(admission, "started", 1, issued=NOW + 10)
    rejected_start = apply_action_receipt(
        initial,
        expired_start,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 2_000_000_000,
    )
    assert rejected_start.reason == "receipt_expired"
    assert rejected_start.state == initial

    _, started, _ = _started_state()
    expired_terminal = _receipt(admission, "succeeded", 2, issued=NOW + 20)
    rejected_terminal = apply_action_receipt(
        started,
        expired_terminal,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 2_000_000_000,
    )
    assert rejected_terminal.reason == "receipt_expired"
    assert rejected_terminal.state == started


def test_success_requires_start_and_unmatched_receipts_never_become_state_facts() -> None:
    admission = _admission()
    initial = _begin(
        DialogueStateV1.empty(session_id="session-1", now_monotonic_ns=NOW - 100),
        admission,
        now=NOW,
    )
    premature = _receipt(admission, "succeeded", 1, issued=NOW + 10)
    rejected = apply_action_receipt(
        initial, premature, receipt_authenticator=AUTH, now_monotonic_ns=NOW + 10
    )
    assert not rejected.accepted
    assert rejected.reason == "invalid_receipt_transition"
    assert rejected.state.action_receipts == ()

    other = _admission("follow_owner")
    mismatch = _receipt(other, "started", 1, issued=NOW + 10)
    rejected = apply_action_receipt(
        initial, mismatch, receipt_authenticator=AUTH, now_monotonic_ns=NOW + 10
    )
    assert not rejected.accepted
    assert rejected.reason == "receipt_action_mismatch"
    assert rejected.state == initial


def test_receipt_reducer_rejects_state_and_receipt_time_regression() -> None:
    admission, started_state, _started = _started_state()
    terminal_before_start = _receipt(
        admission,
        "succeeded",
        2,
        issued=NOW + 5,
    )
    regressed_receipt = apply_action_receipt(
        started_state,
        terminal_before_start,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 20,
    )
    assert not regressed_receipt.accepted
    assert regressed_receipt.reason == "receipt_timestamp_regression"
    assert regressed_receipt.state == started_state

    valid_terminal = _receipt(admission, "succeeded", 2, issued=NOW + 20)
    regressed_reducer = apply_action_receipt(
        started_state,
        valid_terminal,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 5,
    )
    assert not regressed_reducer.accepted
    assert regressed_reducer.reason == "receipt_reduction_time_regression"
    assert regressed_reducer.state == started_state


def test_matching_terminal_receipt_is_the_only_completion_license() -> None:
    admission, started_state, started = _started_state()
    before_terminal = TerminalClaimProposalV1(
        claim_id="claim-1",
        mission_id=started.mission_id,
        action_id=started.action_id,
        action_name=started.action_name,
        manifest_digest=started.manifest_digest,
        terminal_receipt_id=started.receipt_id,
        claimed_status="succeeded",
        proposed_at_monotonic_ns=NOW + 11,
    )
    refused = license_terminal_claim(
        before_terminal,
        started_state,
        authenticated_receipt=started,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 11,
    )
    assert not refused.licensed
    assert refused.reason == "receipt_not_terminal"

    terminal = _receipt(admission, "succeeded", 2, issued=NOW + 20)
    reduced = apply_action_receipt(
        started_state, terminal, receipt_authenticator=AUTH, now_monotonic_ns=NOW + 20
    )
    assert reduced.accepted and reduced.state.pending_action is None
    licensed = license_terminal_claim(
        _claim(terminal),
        reduced.state,
        authenticated_receipt=terminal,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 22,
    )
    assert licensed.licensed
    verified = licensed.as_dialogue_claim()
    assert verified.veracity == "verified"
    assert verified.evidence_ref == terminal.receipt_id
    assert DialogueStateV1.from_mapping(reduced.state.as_dict()) == reduced.state


def test_completed_admission_cannot_be_replayed_into_pending_state() -> None:
    admission, state, _ = _started_state()
    terminal = _receipt(admission, "succeeded", 2, issued=NOW + 20)
    completed = apply_action_receipt(
        state,
        terminal,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 20,
    ).state
    assert completed.pending_action is None
    with pytest.raises(ValueError, match="consumed action or mission"):
        _begin(completed, admission, now=NOW + 21)


def test_admission_expiry_and_consumed_ledger_survive_receipt_eviction() -> None:
    admission, state, _ = _started_state()
    empty = DialogueStateV1.empty(session_id="fresh-session", now_monotonic_ns=NOW)
    with pytest.raises(ValueError, match="stale or from the future"):
        _begin(
            empty,
            admission,
            now=admission.expires_monotonic_ns,
        )

    terminal = _receipt(admission, "succeeded", 2, issued=NOW + 20)
    completed = apply_action_receipt(
        state,
        terminal,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 20,
    ).state
    evicted = replace(
        completed,
        last_completed_action=None,
        action_receipts=(),
    )
    restored = DialogueStateV1.from_mapping(evicted.as_dict())
    assert restored.consumed_actions == completed.consumed_actions
    with pytest.raises(ValueError, match="consumed action or mission"):
        _begin(restored, admission, now=NOW + 21)


@pytest.mark.parametrize("field", ["mission_id", "action_id", "manifest_digest"])
def test_terminal_claim_requires_mission_action_and_manifest_match(field: str) -> None:
    admission, state, _ = _started_state()
    terminal = _receipt(admission, "succeeded", 2, issued=NOW + 20)
    state = apply_action_receipt(
        state, terminal, receipt_authenticator=AUTH, now_monotonic_ns=NOW + 20
    ).state
    claim = _claim(terminal)
    if field == "manifest_digest":
        claim = replace(claim, manifest_digest="b" * 64)
    elif field == "mission_id":
        claim = replace(claim, mission_id="mission-" + "b" * 24)
    else:
        claim = replace(claim, action_id="action-" + "b" * 24)
    result = license_terminal_claim(
        claim,
        state,
        authenticated_receipt=terminal,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 22,
    )
    assert not result.licensed
    assert result.reason == "terminal_receipt_identity_mismatch"


def test_stale_terminal_receipt_cannot_license_a_new_claim() -> None:
    admission, state, _ = _started_state()
    terminal = ActionReceiptV1.mint(
        mission_id=admission.mission_id,
        action_id=admission.action_id,
        action_name=admission.action_name,
        manifest_digest=admission.manifest_digest,
        status="succeeded",
        sequence=2,
        issued_at_monotonic_ns=NOW + 20,
        claimable_until_monotonic_ns=NOW + 30,
    )
    terminal = AUTH.authenticate(terminal)
    state = apply_action_receipt(
        state, terminal, receipt_authenticator=AUTH, now_monotonic_ns=NOW + 20
    ).state
    claim = replace(_claim(terminal), proposed_at_monotonic_ns=NOW + 29)
    result = license_terminal_claim(
        claim,
        state,
        authenticated_receipt=terminal,
        receipt_authenticator=AUTH,
        now_monotonic_ns=NOW + 31,
    )
    assert not result.licensed
    assert result.reason == "terminal_receipt_stale_or_future"


def test_again_resolves_only_from_a_matching_success_receipt() -> None:
    admission, state, _ = _started_state()
    assert resolve_repeat_action(state).decision == "defer"
    terminal = _receipt(admission, "succeeded", 2, issued=NOW + 20)
    state = apply_action_receipt(
        state, terminal, receipt_authenticator=AUTH, now_monotonic_ns=NOW + 20
    ).state
    repeated = resolve_repeat_action(
        state, authenticated_receipt=terminal, receipt_authenticator=AUTH
    )
    assert repeated.decision == "repeat"
    assert repeated.action_name == "chuckle"


def test_memory_answers_require_owner_source_live_consent_and_latest_record() -> None:
    old = DialogueMemoryRecordV1(
        record_id="memory-old",
        key="favorite-walk",
        value="the lake",
        source="owner",
        source_session_id="session-1",
        source_turn_id="turn-1",
        observed_at_monotonic_ns=100,
        valid_from_monotonic_ns=100,
        valid_until_monotonic_ns=None,
        consent=_consent(evidence="memory-consent-old"),
        revoked_at_monotonic_ns=None,
        supersedes_record_id=None,
    )
    current = replace(
        old,
        record_id="memory-current",
        value="the river",
        source_turn_id="turn-2",
        observed_at_monotonic_ns=200,
        valid_from_monotonic_ns=200,
        supersedes_record_id="memory-old",
        consent=_consent(evidence="memory-consent-current"),
    )
    inferred = replace(
        old,
        record_id="memory-inferred",
        value="the park",
        source="inferred",
        source_turn_id="turn-3",
        observed_at_monotonic_ns=300,
        valid_from_monotonic_ns=300,
        consent=_consent(evidence="memory-consent-inferred"),
    )
    state = replace(
        DialogueStateV1.empty(session_id="session-1", now_monotonic_ns=NOW),
        memory_records=(old, current, inferred),
        retrieval=RetrievalStateV1(
            query_id="query-1",
            result_ids=("memory-old", "memory-current", "memory-inferred"),
            no_match=False,
            retrieved_at_monotonic_ns=NOW,
        ),
    )
    answers = retrieval_answers(state, principal_id="owner-1", now_monotonic_ns=NOW)
    assert tuple(item.record_id for item in answers) == ("memory-current",)

    revoked = replace(
        current,
        consent=_consent("revoked", evidence="memory-revoked"),
        revoked_at_monotonic_ns=NOW - 1,
    )
    state = replace(state, memory_records=(old, revoked, inferred))
    assert retrieval_answers(state, principal_id="owner-1", now_monotonic_ns=NOW) == ()


def test_opportunity_is_default_off_and_admission_never_authorizes_motion() -> None:
    candidate = _opportunity()
    default = admit_opportunity(
        candidate,
        now_monotonic_ns=NOW,
        current_source_epoch=4,
    )
    assert default.decision == "drop"
    assert default.reason == "proactive_feature_disabled"

    admitted = admit_opportunity(
        candidate,
        now_monotonic_ns=NOW,
        current_source_epoch=4,
        feature_enabled=True,
    )
    assert admitted.admitted_for_phrasing
    assert not admitted.authorizes_motion and not admitted.authorizes_speech
    assert not candidate.authorizes_speech and not candidate.authorizes_motion


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"privacy_state": "private"}, "privacy_not_public"),
        ({"quiet_state": "quiet"}, "quiet_state_blocks"),
        ({"owner_speaking": True}, "owner_speaking"),
        ({"tts_active": True}, "output_lane_busy"),
        ({"novelty": 0.1}, "low_novelty"),
        ({"proactive_consent": _consent("denied")}, "proactive_consent_not_granted"),
    ],
)
def test_opportunity_local_gates_dominate_hosted_phrasing(change, reason: str) -> None:
    result = admit_opportunity(
        _opportunity(**change),
        now_monotonic_ns=NOW,
        current_source_epoch=4,
        feature_enabled=True,
    )
    assert result.decision == "drop"
    assert result.reason == reason


def test_raw_opportunity_boundary_returns_drop_invalid_for_malformed_frames() -> None:
    valid = _opportunity().as_dict()
    for mutation in (
        {**valid, "unknown_permission": True},
        {**valid, "owner_speaking": "false"},
        {**valid, "novelty": float("nan")},
        {**valid, "schema_version": 2},
        {**valid, "source_epoch": True},
    ):
        result = admit_opportunity_mapping(
            mutation,
            now_monotonic_ns=NOW,
            current_source_epoch=4,
            feature_enabled=True,
        )
        assert result.decision == "drop_invalid"
        assert result.reason == "invalid_opportunity_candidate"

    mixed_epoch = _opportunity().as_dict()
    mixed_epoch["owner"] = {**mixed_epoch["owner"], "source_epoch": 5}
    assert (
        admit_opportunity_mapping(
            mixed_epoch,
            now_monotonic_ns=NOW,
            current_source_epoch=4,
            feature_enabled=True,
        ).decision
        == "drop_invalid"
    )
