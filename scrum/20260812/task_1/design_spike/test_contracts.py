from __future__ import annotations

import dataclasses
import math
import random

import pytest
from contracts import (
    AuthorityDisposition,
    BehaviorProposalV2,
    EvidenceEnvelopeV2,
    EvidenceOrigin,
    HardwareCapabilityManifestV1,
    LeaseV1,
    MotionCandidateV2,
    OwnerTrackState,
    ProposalKind,
    RequiredEvidenceV1,
    Resource,
    SafetyVerdictV1,
    TaskTransactionV2,
    TerminalWitnessV2,
    behavior_verdict,
    candidate_verdict,
    dominant_verdict,
    join_evidence,
    owner_motion_verdict,
    terminal_verdict,
)

NOW = 100.0
REQUIRED = (
    RequiredEvidenceV1("pose", "odom", 0.25),
    RequiredEvidenceV1("geometry", "base_link", 0.20),
    RequiredEvidenceV1("feedback", "base_link", 0.20),
)


def evidence(
    stream_id: str,
    frame_id: str,
    *,
    sequence: int = 7,
    age_s: float = 0.05,
    origin: EvidenceOrigin = EvidenceOrigin.PHYSICAL,
    payload_valid: bool = True,
    source_time: float | None = 1_000_000.0,
) -> EvidenceEnvelopeV2:
    return EvidenceEnvelopeV2(
        stream_id=stream_id,
        sequence=sequence,
        origin=origin,
        received_at_monotonic_s=NOW - age_s,
        captured_at_source_s=source_time,
        frame_id=frame_id,
        calibration_epoch="cal-1",
        payload_valid=payload_valid,
        clock_uncertainty_ms=3.0,
    )


@pytest.fixture
def current() -> dict[str, EvidenceEnvelopeV2]:
    return {
        "pose": evidence("pose", "odom"),
        "geometry": evidence("geometry", "base_link"),
        "feedback": evidence("feedback", "base_link"),
    }


@pytest.fixture
def task() -> TaskTransactionV2:
    return TaskTransactionV2("task-1", 3, "turn-9", True, NOW - 1.0, NOW + 5.0)


@pytest.fixture
def capability() -> HardwareCapabilityManifestV1:
    return HardwareCapabilityManifestV1("go2-edu-serial-redacted", True, True, 0.5, 0.25, 0.8, True)


@pytest.fixture
def lease() -> LeaseV1:
    return LeaseV1("robot-gateway", 4, NOW + 0.5)


def candidate(current: dict[str, EvidenceEnvelopeV2], **changes) -> MotionCandidateV2:
    value = MotionCandidateV2(
        task_id="task-1",
        task_revision=3,
        producer="rpp-v1",
        kind=ProposalKind.DETERMINISTIC,
        sequence=11,
        issued_at_monotonic_s=NOW - 0.01,
        valid_until_monotonic_s=NOW + 0.10,
        frame_id="base_link",
        vx_mps=0.2,
        vy_mps=0.0,
        yaw_rps=0.1,
        evidence_sequences=tuple(
            (stream_id, sample.sequence) for stream_id, sample in current.items()
        ),
    )
    return dataclasses.replace(value, **changes)


def test_all_fresh_physical_evidence_passes(current):
    assert join_evidence(REQUIRED, current, now_monotonic_s=NOW).disposition is (
        AuthorityDisposition.PASS
    )


