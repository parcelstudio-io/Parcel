"""Local admission and receipt reducer for embodied conversation.

This module is intentionally stdlib-pure and has no robot adapter.  Its most
important negative guarantees are executable:

* a model proposal always reports ``authorizes_actuation == False``;
* an admission only means "eligible to submit to the executive";
* consent is selected from a trusted action-name binding, never a model label;
* unmatched, stale, or unauthenticated receipts do not mutate dialogue state; and
* a physical outcome claim is licensed only by a retained, fresh, exact-match
  terminal receipt authenticated by the local executive channel.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from parcel_robot.capabilities.commissioning_lifecycle import (
    CommissioningStateProviderV1,
    validate_commissioning_lifecycle,
)
from parcel_robot.capabilities.manifest import (
    CapabilityManifestV1,
    TrustedCommissioningAuthenticatorV1,
)
from parcel_robot.contracts.companion_v1 import (
    SCHEMA_VERSION,
    ActionReceiptV1,
    ConversationActionAdmissionV1,
    ConversationActionProposalV1,
    EmbodimentEnvelopeV1,
    _boolean,
    _derived_identifier,
    _enum,
    _identifier,
    _integer,
    _real,
    derive_action_id,
    derive_mission_id,
)
from parcel_robot.contracts.dialogue_state_v1 import (
    CompletedActionV1,
    ConsumedActionV1,
    DialogueMemoryRecordV1,
    DialogueStateV1,
    PendingActionV1,
)
from parcel_robot.contracts.terminal_claim_v1 import TerminalClaimProposalV1
from parcel_robot.contracts.v1 import DialogueClaimV1

from .action_bindings import (
    MOVEMENT_SCOPES,
    PHYSICAL_SCOPES,
    ActionBindingRegistryV1,
    ActionScopeBindingV1,
    manifest_binding_reason,
)
from .companion_auth import (
    AuthenticatedActionReceiptV1,
    AuthenticatedEmbodimentEnvelopeV1,
    AuthenticatedOperatorEvidenceV1,
    TrustedEmbodimentAuthenticatorV1,
    TrustedOperatorAuthenticatorV1,
    TrustedReceiptAuthenticatorV1,
)
from .companion_opportunity import (
    OpportunityAdmissionV1,
    admit_opportunity,
    admit_opportunity_mapping,
)

MAX_PROPOSAL_TTL_NS = 5_000_000_000
MAX_ENVELOPE_TTL_NS = 2_000_000_000
MAX_OWNER_EVIDENCE_TTL_NS = 10_000_000_000
MAX_CONSENT_TTL_NS = 60_000_000_000
MAX_RECEIPT_CLAIM_TTL_NS = 30_000_000_000
MAX_TERMINAL_CLAIM_AGE_NS = 5_000_000_000


def _action_verdict(
    proposal: ConversationActionProposalV1,
    binding: ActionScopeBindingV1 | None,
    *,
    now_monotonic_ns: int,
    decision: str,
    reason: str,
    expires_monotonic_ns: int | None = None,
) -> ConversationActionAdmissionV1:
    scope = "not_applicable" if binding is None else binding.consent_scope
    mission_id: str | None = None
    action_id: str | None = None
    if decision == "admit_to_executive":
        mission_id = derive_mission_id(
            turn_id=proposal.turn_id,
            proposal_id=proposal.proposal_id,
            manifest_digest=proposal.manifest_digest,
        )
        action_id = derive_action_id(
            mission_id=mission_id,
            proposal_id=proposal.proposal_id,
            action_name=proposal.action_name,
        )
    return ConversationActionAdmissionV1(
        proposal_id=proposal.proposal_id,
        turn_id=proposal.turn_id,
        decision=decision,
        reason=reason,
        evaluated_at_monotonic_ns=now_monotonic_ns,
        expires_monotonic_ns=(
            proposal.expires_monotonic_ns
            if expires_monotonic_ns is None
            else expires_monotonic_ns
        ),
        manifest_digest=proposal.manifest_digest,
        action_name=proposal.action_name,
        consent_scope=scope,
        mission_id=mission_id,
        action_id=action_id,
        repeatable=bool(binding is not None and binding.repeatable),
    )


def _capability_bridge_reason(
    proposal: ConversationActionProposalV1,
    envelope: EmbodimentEnvelopeV1,
    manifest: CapabilityManifestV1,
) -> str | None:
    if proposal.manifest_digest != manifest.manifest_digest:
        return "proposal_manifest_not_trusted"
    if envelope.manifest_digest != manifest.manifest_digest:
        return "envelope_manifest_not_trusted"
    if envelope.commissioned_actions != manifest.commissioned_action_names():
        return "commissioned_action_set_not_trusted"
    if proposal.action_name not in manifest.commissioned_action_names():
        return "action_not_commissioned"
    return None


def _lifetime_exceeds(start: int, end: int, maximum: int) -> bool:
    return end - start > maximum


def _admission_ttl_reason(
    proposal: ConversationActionProposalV1,
    envelope: EmbodimentEnvelopeV1,
    binding: ActionScopeBindingV1 | None,
) -> str | None:
    if _lifetime_exceeds(
        proposal.created_at_monotonic_ns,
        proposal.expires_monotonic_ns,
        MAX_PROPOSAL_TTL_NS,
    ):
        return "proposal_ttl_exceeds_limit"
    if _lifetime_exceeds(
        envelope.snapshot_monotonic_ns,
        envelope.expires_monotonic_ns,
        MAX_ENVELOPE_TTL_NS,
    ):
        return "envelope_ttl_exceeds_limit"
    if _lifetime_exceeds(
        envelope.owner.received_monotonic_ns,
        envelope.owner.expires_monotonic_ns,
        MAX_OWNER_EVIDENCE_TTL_NS,
    ):
        return "owner_evidence_ttl_exceeds_limit"
    if envelope.operator is not None and _lifetime_exceeds(
        envelope.operator.received_monotonic_ns,
        envelope.operator.expires_monotonic_ns,
        MAX_OWNER_EVIDENCE_TTL_NS,
    ):
        return "operator_evidence_ttl_exceeds_limit"
    if binding is None:
        return None
    consent = envelope.consent.for_scope(binding.consent_scope)
    if (
        consent.decided_at_monotonic_ns is not None
        and consent.expires_at_monotonic_ns is not None
        and _lifetime_exceeds(
            consent.decided_at_monotonic_ns,
            consent.expires_at_monotonic_ns,
            MAX_CONSENT_TTL_NS,
        )
    ):
        return "consent_ttl_exceeds_limit"
    return None


def _operator_evidence_reason(
    proposal: ConversationActionProposalV1,
    envelope: EmbodimentEnvelopeV1,
    *,
    authenticated_operator: AuthenticatedOperatorEvidenceV1 | None,
    operator_authenticator: TrustedOperatorAuthenticatorV1 | None,
    now_monotonic_ns: int,
    minimum_confidence: float,
) -> str | None:
    if proposal.initiator != "operator":
        return None
    if (
        operator_authenticator is None
        or authenticated_operator is None
        or not operator_authenticator.verify(authenticated_operator)
        or envelope.operator != authenticated_operator.evidence
    ):
        return "operator_evidence_not_authenticated"
    operator = authenticated_operator.evidence
    if (
        not operator.fresh_and_verified(
            now_monotonic_ns, minimum_confidence=minimum_confidence
        )
        or proposal.requested_by_principal_id != operator.principal_id
    ):
        return "operator_evidence_unverified_or_stale"
    return None


def _physical_gate(
    binding: ActionScopeBindingV1,
    envelope: EmbodimentEnvelopeV1,
    *,
    now_monotonic_ns: int,
    minimum_confidence: float,
) -> tuple[str, str] | None:
    if binding.requires_verified_owner and not envelope.owner.fresh_and_verified(
        now_monotonic_ns, minimum_confidence=minimum_confidence
    ):
        return "reject", "owner_evidence_unverified_or_stale"
    consent = envelope.consent.for_scope(binding.consent_scope)
    if not consent.granted_at(
        now_monotonic_ns, principal_id=envelope.owner.principal_id
    ):
        return "reject", f"consent_not_granted:{binding.consent_scope}"
    if binding.consent_scope in PHYSICAL_SCOPES and envelope.estop_state != "clear":
        return "reject", "estop_not_clear"
    if envelope.body_mode == "fault":
        return "reject", "body_fault"
    if binding.requires_locomotion and (
        not envelope.locomotion_commissioned or not envelope.locomotion_healthy
    ):
        return "reject", "locomotion_unavailable"
    if binding.requires_clear_space and (
        envelope.affordance_state != "ready" or envelope.space_state != "clear"
    ):
        return "reject", "affordance_or_space_not_clear"
    if binding.requires_idle_body and envelope.body_mode not in {"idle", "stationary"}:
        return "defer", "body_busy"
    if binding.requires_idle_body and (envelope.pending_action_id or envelope.busy_reason):
        return "defer", "action_pending_or_busy"
    return None


def _trusted_policy_integrity_reason(
    capability_manifest: CapabilityManifestV1,
    action_bindings: ActionBindingRegistryV1,
) -> str | None:
    try:
        action_bindings.assert_canonical_integrity()
    except (AttributeError, TypeError, ValueError):
        return "action_binding_registry_integrity_failed"
    try:
        capability_manifest.assert_canonical_integrity()
    except (AttributeError, TypeError, ValueError):
        return "capability_manifest_integrity_failed"
    return None


def _admission_evidence_expiry(
    proposal: ConversationActionProposalV1,
    envelope: EmbodimentEnvelopeV1,
    binding: ActionScopeBindingV1,
) -> int:
    consent_expiry = envelope.consent.for_scope(binding.consent_scope).expires_at_monotonic_ns
    assert consent_expiry is not None
    expiries = [
        proposal.expires_monotonic_ns,
        envelope.expires_monotonic_ns,
        envelope.owner.expires_monotonic_ns,
        consent_expiry,
    ]
    if envelope.initiator == "operator":
        assert envelope.operator is not None
        expiries.append(envelope.operator.expires_monotonic_ns)
    return min(expiries)


def _validated_admission_inputs(
    proposal: ConversationActionProposalV1,
    authenticated_envelope: AuthenticatedEmbodimentEnvelopeV1,
    embodiment_authenticator: TrustedEmbodimentAuthenticatorV1,
    capability_manifest: CapabilityManifestV1,
    action_bindings: ActionBindingRegistryV1,
    current_source_epoch: int,
    now_monotonic_ns: int,
    minimum_owner_confidence: float,
) -> tuple[EmbodimentEnvelopeV1, int, int, float]:
    if not isinstance(proposal, ConversationActionProposalV1):
        raise TypeError("proposal must be ConversationActionProposalV1")
    if not isinstance(authenticated_envelope, AuthenticatedEmbodimentEnvelopeV1):
        raise TypeError("authenticated_envelope must be AuthenticatedEmbodimentEnvelopeV1")
    if not isinstance(embodiment_authenticator, TrustedEmbodimentAuthenticatorV1):
        raise TypeError("embodiment_authenticator must be TrustedEmbodimentAuthenticatorV1")
    if not isinstance(capability_manifest, CapabilityManifestV1):
        raise TypeError("capability_manifest must be CapabilityManifestV1")
    if not isinstance(action_bindings, ActionBindingRegistryV1):
        raise TypeError("action_bindings must be ActionBindingRegistryV1")
    return (
        authenticated_envelope.envelope,
        _integer(current_source_epoch, "current_source_epoch"),
        _integer(now_monotonic_ns, "now_monotonic_ns"),
        _real(
            minimum_owner_confidence,
            "minimum_owner_confidence",
            minimum=0.0,
            maximum=1.0,
        ),
    )


def _bound_action_gate(
    proposal: ConversationActionProposalV1,
    envelope: EmbodimentEnvelopeV1,
    binding: ActionScopeBindingV1,
    capability_manifest: CapabilityManifestV1,
    *,
    authenticated_operator: AuthenticatedOperatorEvidenceV1 | None,
    operator_authenticator: TrustedOperatorAuthenticatorV1 | None,
    now_monotonic_ns: int,
    minimum_owner_confidence: float,
) -> tuple[str, str] | None:
    reason = manifest_binding_reason(capability_manifest, proposal.action_name, binding)
    if reason is not None:
        return "reject", reason
    if proposal.initiator not in binding.allowed_initiators:
        return "reject", "initiator_not_allowed"
    if proposal.initiator == "system" and binding.consent_scope in MOVEMENT_SCOPES:
        return "reject", "system_initiated_travel_forbidden"
    if proposal.initiator == "system" and binding.consent_scope == "speech":
        return "reject", "system_speech_requires_proactive_scope"
    if proposal.initiator == "owner" and (
        not proposal.requested_by_principal_id
        or proposal.requested_by_principal_id != envelope.owner.principal_id
    ):
        return "reject", "request_principal_mismatch"
    reason = _operator_evidence_reason(
        proposal,
        envelope,
        authenticated_operator=authenticated_operator,
        operator_authenticator=operator_authenticator,
        now_monotonic_ns=now_monotonic_ns,
        minimum_confidence=minimum_owner_confidence,
    )
    if reason is not None:
        return "reject", reason
    return _physical_gate(
        binding,
        envelope,
        now_monotonic_ns=now_monotonic_ns,
        minimum_confidence=minimum_owner_confidence,
    )


def admit_conversation_action(
    proposal: ConversationActionProposalV1,
    authenticated_envelope: AuthenticatedEmbodimentEnvelopeV1,
    *,
    embodiment_authenticator: TrustedEmbodimentAuthenticatorV1,
    capability_manifest: CapabilityManifestV1,
    commissioning_authenticator: TrustedCommissioningAuthenticatorV1,
    commissioning_state_provider: CommissioningStateProviderV1,
    action_bindings: ActionBindingRegistryV1,
    current_source_epoch: int,
    now_monotonic_ns: int,
    minimum_owner_confidence: float = 0.80,
    authenticated_operator: AuthenticatedOperatorEvidenceV1 | None = None,
    operator_authenticator: TrustedOperatorAuthenticatorV1 | None = None,
) -> ConversationActionAdmissionV1:
    """Evaluate a proposal without dispatching it or touching an actuator."""

    envelope, epoch, now, confidence = _validated_admission_inputs(
        proposal,
        authenticated_envelope,
        embodiment_authenticator,
        capability_manifest,
        action_bindings,
        current_source_epoch,
        now_monotonic_ns,
        minimum_owner_confidence,
    )
    capability_manifest.assert_authenticated_commissioning(
        commissioning_authenticator
    )
    validate_commissioning_lifecycle(
        capability_manifest.commissioning_lifecycle,
        state_provider=commissioning_state_provider,
        now_monotonic_ns=now,
    )
    binding: ActionScopeBindingV1 | None = None

    def verdict(
        decision: str,
        reason: str,
        *,
        expires_monotonic_ns: int | None = None,
    ) -> ConversationActionAdmissionV1:
        return _action_verdict(
            proposal,
            binding,
            now_monotonic_ns=now,
            decision=decision,
            reason=reason,
            expires_monotonic_ns=expires_monotonic_ns,
        )

    if not embodiment_authenticator.verify(authenticated_envelope):
        return verdict("reject", "embodiment_authentication_failed")
    integrity_reason = _trusted_policy_integrity_reason(
        capability_manifest, action_bindings
    )
    if integrity_reason is not None:
        return verdict("reject", integrity_reason)
    if envelope.owner.source_epoch != epoch:
        return verdict("reject", "source_epoch_mismatch")
    if envelope.action_bindings_digest != action_bindings.registry_digest:
        return verdict("reject", "action_binding_registry_digest_mismatch")
    binding = action_bindings.get(proposal.action_name)
    if now < proposal.created_at_monotonic_ns or now >= proposal.expires_monotonic_ns:
        return verdict("reject", "proposal_stale_or_future")
    if not envelope.fresh(now):
        return verdict("reject", "embodiment_envelope_stale_or_future")
    ttl_reason = _admission_ttl_reason(proposal, envelope, binding)
    if ttl_reason is not None:
        return verdict("reject", ttl_reason)
    bridge_reason = _capability_bridge_reason(proposal, envelope, capability_manifest)
    if bridge_reason is not None:
        return verdict("reject", bridge_reason)
    if proposal.initiator != envelope.initiator:
        return verdict("reject", "initiator_mismatch")
    if binding is None:
        return verdict("reject", "action_has_no_trusted_scope_binding")
    gate = _bound_action_gate(
        proposal,
        envelope,
        binding,
        capability_manifest,
        authenticated_operator=authenticated_operator,
        operator_authenticator=operator_authenticator,
        now_monotonic_ns=now,
        minimum_owner_confidence=confidence,
    )
    if gate is not None:
        return verdict(*gate)
    return verdict(
        "admit_to_executive",
        "eligible_for_local_executive_admission",
        expires_monotonic_ns=_admission_evidence_expiry(proposal, envelope, binding),
    )


def _refresh_admission_for_begin(
    admission: ConversationActionAdmissionV1,
    proposal: ConversationActionProposalV1,
    authenticated_envelope: AuthenticatedEmbodimentEnvelopeV1,
    *,
    embodiment_authenticator: TrustedEmbodimentAuthenticatorV1,
    capability_manifest: CapabilityManifestV1,
    commissioning_authenticator: TrustedCommissioningAuthenticatorV1,
    commissioning_state_provider: CommissioningStateProviderV1,
    action_bindings: ActionBindingRegistryV1,
    current_source_epoch: int,
    now_monotonic_ns: int,
    minimum_owner_confidence: float,
    authenticated_operator: AuthenticatedOperatorEvidenceV1 | None,
    operator_authenticator: TrustedOperatorAuthenticatorV1 | None,
) -> ConversationActionAdmissionV1:
    current = admit_conversation_action(
        proposal,
        authenticated_envelope,
        embodiment_authenticator=embodiment_authenticator,
        capability_manifest=capability_manifest,
        commissioning_authenticator=commissioning_authenticator,
        commissioning_state_provider=commissioning_state_provider,
        action_bindings=action_bindings,
        current_source_epoch=current_source_epoch,
        now_monotonic_ns=now_monotonic_ns,
        minimum_owner_confidence=minimum_owner_confidence,
        authenticated_operator=authenticated_operator,
        operator_authenticator=operator_authenticator,
    )
    if not current.admitted:
        raise ValueError(f"current action admission rejected: {current.reason}")
    stable_fields = (
        "proposal_id",
        "turn_id",
        "manifest_digest",
        "action_name",
        "consent_scope",
        "mission_id",
        "action_id",
        "repeatable",
    )
    if any(getattr(admission, name) != getattr(current, name) for name in stable_fields):
        raise ValueError("current action admission does not match prior eligibility")
    return current


def begin_admitted_action(
    state: DialogueStateV1,
    admission: ConversationActionAdmissionV1,
    *,
    proposal: ConversationActionProposalV1,
    authenticated_envelope: AuthenticatedEmbodimentEnvelopeV1,
    embodiment_authenticator: TrustedEmbodimentAuthenticatorV1,
    capability_manifest: CapabilityManifestV1,
    commissioning_authenticator: TrustedCommissioningAuthenticatorV1,
    commissioning_state_provider: CommissioningStateProviderV1,
    action_bindings: ActionBindingRegistryV1,
    current_source_epoch: int,
    now_monotonic_ns: int,
    minimum_owner_confidence: float = 0.80,
    authenticated_operator: AuthenticatedOperatorEvidenceV1 | None = None,
    operator_authenticator: TrustedOperatorAuthenticatorV1 | None = None,
) -> DialogueStateV1:
    """Atomically re-admit current evidence before recording pending work."""

    if not isinstance(state, DialogueStateV1):
        raise TypeError("state must be DialogueStateV1")
    if not isinstance(admission, ConversationActionAdmissionV1):
        raise TypeError("admission must be ConversationActionAdmissionV1")
    now = _integer(now_monotonic_ns, "now_monotonic_ns")
    if not admission.admitted:
        raise ValueError("only an admitted proposal can become pending")
    if not admission.evaluated_at_monotonic_ns <= now < admission.expires_monotonic_ns:
        raise ValueError("action admission is stale or from the future")
    admission = _refresh_admission_for_begin(
        admission,
        proposal,
        authenticated_envelope,
        embodiment_authenticator=embodiment_authenticator,
        capability_manifest=capability_manifest,
        commissioning_authenticator=commissioning_authenticator,
        commissioning_state_provider=commissioning_state_provider,
        action_bindings=action_bindings,
        current_source_epoch=current_source_epoch,
        now_monotonic_ns=now,
        minimum_owner_confidence=minimum_owner_confidence,
        authenticated_operator=authenticated_operator,
        operator_authenticator=operator_authenticator,
    )
    if now < state.updated_at_monotonic_ns:
        raise ValueError("action begin would regress dialogue state time")
    if state.pending_action is not None:
        raise ValueError("dialogue state already has a pending action")
    assert admission.mission_id is not None
    assert admission.action_id is not None
    consumed_replay = any(
        item.action_id == admission.action_id or item.mission_id == admission.mission_id
        for item in state.consumed_actions
    )
    if consumed_replay:
        raise ValueError("admission replays a consumed action or mission")
    if len(state.consumed_actions) >= 64:
        raise ValueError("consumed-action ledger is full; start a new dialogue session")
    replayed = any(
        item.action_id == admission.action_id or item.mission_id == admission.mission_id
        for item in state.action_receipts
    )
    completed = state.last_completed_action
    if replayed or (
        completed is not None
        and (
            completed.action_id == admission.action_id
            or completed.mission_id == admission.mission_id
        )
    ):
        raise ValueError("admission replays a previously observed action or mission")
    pending = PendingActionV1(
        mission_id=admission.mission_id,
        action_id=admission.action_id,
        proposal_id=admission.proposal_id,
        turn_id=admission.turn_id,
        action_name=admission.action_name,
        manifest_digest=admission.manifest_digest,
        consent_scope=admission.consent_scope,
        repeatable=admission.repeatable,
        state="admitted",
        admitted_at_monotonic_ns=now,
    )
    return replace(
        state,
        revision=state.revision + 1,
        updated_at_monotonic_ns=now,
        pending_action=pending,
        consumed_actions=(
            *state.consumed_actions,
            ConsumedActionV1(
                mission_id=admission.mission_id,
                action_id=admission.action_id,
                expires_monotonic_ns=admission.expires_monotonic_ns,
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class ReceiptReductionV1:
    state: DialogueStateV1
    accepted: bool
    disposition: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, DialogueStateV1):
            raise TypeError("receipt reduction state must be DialogueStateV1")
        _boolean(self.accepted, "receipt reduction accepted")
        _identifier(self.disposition, "receipt reduction disposition")
        _identifier(self.reason, "receipt reduction reason")


def apply_action_receipt(
    state: DialogueStateV1,
    authenticated_receipt: AuthenticatedActionReceiptV1,
    *,
    receipt_authenticator: TrustedReceiptAuthenticatorV1,
    now_monotonic_ns: int,
) -> ReceiptReductionV1:
    """Reduce one authenticated local receipt; raw parsed receipts are refused."""

    if not isinstance(state, DialogueStateV1):
        raise TypeError("state must be DialogueStateV1")
    if not isinstance(receipt_authenticator, TrustedReceiptAuthenticatorV1):
        raise TypeError("receipt_authenticator must be TrustedReceiptAuthenticatorV1")
    if not receipt_authenticator.verify(authenticated_receipt):
        return ReceiptReductionV1(state, False, "ignored", "receipt_authentication_failed")
    receipt = authenticated_receipt.receipt
    now = _integer(now_monotonic_ns, "now_monotonic_ns")
    if now < state.updated_at_monotonic_ns:
        return ReceiptReductionV1(
            state, False, "ignored", "receipt_reduction_time_regression"
        )
    if _lifetime_exceeds(
        receipt.issued_at_monotonic_ns,
        receipt.claimable_until_monotonic_ns,
        MAX_RECEIPT_CLAIM_TTL_NS,
    ):
        return ReceiptReductionV1(state, False, "ignored", "receipt_ttl_exceeds_limit")
    if receipt.issued_at_monotonic_ns > now:
        return ReceiptReductionV1(state, False, "ignored", "receipt_from_future")
    if now >= receipt.claimable_until_monotonic_ns:
        return ReceiptReductionV1(state, False, "ignored", "receipt_expired")
    if state.receipt(receipt.receipt_id) is not None:
        return ReceiptReductionV1(state, False, "duplicate", "receipt_already_recorded")
    pending = state.pending_action
    if pending is None:
        return ReceiptReductionV1(state, False, "ignored", "no_pending_action")
    if not _receipt_matches_pending(receipt, pending):
        return ReceiptReductionV1(state, False, "ignored", "receipt_action_mismatch")
    if receipt.issued_at_monotonic_ns < pending.admitted_at_monotonic_ns:
        return ReceiptReductionV1(state, False, "ignored", "receipt_predates_admission")
    prior = tuple(
        item
        for item in state.action_receipts
        if item.mission_id == receipt.mission_id and item.action_id == receipt.action_id
    )
    prior_issued_at = max(
        (item.issued_at_monotonic_ns for item in prior),
        default=pending.admitted_at_monotonic_ns,
    )
    if receipt.issued_at_monotonic_ns < prior_issued_at:
        return ReceiptReductionV1(
            state, False, "ignored", "receipt_timestamp_regression"
        )
    if prior and receipt.sequence <= max(item.sequence for item in prior):
        return ReceiptReductionV1(state, False, "ignored", "receipt_sequence_regression")
    last_status = max(prior, key=lambda item: item.sequence).status if prior else ""
    if not _valid_receipt_transition(last_status, receipt.status):
        return ReceiptReductionV1(state, False, "ignored", "invalid_receipt_transition")

    receipts = _append_receipt(state, receipt)
    next_pending: PendingActionV1 | None = pending
    last_completed = state.last_completed_action
    if receipt.status == "started":
        next_pending = replace(
            pending,
            state="started",
            start_receipt_id=receipt.receipt_id,
            started_at_monotonic_ns=receipt.issued_at_monotonic_ns,
        )
    elif receipt.terminal:
        next_pending = None
        if receipt.status == "succeeded":
            last_completed = CompletedActionV1(
                mission_id=receipt.mission_id,
                action_id=receipt.action_id,
                action_name=receipt.action_name,
                manifest_digest=receipt.manifest_digest,
                terminal_receipt_id=receipt.receipt_id,
                completed_at_monotonic_ns=receipt.issued_at_monotonic_ns,
                repeatable=pending.repeatable,
            )
    next_state = replace(
        state,
        revision=state.revision + 1,
        updated_at_monotonic_ns=now,
        pending_action=next_pending,
        last_completed_action=last_completed,
        action_receipts=receipts,
    )
    disposition = "terminal" if receipt.terminal else receipt.status
    return ReceiptReductionV1(next_state, True, disposition, "matching_local_receipt")


def _receipt_matches_pending(receipt: ActionReceiptV1, pending: PendingActionV1) -> bool:
    return (
        receipt.mission_id == pending.mission_id
        and receipt.action_id == pending.action_id
        and receipt.action_name == pending.action_name
        and receipt.manifest_digest == pending.manifest_digest
    )


def _valid_receipt_transition(previous: str, current: str) -> bool:
    if current == "admitted":
        return not previous
    if current == "started":
        return previous in {"", "admitted"}
    if current == "rejected":
        return previous in {"", "admitted"}
    if current in {"succeeded", "failed", "cancelled"}:
        return previous == "started"
    return False


def _append_receipt(state: DialogueStateV1, receipt: ActionReceiptV1) -> tuple[ActionReceiptV1, ...]:
    receipts = (*state.action_receipts, receipt)
    if len(receipts) <= 32:
        return receipts
    protected = {
        item
        for item in (
            state.pending_action.start_receipt_id if state.pending_action else None,
            state.last_completed_action.terminal_receipt_id if state.last_completed_action else None,
            receipt.receipt_id,
        )
        if item is not None
    }
    removable = next((index for index, item in enumerate(receipts) if item.receipt_id not in protected), 0)
    return (*receipts[:removable], *receipts[removable + 1 :])


@dataclass(frozen=True, slots=True)
class TerminalClaimLicenseV1:
    claim_id: str
    licensed: bool
    reason: str
    mission_id: str
    action_id: str
    action_name: str
    verified_status: str
    evidence_ref: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.claim_id, "claim_id")
        _boolean(self.licensed, "terminal claim licensed")
        _identifier(self.reason, "terminal claim reason")
        _derived_identifier(self.mission_id, "mission_id")
        _derived_identifier(self.action_id, "action_id")
        _identifier(self.action_name, "action_name")
        if self.licensed:
            _enum(
                self.verified_status,
                frozenset({"succeeded", "failed", "cancelled", "rejected"}),
                "verified_status",
            )
            _derived_identifier(self.evidence_ref, "evidence_ref")
        elif self.verified_status or self.evidence_ref:
            raise ValueError("unlicensed terminal claim cannot carry verified evidence")

    @property
    def is_verified(self) -> bool:
        return self.licensed

    def as_dialogue_claim(self) -> DialogueClaimV1:
        """Return a deterministic fact; free-form phrasing is a later step."""

        if not self.licensed:
            raise ValueError("an unlicensed terminal proposal cannot become a verified claim")
        return DialogueClaimV1(
            text=f"action {self.action_name} {self.verified_status}",
            veracity="verified",
            evidence_ref=self.evidence_ref,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "claim_id": self.claim_id,
            "licensed": self.licensed,
            "reason": self.reason,
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "action_name": self.action_name,
            "verified_status": self.verified_status,
            "evidence_ref": self.evidence_ref,
        }


def license_terminal_claim(
    proposal: TerminalClaimProposalV1,
    state: DialogueStateV1,
    *,
    authenticated_receipt: AuthenticatedActionReceiptV1,
    receipt_authenticator: TrustedReceiptAuthenticatorV1,
    now_monotonic_ns: int,
) -> TerminalClaimLicenseV1:
    """Require an authenticated receipt plus exact retained terminal identity."""

    if not isinstance(proposal, TerminalClaimProposalV1):
        raise TypeError("proposal must be TerminalClaimProposalV1")
    if not isinstance(state, DialogueStateV1):
        raise TypeError("state must be DialogueStateV1")
    if not isinstance(receipt_authenticator, TrustedReceiptAuthenticatorV1):
        raise TypeError("receipt_authenticator must be TrustedReceiptAuthenticatorV1")
    now = _integer(now_monotonic_ns, "now_monotonic_ns")

    def result(licensed: bool, reason: str) -> TerminalClaimLicenseV1:
        return TerminalClaimLicenseV1(
            claim_id=proposal.claim_id,
            licensed=licensed,
            reason=reason,
            mission_id=proposal.mission_id,
            action_id=proposal.action_id,
            action_name=proposal.action_name,
            verified_status=proposal.claimed_status if licensed else "",
            evidence_ref=proposal.terminal_receipt_id if licensed else "",
        )

    if proposal.proposed_at_monotonic_ns > now:
        return result(False, "claim_proposal_from_future")
    if now - proposal.proposed_at_monotonic_ns > MAX_TERMINAL_CLAIM_AGE_NS:
        return result(False, "claim_proposal_ttl_exceeds_limit")
    if not receipt_authenticator.verify(authenticated_receipt):
        return result(False, "receipt_authentication_failed")
    trusted_receipt = authenticated_receipt.receipt
    if trusted_receipt.receipt_id != proposal.terminal_receipt_id:
        return result(False, "authenticated_receipt_identity_mismatch")
    receipt = state.receipt(proposal.terminal_receipt_id)
    if receipt is None:
        return result(False, "receipt_not_retained")
    if receipt != trusted_receipt:
        return result(False, "authenticated_receipt_content_mismatch")
    if (
        receipt.mission_id != proposal.mission_id
        or receipt.action_id != proposal.action_id
        or receipt.action_name != proposal.action_name
        or receipt.manifest_digest != proposal.manifest_digest
    ):
        return result(False, "terminal_receipt_identity_mismatch")
    if not receipt.terminal:
        return result(False, "receipt_not_terminal")
    if _lifetime_exceeds(
        receipt.issued_at_monotonic_ns,
        receipt.claimable_until_monotonic_ns,
        MAX_RECEIPT_CLAIM_TTL_NS,
    ):
        return result(False, "receipt_ttl_exceeds_limit")
    if receipt.status != proposal.claimed_status:
        return result(False, "terminal_status_mismatch")
    if not (
        receipt.issued_at_monotonic_ns
        <= proposal.proposed_at_monotonic_ns
        < receipt.claimable_until_monotonic_ns
        and now < receipt.claimable_until_monotonic_ns
    ):
        return result(False, "terminal_receipt_stale_or_future")
    return result(True, "matching_local_terminal_receipt")


@dataclass(frozen=True, slots=True)
class RepeatResolutionV1:
    decision: str
    action_name: str
    reason: str

    def __post_init__(self) -> None:
        _enum(self.decision, frozenset({"repeat", "defer", "clarify"}), "repeat decision")
        _identifier(self.action_name, "repeat action_name", empty=self.decision != "repeat")
        _identifier(self.reason, "repeat reason")
        if self.decision == "repeat" and not self.action_name:
            raise ValueError("repeat decision requires action_name")


def resolve_repeat_action(
    state: DialogueStateV1,
    *,
    authenticated_receipt: AuthenticatedActionReceiptV1 | None = None,
    receipt_authenticator: TrustedReceiptAuthenticatorV1 | None = None,
) -> RepeatResolutionV1:
    """Resolve “again” from completion, never from a proposal or start."""

    if state.pending_action is not None:
        return RepeatResolutionV1("defer", "", "action_still_pending")
    completed = state.last_completed_action
    if completed is None or not completed.repeatable:
        return RepeatResolutionV1("clarify", "", "no_completed_repeatable_action")
    receipt = state.receipt(completed.terminal_receipt_id)
    if receipt is None or receipt.status != "succeeded":
        return RepeatResolutionV1("clarify", "", "completion_receipt_not_retained")
    if (
        receipt_authenticator is None
        or authenticated_receipt is None
        or not receipt_authenticator.verify(authenticated_receipt)
        or authenticated_receipt.receipt != receipt
    ):
        return RepeatResolutionV1("clarify", "", "completion_receipt_not_authenticated")
    return RepeatResolutionV1("repeat", completed.action_name, "matching_success_receipt")


def retrieval_answers(
    state: DialogueStateV1,
    *,
    principal_id: str,
    now_monotonic_ns: int,
) -> tuple[DialogueMemoryRecordV1, ...]:
    """Return only retrieved, owner-sourced, live, consented, non-superseded facts."""

    _identifier(principal_id, "principal_id")
    now = _integer(now_monotonic_ns, "now_monotonic_ns")
    if state.retrieval is None or state.retrieval.no_match:
        return ()
    records = {item.record_id: item for item in state.memory_records}
    candidates = tuple(
        records[record_id]
        for record_id in state.retrieval.result_ids
        if record_id in records and records[record_id].answerable_at(now, principal_id=principal_id)
    )
    # Supersession is historical lineage, not permission.  A newer owner row
    # that is later revoked must not make the older value spring back to life.
    superseded = {
        item.supersedes_record_id
        for item in state.memory_records
        if item.source == "owner" and item.supersedes_record_id is not None
    }
    return tuple(item for item in candidates if item.record_id not in superseded)


__all__ = [
    "ActionBindingRegistryV1",
    "ActionScopeBindingV1",
    "AuthenticatedActionReceiptV1",
    "AuthenticatedEmbodimentEnvelopeV1",
    "AuthenticatedOperatorEvidenceV1",
    "OpportunityAdmissionV1",
    "ReceiptReductionV1",
    "RepeatResolutionV1",
    "TerminalClaimLicenseV1",
    "TrustedEmbodimentAuthenticatorV1",
    "TrustedOperatorAuthenticatorV1",
    "TrustedReceiptAuthenticatorV1",
    "admit_conversation_action",
    "admit_opportunity",
    "admit_opportunity_mapping",
    "apply_action_receipt",
    "begin_admitted_action",
    "license_terminal_claim",
    "resolve_repeat_action",
    "retrieval_answers",
]