@pytest.mark.parametrize("missing", ["pose", "geometry", "feedback"])
def test_missing_authority_input_holds(current, missing):
    current.pop(missing)
    verdict = join_evidence(REQUIRED, current, now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert f"{missing}:missing" in verdict.reasons


@pytest.mark.parametrize("stale", ["pose", "geometry", "feedback"])
def test_stale_authority_input_holds(current, stale):
    current[stale] = dataclasses.replace(current[stale], received_at_monotonic_s=NOW - 2.0)
    assert join_evidence(REQUIRED, current, now_monotonic_s=NOW).disposition is (
        AuthorityDisposition.HOLD
    )


@pytest.mark.parametrize("bad", ["pose", "geometry", "feedback"])
def test_wrong_frame_latches_stop(current, bad):
    current[bad] = dataclasses.replace(current[bad], frame_id="mystery_frame")
    assert join_evidence(REQUIRED, current, now_monotonic_s=NOW).disposition is (
        AuthorityDisposition.LATCHED_STOP
    )


@pytest.mark.parametrize("origin", [EvidenceOrigin.SIMULATION, EvidenceOrigin.REPLAY])
def test_lab_evidence_cannot_authorize_physical_motion(current, origin):
    current["pose"] = dataclasses.replace(current["pose"], origin=origin)
    verdict = join_evidence(REQUIRED, current, now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP


def test_simulation_profile_must_explicitly_allow_simulation(current):
    sim_required = tuple(
        dataclasses.replace(spec, allowed_origins=frozenset({EvidenceOrigin.SIMULATION}))
        for spec in REQUIRED
    )
    sim_current = {
        name: dataclasses.replace(sample, origin=EvidenceOrigin.SIMULATION)
        for name, sample in current.items()
    }
    assert join_evidence(sim_required, sim_current, now_monotonic_s=NOW).disposition is (
        AuthorityDisposition.PASS
    )


def test_source_clock_jump_does_not_corrupt_watchdog(current):
    current["pose"] = dataclasses.replace(current["pose"], captured_at_source_s=-9_000_000_000.0)
    assert join_evidence(REQUIRED, current, now_monotonic_s=NOW).disposition is (
        AuthorityDisposition.PASS
    )


def test_unknown_string_cannot_be_smuggled_as_physical_origin():
    with pytest.raises(TypeError):
        evidence("pose", "odom", origin="unitree_sport")  # type: ignore[arg-type]


def test_dominant_safety_verdict_cannot_be_relaxed():
    verdict = dominant_verdict(
        SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("tilt",)),
        SafetyVerdictV1(AuthorityDisposition.PASS),
        SafetyVerdictV1(AuthorityDisposition.CLAMP, ("social_distance",)),
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert verdict.reasons == ("tilt",)


def test_deterministic_candidate_with_current_task_and_lease_passes(
    current, task, capability, lease
):
    verdict = candidate_verdict(
        candidate(current),
        task=task,
        capability=capability,
        lease=lease,
        expected_writer_id="robot-gateway",
        now_monotonic_s=NOW,
        current_evidence=current,
    )
    assert verdict.disposition is AuthorityDisposition.PASS


def test_learned_candidate_has_identical_admission_rules(current, task, capability, lease):
    learned = candidate(current, producer="mppi-shadow-7", kind=ProposalKind.LEARNED)
    assert (
        candidate_verdict(
            learned,
            task=task,
            capability=capability,
            lease=lease,
            expected_writer_id="robot-gateway",
            now_monotonic_s=NOW,
            current_evidence=current,
        ).disposition
        is AuthorityDisposition.PASS
    )


def test_old_plan_revision_is_discarded(current, task, capability, lease):
    old = candidate(current, task_revision=task.revision - 1)
    assert (
        candidate_verdict(
            old,
            task=task,
            capability=capability,
            lease=lease,
            expected_writer_id="robot-gateway",
            now_monotonic_s=NOW,
            current_evidence=current,
        ).disposition
        is AuthorityDisposition.HOLD
    )


def test_scene_revision_change_discards_late_model_output(current, task, capability, lease):
    late = candidate(current)
    current["geometry"] = dataclasses.replace(current["geometry"], sequence=8)
    verdict = candidate_verdict(
        late,
        task=task,
        capability=capability,
        lease=lease,
        expected_writer_id="robot-gateway",
        now_monotonic_s=NOW,
        current_evidence=current,
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "geometry:evidence_revision_changed" in verdict.reasons


def test_expired_candidate_holds(current, task, capability, lease):
    expired = candidate(current, valid_until_monotonic_s=NOW)
    assert (
        candidate_verdict(
            expired,
            task=task,
            capability=capability,
            lease=lease,
            expected_writer_id="robot-gateway",
            now_monotonic_s=NOW,
            current_evidence=current,
        ).disposition
        is AuthorityDisposition.HOLD
    )


def test_lease_loss_requires_stop(current, task, capability, lease):
    expired_lease = dataclasses.replace(lease, valid_until_monotonic_s=NOW)
    assert (
        candidate_verdict(
            candidate(current),
            task=task,
            capability=capability,
            lease=expired_lease,
            expected_writer_id="robot-gateway",
            now_monotonic_s=NOW,
            current_evidence=current,
        ).disposition
        is AuthorityDisposition.STOP
    )


def test_second_writer_latches_stop(current, task, capability, lease):
    intruder = dataclasses.replace(lease, writer_id="second-writer")
    assert (
        candidate_verdict(
            candidate(current),
            task=task,
            capability=capability,
            lease=intruder,
            expected_writer_id="robot-gateway",
            now_monotonic_s=NOW,
            current_evidence=current,
        ).disposition
        is AuthorityDisposition.LATCHED_STOP
    )


def test_uncommissioned_platform_latches_stop(current, task, capability, lease):
    uncommissioned = dataclasses.replace(capability, commissioned=False)
    assert (
        candidate_verdict(
            candidate(current),
            task=task,
            capability=uncommissioned,
            lease=lease,
            expected_writer_id="robot-gateway",
            now_monotonic_s=NOW,
            current_evidence=current,
        ).disposition
        is AuthorityDisposition.LATCHED_STOP
    )


def test_nonholonomic_platform_rejects_lateral_shortcut(current, task, capability, lease):
    nonholonomic = dataclasses.replace(capability, lateral_velocity=False)
    sideways = candidate(current, vy_mps=0.1)
    verdict = candidate_verdict(
        sideways,
        task=task,
        capability=nonholonomic,
        lease=lease,
        expected_writer_id="robot-gateway",
        now_monotonic_s=NOW,
        current_evidence=current,
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "lateral_velocity_unsupported" in verdict.reasons


@pytest.mark.parametrize("state", list(OwnerTrackState))
def test_only_locked_owner_authorizes_follow_translation(state):
    verdict = owner_motion_verdict(state, candidate_is_translation=True)
    expected = (
        AuthorityDisposition.PASS if state is OwnerTrackState.LOCKED else AuthorityDisposition.HOLD
    )
    assert verdict.disposition is expected


def test_owner_ambiguity_still_allows_in_place_stop_orient_command():
    assert (
        owner_motion_verdict(OwnerTrackState.AMBIGUOUS, candidate_is_translation=False).disposition
        is AuthorityDisposition.PASS
    )


def test_conversational_reaction_cannot_steal_navigation_base():
    reaction = BehaviorProposalV2(
        "excited_hop",
        frozenset({Resource.BASE, Resource.POSTURE}),
        False,
        NOW + 1.0,
    )
    assert (
        behavior_verdict(reaction, navigation_owns_base=True, now_monotonic_s=NOW).disposition
        is AuthorityDisposition.HOLD
    )


def test_voice_only_response_can_coexist_with_navigation():
    reply = BehaviorProposalV2("spoken_ack", frozenset({Resource.VOICE}), False, NOW + 1.0)
    assert (
        behavior_verdict(reply, navigation_owns_base=True, now_monotonic_s=NOW).disposition
        is AuthorityDisposition.PASS
    )


def test_emergency_behavior_always_latches_stop():
    stop = BehaviorProposalV2("emergency_stop", frozenset({Resource.BASE}), True, NOW - 10.0)
    assert (
        behavior_verdict(stop, navigation_owns_base=True, now_monotonic_s=NOW).disposition
        is AuthorityDisposition.LATCHED_STOP
    )


def test_terminal_witness_requires_fresh_current_evidence_and_settling(current, task):
    witness = TerminalWitnessV2(
        task.task_id,
        task.revision,
        True,
        NOW - 0.05,
        tuple((name, item.sequence) for name, item in current.items()),
        3,
    )
    assert (
        terminal_verdict(
            witness,
            task=task,
            current_evidence=current,
            now_monotonic_s=NOW,
            max_age_s=0.25,
            required_settled_samples=3,
        ).disposition
        is AuthorityDisposition.PASS
    )


def test_false_arrival_is_not_accepted(current, task):
    witness = TerminalWitnessV2(
        task.task_id,
        task.revision,
        False,
        NOW,
        tuple((name, item.sequence) for name, item in current.items()),
        3,
    )
    assert (
        terminal_verdict(
            witness,
            task=task,
            current_evidence=current,
            now_monotonic_s=NOW,
            max_age_s=0.25,
            required_settled_samples=3,
        ).disposition
        is AuthorityDisposition.HOLD
    )


def test_stop_is_not_completion_until_feedback_settles(current, task):
    witness = TerminalWitnessV2(
        task.task_id,
        task.revision,
        True,
        NOW,
        tuple((name, item.sequence) for name, item in current.items()),
        1,
    )
    verdict = terminal_verdict(
        witness,
        task=task,
        current_evidence=current,
        now_monotonic_s=NOW,
        max_age_s=0.25,
        required_settled_samples=3,
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "robot_not_settled" in verdict.reasons


def test_seeded_fault_campaign_never_authorizes_a_corrupted_boundary(
    current, task, capability, lease
):
    """A small reproducible design-level fault campaign, not a safety proof."""

    rng = random.Random(0xD06)
    corruptions_checked = 0
    for _ in range(200):
        corrupted = dict(current)
        stream = rng.choice(tuple(corrupted))
        mode = rng.choice(("stale", "invalid", "sim", "wrong_frame"))
        if mode == "stale":
            corrupted[stream] = dataclasses.replace(
                corrupted[stream], received_at_monotonic_s=NOW - 10.0
            )
        elif mode == "invalid":
            corrupted[stream] = dataclasses.replace(corrupted[stream], payload_valid=False)
        elif mode == "sim":
            corrupted[stream] = dataclasses.replace(
                corrupted[stream], origin=EvidenceOrigin.SIMULATION
            )
        else:
            corrupted[stream] = dataclasses.replace(corrupted[stream], frame_id="bad")
        evidence_verdict = join_evidence(REQUIRED, corrupted, now_monotonic_s=NOW)
        final = dominant_verdict(
            evidence_verdict,
            candidate_verdict(
                candidate(corrupted),
                task=task,
                capability=capability,
                lease=lease,
                expected_writer_id="robot-gateway",
                now_monotonic_s=NOW,
                current_evidence=corrupted,
            ),
        )
        assert final.disposition >= AuthorityDisposition.HOLD
        corruptions_checked += 1
    assert corruptions_checked == 200


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_velocity_never_becomes_a_candidate(current, value):
    with pytest.raises(ValueError):
        candidate(current, vx_mps=value)
