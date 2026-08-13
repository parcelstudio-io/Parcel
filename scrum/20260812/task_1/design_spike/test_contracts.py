"""Executable contract tests for the design spike (revision 2).

Revision 2 exists because the Fable audit (``../FABLE_VERDICT.md`` RC-1) proved
revision 1's suite let 12 of 20 invariant-killing mutants live.  Every test
below that is new either kills a named mutant or exercises an invariant the
audit found unenforced; the mutant-to-test map is in
``../../task_2/S1_STATUS.md``.
"""

from __future__ import annotations

import dataclasses
import math
import random

import pytest
from contracts import (
    PHYSICAL_ONLY,
    AuthorityDisposition,
    BehaviorProposalV2,
    EvidenceEnvelopeV2,
    EvidenceOrigin,
    GatewayPhase,
    HardwareCapabilityManifestV1,
    LeaseV1,
    MotionCandidateV2,
    OwnerTrackState,
    ProposalKind,
    RequiredEvidenceV1,
    Resource,
    RobotGatewayV1,
    SafetyVerdictV1,
    StationaryWitnessV1,
    TaskTransactionV2,
    TerminalWitnessV2,
    authorize_motion,
    behavior_verdict,
    candidate_verdict,
    dominant_verdict,
    in_place_search_verdict,
    join_evidence,
    owner_motion_verdict,
    speed_envelope_verdict,
    terminal_verdict,
)

NOW = 100.0
WRITER = "robot-gateway"
BOOT_EPOCH = 4

# Illustrative spike thresholds.  They are NOT product constants and carry no
# hazard or ODD derivation; they exist so that every gate call has to state its
# own limits instead of inheriting a hidden default (global rule 6).
SURROUND_MAX_AGE_S = 0.50
PERMITTED_SPEED_MPS = 0.50
CLEAR_MAX_AGE_S = 0.25
CLEAR_SPEED_EPSILON_MPS = 0.01
CLEAR_YAW_EPSILON_RPS = 0.02
CLEAR_SETTLED_SAMPLES = 3

REQUIRED = (
    RequiredEvidenceV1("pose", "odom", 0.25),
    RequiredEvidenceV1("geometry", "base_link", 0.20),
    RequiredEvidenceV1("feedback", "base_link", 0.20),
)

# backlog/BLOCKED.md B5, measured on the `calibrated_go2_reanchoring` arm: the
# controller stops 0.002-0.040 m inside the 2.5 m outer band edge in its own MAP
# frame while claim-tick MAP error runs 0.007-0.239 m, and 3 of 7 arrivals
# stopped TRUE-outside the band (-0.153 / -0.043 / -0.024 m).  The named fixture
# below pairs the low margin with the worst measured error.
B5_ARRIVAL_MARGIN_M = 0.007
B5_POSE_ERROR_M = 0.239
B5_TRUE_OUTSIDE_MARGIN_M = -0.153


def evidence(
    stream_id: str,
    frame_id: str,
    *,
    sequence: int = 7,
    age_s: float = 0.05,
    origin: EvidenceOrigin = EvidenceOrigin.PHYSICAL,
    payload_valid: bool = True,
    source_time: float | None = 1_000_000.0,
    calibration_epoch: str = "cal-1",
) -> EvidenceEnvelopeV2:
    return EvidenceEnvelopeV2(
        stream_id=stream_id,
        sequence=sequence,
        origin=origin,
        received_at_monotonic_s=NOW - age_s,
        captured_at_source_s=source_time,
        frame_id=frame_id,
        calibration_epoch=calibration_epoch,
        payload_valid=payload_valid,
        clock_uncertainty_ms=3.0,
    )


def corrupt(instance, **fields):
    """Force a field past its validator.

    This models a payload that crossed a process boundary and was rebuilt by a
    decoder which did not re-run ``__post_init__`` — precisely the case the
    verdict functions must still fail closed on (RC-1b).  Constructor validation
    and gate validation are separate defences and are mutated separately.
    """

    clone = object.__new__(type(instance))
    values = {f.name: getattr(instance, f.name) for f in dataclasses.fields(instance)}
    values.update(fields)
    for name, value in values.items():
        object.__setattr__(clone, name, value)
    return clone


@pytest.fixture
def current() -> dict[str, EvidenceEnvelopeV2]:
    return {
        "pose": evidence("pose", "odom"),
        "geometry": evidence("geometry", "base_link"),
        "feedback": evidence("feedback", "base_link"),
    }


@pytest.fixture
def surrounding() -> EvidenceEnvelopeV2:
    return evidence("surround_scan", "base_link", sequence=5, age_s=0.10)


@pytest.fixture
def task() -> TaskTransactionV2:
    return TaskTransactionV2("task-1", 3, "turn-9", True, NOW - 1.0, NOW + 5.0)


@pytest.fixture
def capability() -> HardwareCapabilityManifestV1:
    return HardwareCapabilityManifestV1("go2-edu-serial-redacted", True, True, 0.5, 0.25, 0.8, True)


@pytest.fixture
def lease() -> LeaseV1:
    return LeaseV1(WRITER, BOOT_EPOCH, NOW + 0.5)


@pytest.fixture
def gateway(lease) -> RobotGatewayV1:
    instance = RobotGatewayV1(boot_epoch=BOOT_EPOCH, expected_writer_id=WRITER)
    assert instance.arm(lease, now_monotonic_s=NOW).disposition is AuthorityDisposition.PASS
    return instance


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


def witness(current: dict[str, EvidenceEnvelopeV2], **changes) -> TerminalWitnessV2:
    value = TerminalWitnessV2(
        task_id="task-1",
        task_revision=3,
        predicate_true=True,
        observed_at_monotonic_s=NOW - 0.05,
        evidence_sequences=tuple((name, item.sequence) for name, item in current.items()),
        settled_samples=3,
        arrival_margin_m=0.30,
        pose_uncertainty_m=0.05,
    )
    return dataclasses.replace(value, **changes)


def admit(candidate_value, *, task, capability, lease, current_evidence, **changes):
    """Call ``candidate_verdict`` with the spike's standard bindings."""

    kwargs = {
        "task": task,
        "capability": capability,
        "lease": lease,
        "expected_writer_id": WRITER,
        "current_epoch": BOOT_EPOCH,
        "now_monotonic_s": NOW,
        "current_evidence": current_evidence,
    }
    kwargs.update(changes)
    return candidate_verdict(candidate_value, **kwargs)


# ---------------------------------------------------------------------------
# Evidence provenance and freshness
# ---------------------------------------------------------------------------


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


@pytest.mark.parametrize(
    "origin", [EvidenceOrigin.SIMULATION, EvidenceOrigin.REPLAY, EvidenceOrigin.UNKNOWN]
)
def test_lab_evidence_cannot_authorize_physical_motion(current, origin):
    current["pose"] = dataclasses.replace(current["pose"], origin=origin)
    verdict = join_evidence(REQUIRED, current, now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "pose:origin_not_commissioned" in verdict.reasons


def test_default_required_evidence_admits_physical_origin_only():
    """Kills the mutant that widens the default admission set (M02)."""

    spec = RequiredEvidenceV1("pose", "odom", 0.25)
    assert spec.allowed_origins == frozenset({EvidenceOrigin.PHYSICAL})
    assert PHYSICAL_ONLY == frozenset({EvidenceOrigin.PHYSICAL})


def test_unknown_origin_can_never_be_commissioned():
    with pytest.raises(ValueError):
        RequiredEvidenceV1(
            "pose",
            "odom",
            0.25,
            allowed_origins=frozenset({EvidenceOrigin.PHYSICAL, EvidenceOrigin.UNKNOWN}),
        )


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


def test_evidence_without_calibration_epoch_is_rejected():
    """Kills the mutant that drops the calibration-epoch requirement (M20)."""

    with pytest.raises(ValueError):
        evidence("pose", "odom", calibration_epoch="")


def test_calibration_epoch_mismatch_latches_stop(current):
    pinned = (
        RequiredEvidenceV1("pose", "odom", 0.25, PHYSICAL_ONLY, "cal-1"),
        RequiredEvidenceV1("geometry", "base_link", 0.20, PHYSICAL_ONLY, "cal-1"),
        RequiredEvidenceV1("feedback", "base_link", 0.20, PHYSICAL_ONLY, "cal-1"),
    )
    current["geometry"] = dataclasses.replace(current["geometry"], calibration_epoch="cal-2")
    verdict = join_evidence(pinned, current, now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "geometry:calibration_epoch_mismatch" in verdict.reasons


def test_receive_time_in_the_future_latches_stop(current):
    current["pose"] = dataclasses.replace(current["pose"], received_at_monotonic_s=NOW + 5.0)
    verdict = join_evidence(REQUIRED, current, now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "pose:receive_time_in_future" in verdict.reasons


@pytest.mark.parametrize("bad_clock", [math.nan, math.inf, -math.inf, None])
def test_malformed_decision_clock_latches_evidence_join(current, bad_clock):
    verdict = join_evidence(REQUIRED, current, now_monotonic_s=bad_clock)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "decision_clock_malformed" in verdict.reasons


@pytest.mark.parametrize("bad_clock", [math.nan, math.inf, None])
def test_malformed_receive_time_in_payload_latches(current, bad_clock):
    current["feedback"] = corrupt(current["feedback"], received_at_monotonic_s=bad_clock)
    verdict = join_evidence(REQUIRED, current, now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "feedback:receive_time_malformed" in verdict.reasons


def test_empty_required_evidence_set_is_not_authorization(current):
    """The join's sibling of the zero-gate case: nothing checked is not a PASS."""

    verdict = join_evidence((), current, now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "no_required_evidence" in verdict.reasons


def test_malformed_required_max_age_latches(current):
    broken = (corrupt(REQUIRED[0], max_age_s=math.nan),) + REQUIRED[1:]
    verdict = join_evidence(broken, current, now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "pose:max_age_malformed" in verdict.reasons


# ---------------------------------------------------------------------------
# Monotone composition
# ---------------------------------------------------------------------------


def test_dominant_safety_verdict_cannot_be_relaxed():
    verdict = dominant_verdict(
        SafetyVerdictV1(AuthorityDisposition.LATCHED_STOP, ("tilt",)),
        SafetyVerdictV1(AuthorityDisposition.PASS),
        SafetyVerdictV1(AuthorityDisposition.CLAMP, ("social_distance",)),
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert verdict.reasons == ("tilt",)


def test_zero_gate_composition_is_not_authorization():
    """N-3: an empty gate set is a composition bug, never a PASS."""

    verdict = dominant_verdict()
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "no_gates_evaluated" in verdict.reasons


def test_speed_envelope_produces_clamp(current):
    """N-3: the CLAMP rung is emitted by a real gate, not only by test inputs."""

    fast = candidate(current, vx_mps=0.45, vy_mps=0.20)
    verdict = speed_envelope_verdict(fast, permitted_speed_mps=0.30)
    assert verdict.disposition is AuthorityDisposition.CLAMP
    assert "speed_envelope_exceeded" in verdict.reasons
    assert (
        speed_envelope_verdict(candidate(current), permitted_speed_mps=0.30).disposition
        is AuthorityDisposition.PASS
    )


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1.0, None])
def test_malformed_speed_envelope_latches(current, bad):
    verdict = speed_envelope_verdict(candidate(current), permitted_speed_mps=bad)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP


def test_resource_enum_is_the_canonical_six():
    """N-4: one vocabulary, or the spike ships the defect it exists to retire."""

    assert [item.value for item in Resource] == [
        "base",
        "posture",
        "voice",
        "attention",
        "perception_scan",
        "expression_audio",
    ]


# ---------------------------------------------------------------------------
# Candidate admission
# ---------------------------------------------------------------------------


def test_deterministic_candidate_with_current_task_and_lease_passes(
    current, task, capability, lease
):
    verdict = admit(
        candidate(current), task=task, capability=capability, lease=lease, current_evidence=current
    )
    assert verdict.disposition is AuthorityDisposition.PASS


def test_learned_candidate_has_identical_admission_rules(current, task, capability, lease):
    learned = candidate(current, producer="mppi-shadow-7", kind=ProposalKind.LEARNED)
    assert (
        admit(
            learned, task=task, capability=capability, lease=lease, current_evidence=current
        ).disposition
        is AuthorityDisposition.PASS
    )


def test_old_plan_revision_is_discarded(current, task, capability, lease):
    old = candidate(current, task_revision=task.revision - 1)
    assert (
        admit(
            old, task=task, capability=capability, lease=lease, current_evidence=current
        ).disposition
        is AuthorityDisposition.HOLD
    )


def test_scene_revision_change_discards_late_model_output(current, task, capability, lease):
    late = candidate(current)
    current["geometry"] = dataclasses.replace(current["geometry"], sequence=8)
    verdict = admit(
        late, task=task, capability=capability, lease=lease, current_evidence=current
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "geometry:evidence_revision_changed" in verdict.reasons


def test_expired_candidate_holds(current, task, capability, lease):
    expired = candidate(current, valid_until_monotonic_s=NOW)
    verdict = admit(
        expired, task=task, capability=capability, lease=lease, current_evidence=current
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "candidate_expired" in verdict.reasons


def test_expired_task_holds(current, task, capability, lease):
    """Kills the mutant that drops the task-expiry leg (M12)."""

    expired_task = dataclasses.replace(task, valid_until_monotonic_s=NOW)
    verdict = admit(
        candidate(current),
        task=expired_task,
        capability=capability,
        lease=lease,
        current_evidence=current,
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "task_expired" in verdict.reasons


def test_unauthorized_task_cannot_move_the_base(current, task, capability, lease):
    """Kills the mutant that drops the owner-authorization leg (M09)."""

    unauthorized = dataclasses.replace(task, owner_authorized=False)
    verdict = admit(
        candidate(current),
        task=unauthorized,
        capability=capability,
        lease=lease,
        current_evidence=current,
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "task_not_owner_authorized" in verdict.reasons


def test_vx_beyond_platform_capability_holds(current, task, capability, lease):
    """Kills the mutant that drops the vx limit (M10)."""

    fast = candidate(current, vx_mps=capability.max_vx_mps + 0.1)
    verdict = admit(
        fast, task=task, capability=capability, lease=lease, current_evidence=current
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "vx_limit_exceeded" in verdict.reasons


def test_vy_beyond_platform_capability_holds(current, task, capability, lease):
    sideways = candidate(current, vy_mps=capability.max_vy_mps + 0.1)
    verdict = admit(
        sideways, task=task, capability=capability, lease=lease, current_evidence=current
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "vy_limit_exceeded" in verdict.reasons


def test_yaw_beyond_platform_capability_holds(current, task, capability, lease):
    """Kills the mutant that drops the yaw limit (M11)."""

    spin = candidate(current, yaw_rps=capability.max_yaw_rps + 0.1)
    verdict = admit(
        spin, task=task, capability=capability, lease=lease, current_evidence=current
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "yaw_limit_exceeded" in verdict.reasons


def test_candidate_outside_base_link_is_rejected(current):
    """Kills the mutant that drops the base_link frame requirement (M17)."""

    with pytest.raises(ValueError):
        candidate(current, frame_id="odom")


def test_lease_loss_requires_stop(current, task, capability, lease):
    expired_lease = dataclasses.replace(lease, valid_until_monotonic_s=NOW)
    verdict = admit(
        candidate(current),
        task=task,
        capability=capability,
        lease=expired_lease,
        current_evidence=current,
    )
    assert verdict.disposition is AuthorityDisposition.STOP
    assert "lease_expired" in verdict.reasons


def test_second_writer_latches_stop(current, task, capability, lease):
    intruder = dataclasses.replace(lease, writer_id="second-writer")
    assert (
        admit(
            candidate(current),
            task=task,
            capability=capability,
            lease=intruder,
            current_evidence=current,
        ).disposition
        is AuthorityDisposition.LATCHED_STOP
    )


def test_uncommissioned_platform_latches_stop(current, task, capability, lease):
    uncommissioned = dataclasses.replace(capability, commissioned=False)
    assert (
        admit(
            candidate(current),
            task=task,
            capability=uncommissioned,
            lease=lease,
            current_evidence=current,
        ).disposition
        is AuthorityDisposition.LATCHED_STOP
    )


def test_nonholonomic_platform_rejects_lateral_shortcut(current, task, capability, lease):
    nonholonomic = dataclasses.replace(capability, lateral_velocity=False)
    sideways = candidate(current, vy_mps=0.1)
    verdict = admit(
        sideways, task=task, capability=nonholonomic, lease=lease, current_evidence=current
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "lateral_velocity_unsupported" in verdict.reasons


@pytest.mark.parametrize("bad_clock", [math.nan, math.inf, -math.inf, None])
def test_malformed_decision_clock_never_authorizes_a_candidate(
    current, task, capability, lease, bad_clock
):
    """RC-1b: the audit's probe P7 returned PASS with every gate silently skipped."""

    verdict = admit(
        candidate(current),
        task=task,
        capability=capability,
        lease=lease,
        current_evidence=current,
        now_monotonic_s=bad_clock,
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "decision_clock_malformed" in verdict.reasons


def test_malformed_task_deadline_never_authorizes_a_candidate(
    current, task, capability, lease
):
    broken = corrupt(task, valid_until_monotonic_s=math.nan)
    verdict = admit(
        candidate(current),
        task=broken,
        capability=capability,
        lease=lease,
        current_evidence=current,
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "task_time_malformed" in verdict.reasons


def test_malformed_lease_deadline_never_authorizes_a_candidate(
    current, task, capability, lease
):
    broken = corrupt(lease, valid_until_monotonic_s=math.nan)
    verdict = admit(
        candidate(current),
        task=task,
        capability=capability,
        lease=broken,
        current_evidence=current,
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "lease_time_malformed" in verdict.reasons


def test_malformed_candidate_command_never_authorizes(current, task, capability, lease):
    broken = corrupt(candidate(current), vx_mps=math.nan)
    verdict = admit(
        broken, task=task, capability=capability, lease=lease, current_evidence=current
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "candidate_command_malformed" in verdict.reasons


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_velocity_never_becomes_a_candidate(current, value):
    with pytest.raises(ValueError):
        candidate(current, vx_mps=value)


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_nonfinite_candidate_deadline_is_rejected(current, value):
    with pytest.raises(ValueError):
        candidate(current, valid_until_monotonic_s=value)


# ---------------------------------------------------------------------------
# RC-1a: boot epoch and restart disarm
# ---------------------------------------------------------------------------


def test_fresh_gateway_starts_disarmed(lease, current, task, capability, surrounding):
    """RC-1a: a fresh instance models a process boot and cannot be born armed."""

    fresh = RobotGatewayV1(boot_epoch=BOOT_EPOCH, expected_writer_id=WRITER)
    assert fresh.phase is GatewayPhase.DISARMED
    assert fresh.lease is None
    verdict = authorize_motion(
        fresh,
        candidate(current),
        task=task,
        capability=capability,
        lease=lease,
        required=REQUIRED,
        current_evidence=current,
        owner_state=OwnerTrackState.LOCKED,
        candidate_is_translation=True,
        now_monotonic_s=NOW,
        permitted_speed_mps=PERMITTED_SPEED_MPS,
        surrounding_max_age_s=SURROUND_MAX_AGE_S,
        surrounding_evidence=surrounding,
    )
    assert verdict.disposition is AuthorityDisposition.STOP
    assert "gateway_disarmed" in verdict.reasons


def test_gateway_cannot_be_constructed_already_armed():
    with pytest.raises(TypeError):
        RobotGatewayV1(  # type: ignore[call-arg]
            boot_epoch=BOOT_EPOCH,
            expected_writer_id=WRITER,
            phase=GatewayPhase.ARMED,
        )


def test_prior_epoch_lease_cannot_arm_the_gateway():
    """RC-1a: the audit's executed probe used epoch 1 against a boot epoch of 4."""

    fresh = RobotGatewayV1(boot_epoch=BOOT_EPOCH, expected_writer_id=WRITER)
    verdict = fresh.arm(LeaseV1(WRITER, 1, NOW + 0.5), now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.STOP
    assert "lease_epoch_mismatch" in verdict.reasons
    assert fresh.phase is GatewayPhase.DISARMED


@pytest.mark.parametrize("epoch", [1, BOOT_EPOCH - 1, BOOT_EPOCH + 1, 9_999])
def test_lease_from_another_epoch_cannot_authorize_motion(
    current, task, capability, epoch
):
    """RC-1a: the exact probe that returned PASS in revision 1."""

    stale = LeaseV1(WRITER, epoch, NOW + 0.5)
    verdict = admit(
        candidate(current),
        task=task,
        capability=capability,
        lease=stale,
        current_evidence=current,
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "lease_epoch_mismatch" in verdict.reasons


def test_current_epoch_lease_authorizes(current, task, capability, lease):
    verdict = admit(
        candidate(current), task=task, capability=capability, lease=lease, current_evidence=current
    )
    assert verdict.disposition is AuthorityDisposition.PASS


@pytest.mark.parametrize("bad_epoch", [0, -1, None, 1.5, True])
def test_malformed_gateway_epoch_latches(current, task, capability, lease, bad_epoch):
    verdict = admit(
        candidate(current),
        task=task,
        capability=capability,
        lease=lease,
        current_evidence=current,
        current_epoch=bad_epoch,
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "gateway_epoch_malformed" in verdict.reasons


def test_foreign_writer_arming_latches_the_gateway():
    fresh = RobotGatewayV1(boot_epoch=BOOT_EPOCH, expected_writer_id=WRITER)
    verdict = fresh.arm(LeaseV1("second-writer", BOOT_EPOCH, NOW + 0.5), now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert fresh.phase is GatewayPhase.LATCHED


def test_released_writer_must_re_arm_before_commanding(
    gateway, current, task, capability, lease, surrounding
):
    """The second-writer-after-release class: release means release."""

    gateway.release()
    assert gateway.phase is GatewayPhase.DISARMED
    verdict = authorize_motion(
        gateway,
        candidate(current),
        task=task,
        capability=capability,
        lease=lease,
        required=REQUIRED,
        current_evidence=current,
        owner_state=OwnerTrackState.LOCKED,
        candidate_is_translation=True,
        now_monotonic_s=NOW,
        permitted_speed_mps=PERMITTED_SPEED_MPS,
        surrounding_max_age_s=SURROUND_MAX_AGE_S,
        surrounding_evidence=surrounding,
    )
    assert verdict.disposition is AuthorityDisposition.STOP
    assert "gateway_disarmed" in verdict.reasons
    assert gateway.arm(lease, now_monotonic_s=NOW).disposition is AuthorityDisposition.PASS


def test_expired_lease_cannot_arm_the_gateway():
    fresh = RobotGatewayV1(boot_epoch=BOOT_EPOCH, expected_writer_id=WRITER)
    verdict = fresh.arm(LeaseV1(WRITER, BOOT_EPOCH, NOW - 1.0), now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.STOP
    assert fresh.phase is GatewayPhase.DISARMED


@pytest.mark.parametrize("bad_epoch", [0, -3, True])
def test_gateway_boot_epoch_must_be_a_positive_integer(bad_epoch):
    with pytest.raises(ValueError):
        RobotGatewayV1(boot_epoch=bad_epoch, expected_writer_id=WRITER)


# ---------------------------------------------------------------------------
# RC-1c: the latch is stateful
# ---------------------------------------------------------------------------


def _authorize(gateway, current, task, capability, lease, surrounding, **changes):
    kwargs = {
        "task": task,
        "capability": capability,
        "lease": lease,
        "required": REQUIRED,
        "current_evidence": current,
        "owner_state": OwnerTrackState.LOCKED,
        "candidate_is_translation": True,
        "now_monotonic_s": NOW,
        "permitted_speed_mps": PERMITTED_SPEED_MPS,
        "surrounding_max_age_s": SURROUND_MAX_AGE_S,
        "surrounding_evidence": surrounding,
    }
    kwargs.update(changes)
    value = kwargs.pop("candidate", None)
    if value is None:
        value = candidate(current)
    return authorize_motion(gateway, value, **kwargs)


def test_latched_stop_persists_across_a_subsequent_clean_tick(
    gateway, current, task, capability, lease, surrounding
):
    """RC-1c: revision 1 returned PASS on the very next clean call."""

    dirty = dict(current)
    dirty["pose"] = dataclasses.replace(dirty["pose"], frame_id="mystery_frame")
    first = _authorize(gateway, dirty, task, capability, lease, surrounding)
    assert first.disposition is AuthorityDisposition.LATCHED_STOP
    assert gateway.phase is GatewayPhase.LATCHED

    for _ in range(5):
        clean = _authorize(gateway, current, task, capability, lease, surrounding)
        assert clean.disposition is AuthorityDisposition.LATCHED_STOP
        assert "pose:frame_mismatch" in clean.reasons


def test_latch_does_not_clear_without_an_operator_event(
    gateway, current, task, capability, lease, surrounding
):
    dirty = dict(current)
    dirty["pose"] = dataclasses.replace(dirty["pose"], payload_valid=False)
    assert (
        _authorize(gateway, dirty, task, capability, lease, surrounding).disposition
        is AuthorityDisposition.LATCHED_STOP
    )
    verdict = gateway.clear_latch(
        operator_ack=False,
        stationary=StationaryWitnessV1(EvidenceOrigin.PHYSICAL, NOW - 0.05, 0.0, 0.0, 5),
        now_monotonic_s=NOW,
        max_age_s=CLEAR_MAX_AGE_S,
        speed_epsilon_mps=CLEAR_SPEED_EPSILON_MPS,
        yaw_epsilon_rps=CLEAR_YAW_EPSILON_RPS,
        required_settled_samples=CLEAR_SETTLED_SAMPLES,
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "operator_ack_absent" in verdict.reasons
    assert gateway.phase is GatewayPhase.LATCHED


@pytest.mark.parametrize(
    ("stationary", "reason"),
    [
        (None, "stationary_feedback_missing"),
        (
            StationaryWitnessV1(EvidenceOrigin.PHYSICAL, NOW - 5.0, 0.0, 0.0, 5),
            "stationary_feedback_stale",
        ),
        (
            StationaryWitnessV1(EvidenceOrigin.PHYSICAL, NOW - 0.05, 0.4, 0.0, 5),
            "robot_still_translating",
        ),
        (
            StationaryWitnessV1(EvidenceOrigin.PHYSICAL, NOW - 0.05, 0.0, 0.5, 5),
            "robot_still_rotating",
        ),
        (
            StationaryWitnessV1(EvidenceOrigin.PHYSICAL, NOW - 0.05, 0.0, 0.0, 1),
            "robot_not_settled",
        ),
        (
            StationaryWitnessV1(EvidenceOrigin.SIMULATION, NOW - 0.05, 0.0, 0.0, 5),
            "stationary_feedback_not_physical",
        ),
    ],
)
def test_latch_does_not_clear_without_fresh_stationary_feedback(
    gateway, current, task, capability, lease, surrounding, stationary, reason
):
    dirty = dict(current)
    dirty["geometry"] = dataclasses.replace(dirty["geometry"], frame_id="mystery_frame")
    assert (
        _authorize(gateway, dirty, task, capability, lease, surrounding).disposition
        is AuthorityDisposition.LATCHED_STOP
    )
    verdict = gateway.clear_latch(
        operator_ack=True,
        stationary=stationary,
        now_monotonic_s=NOW,
        max_age_s=CLEAR_MAX_AGE_S,
        speed_epsilon_mps=CLEAR_SPEED_EPSILON_MPS,
        yaw_epsilon_rps=CLEAR_YAW_EPSILON_RPS,
        required_settled_samples=CLEAR_SETTLED_SAMPLES,
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert reason in verdict.reasons
    assert gateway.phase is GatewayPhase.LATCHED


def test_operator_clear_with_stationary_feedback_returns_to_disarmed_not_armed(
    gateway, current, task, capability, lease, surrounding
):
    dirty = dict(current)
    dirty["feedback"] = dataclasses.replace(dirty["feedback"], frame_id="mystery_frame")
    assert (
        _authorize(gateway, dirty, task, capability, lease, surrounding).disposition
        is AuthorityDisposition.LATCHED_STOP
    )
    cleared = gateway.clear_latch(
        operator_ack=True,
        stationary=StationaryWitnessV1(EvidenceOrigin.PHYSICAL, NOW - 0.05, 0.0, 0.0, 5),
        now_monotonic_s=NOW,
        max_age_s=CLEAR_MAX_AGE_S,
        speed_epsilon_mps=CLEAR_SPEED_EPSILON_MPS,
        yaw_epsilon_rps=CLEAR_YAW_EPSILON_RPS,
        required_settled_samples=CLEAR_SETTLED_SAMPLES,
    )
    assert cleared.disposition is AuthorityDisposition.PASS
    assert gateway.phase is GatewayPhase.DISARMED

    # Clearing a latch is not re-arming: authority must be re-acquired.
    still_disarmed = _authorize(gateway, current, task, capability, lease, surrounding)
    assert still_disarmed.disposition is AuthorityDisposition.STOP
    assert "gateway_disarmed" in still_disarmed.reasons

    assert gateway.arm(lease, now_monotonic_s=NOW).disposition is AuthorityDisposition.PASS
    assert (
        _authorize(gateway, current, task, capability, lease, surrounding).disposition
        is AuthorityDisposition.PASS
    )


def test_latched_gateway_cannot_be_re_armed(gateway, current, task, capability, lease, surrounding):
    dirty = dict(current)
    dirty["pose"] = dataclasses.replace(dirty["pose"], frame_id="mystery_frame")
    _authorize(gateway, dirty, task, capability, lease, surrounding)
    verdict = gateway.arm(lease, now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert gateway.phase is GatewayPhase.LATCHED


def test_malformed_gateway_clock_latches(gateway):
    verdict = gateway.observe(
        SafetyVerdictV1(AuthorityDisposition.PASS), now_monotonic_s=math.nan
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert gateway.phase is GatewayPhase.LATCHED


def test_clear_latch_on_an_unlatched_gateway_is_a_no_op(gateway):
    verdict = gateway.clear_latch(
        operator_ack=True,
        stationary=None,
        now_monotonic_s=NOW,
        max_age_s=CLEAR_MAX_AGE_S,
        speed_epsilon_mps=CLEAR_SPEED_EPSILON_MPS,
        yaw_epsilon_rps=CLEAR_YAW_EPSILON_RPS,
        required_settled_samples=CLEAR_SETTLED_SAMPLES,
    )
    assert verdict.disposition is AuthorityDisposition.PASS
    assert gateway.phase is GatewayPhase.ARMED


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1.0, None])
def test_malformed_clear_thresholds_keep_the_latch(
    gateway, current, task, capability, lease, surrounding, bad
):
    dirty = dict(current)
    dirty["pose"] = dataclasses.replace(dirty["pose"], frame_id="mystery_frame")
    _authorize(gateway, dirty, task, capability, lease, surrounding)
    verdict = gateway.clear_latch(
        operator_ack=True,
        stationary=StationaryWitnessV1(EvidenceOrigin.PHYSICAL, NOW - 0.05, 0.0, 0.0, 5),
        now_monotonic_s=NOW,
        max_age_s=bad,
        speed_epsilon_mps=CLEAR_SPEED_EPSILON_MPS,
        yaw_epsilon_rps=CLEAR_YAW_EPSILON_RPS,
        required_settled_samples=CLEAR_SETTLED_SAMPLES,
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "clear_thresholds_malformed" in verdict.reasons
    assert gateway.phase is GatewayPhase.LATCHED


@pytest.mark.parametrize("bad", [math.nan, math.inf, None])
def test_stationary_witness_rejects_malformed_measurements(bad):
    with pytest.raises(ValueError):
        StationaryWitnessV1(EvidenceOrigin.PHYSICAL, NOW, bad, 0.0, 5)


def test_stationary_witness_rejects_negative_settled_samples():
    with pytest.raises(ValueError):
        StationaryWitnessV1(EvidenceOrigin.PHYSICAL, NOW, 0.0, 0.0, -5)


# ---------------------------------------------------------------------------
# Owner identity and bounded in-place search (N-1)
# ---------------------------------------------------------------------------


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


def test_untyped_owner_state_cannot_be_smuggled_in():
    with pytest.raises(TypeError):
        owner_motion_verdict("locked", candidate_is_translation=True)  # type: ignore[arg-type]


def test_in_place_search_requires_surrounding_collision_evidence(current):
    """N-1: yaw-only candidates pass the identity gate, so something else must ask."""

    spin = candidate(current, vx_mps=0.0, vy_mps=0.0, yaw_rps=0.3)
    verdict = in_place_search_verdict(
        spin,
        surrounding_evidence=None,
        now_monotonic_s=NOW,
        max_age_s=SURROUND_MAX_AGE_S,
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "surround_evidence_missing" in verdict.reasons


def test_in_place_search_rejects_stale_surrounding_evidence(current, surrounding):
    spin = candidate(current, vx_mps=0.0, vy_mps=0.0, yaw_rps=0.3)
    verdict = in_place_search_verdict(
        spin,
        surrounding_evidence=dataclasses.replace(
            surrounding, received_at_monotonic_s=NOW - 10.0
        ),
        now_monotonic_s=NOW,
        max_age_s=SURROUND_MAX_AGE_S,
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "surround_evidence_stale" in verdict.reasons


@pytest.mark.parametrize(
    "origin", [EvidenceOrigin.SIMULATION, EvidenceOrigin.REPLAY, EvidenceOrigin.UNKNOWN]
)
def test_in_place_search_rejects_non_physical_surrounding_evidence(
    current, surrounding, origin
):
    spin = candidate(current, vx_mps=0.0, vy_mps=0.0, yaw_rps=0.3)
    verdict = in_place_search_verdict(
        spin,
        surrounding_evidence=dataclasses.replace(surrounding, origin=origin),
        now_monotonic_s=NOW,
        max_age_s=SURROUND_MAX_AGE_S,
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP


def test_in_place_gate_does_not_fire_on_a_translating_candidate(current):
    verdict = in_place_search_verdict(
        candidate(current),
        surrounding_evidence=None,
        now_monotonic_s=NOW,
        max_age_s=SURROUND_MAX_AGE_S,
    )
    assert verdict.disposition is AuthorityDisposition.PASS


def test_in_place_search_with_fresh_physical_surround_passes(current, surrounding):
    spin = candidate(current, vx_mps=0.0, vy_mps=0.0, yaw_rps=0.3)
    verdict = in_place_search_verdict(
        spin,
        surrounding_evidence=surrounding,
        now_monotonic_s=NOW,
        max_age_s=SURROUND_MAX_AGE_S,
    )
    assert verdict.disposition is AuthorityDisposition.PASS


# ---------------------------------------------------------------------------
# N-2: the composed physical-translation pipeline
# ---------------------------------------------------------------------------


def test_candidate_verdict_alone_is_not_authorization(current, task, capability, lease):
    """N-2, stated honestly: the admission gate is scoped, so it must be composed.

    Simulation-origin pose evidence with an unchanged sequence number is admitted
    by ``candidate_verdict`` — and refused by ``authorize_motion``.  Revision 1
    left that composition to the caller and nothing enforced it.
    """

    current["pose"] = dataclasses.replace(current["pose"], origin=EvidenceOrigin.SIMULATION)
    scoped = admit(
        candidate(current), task=task, capability=capability, lease=lease, current_evidence=current
    )
    assert scoped.disposition is AuthorityDisposition.PASS

    fresh = RobotGatewayV1(boot_epoch=BOOT_EPOCH, expected_writer_id=WRITER)
    fresh.arm(lease, now_monotonic_s=NOW)
    composed = authorize_motion(
        fresh,
        candidate(current),
        task=task,
        capability=capability,
        lease=lease,
        required=REQUIRED,
        current_evidence=current,
        owner_state=OwnerTrackState.LOCKED,
        candidate_is_translation=True,
        now_monotonic_s=NOW,
        permitted_speed_mps=PERMITTED_SPEED_MPS,
        surrounding_max_age_s=SURROUND_MAX_AGE_S,
        surrounding_evidence=evidence("surround_scan", "base_link"),
    )
    assert composed.disposition is AuthorityDisposition.LATCHED_STOP
    assert "pose:origin_not_commissioned" in composed.reasons


@pytest.mark.parametrize("stage", ["pose", "geometry", "feedback", "surround"])
@pytest.mark.parametrize(
    "origin", [EvidenceOrigin.SIMULATION, EvidenceOrigin.REPLAY, EvidenceOrigin.UNKNOWN]
)
def test_composed_pipeline_refuses_lab_origin_at_every_stage(
    gateway, current, task, capability, lease, surrounding, stage, origin
):
    """N-2: origin, frame and freshness threaded end to end, one stage at a time."""

    spin = None
    translation = True
    if stage == "surround":
        surrounding = dataclasses.replace(surrounding, origin=origin)
        spin = candidate(current, vx_mps=0.0, vy_mps=0.0, yaw_rps=0.3)
        translation = False
    else:
        current[stage] = dataclasses.replace(current[stage], origin=origin)
    verdict = _authorize(
        gateway,
        current,
        task,
        capability,
        lease,
        surrounding,
        candidate=spin,
        candidate_is_translation=translation,
    )
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert gateway.phase is GatewayPhase.LATCHED


@pytest.mark.parametrize("stage", ["pose", "geometry", "feedback"])
def test_composed_pipeline_refuses_a_wrong_frame_at_every_stage(
    gateway, current, task, capability, lease, surrounding, stage
):
    current[stage] = dataclasses.replace(current[stage], frame_id="mystery_frame")
    verdict = _authorize(gateway, current, task, capability, lease, surrounding)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert f"{stage}:frame_mismatch" in verdict.reasons


@pytest.mark.parametrize("stage", ["pose", "geometry", "feedback"])
def test_composed_pipeline_holds_on_stale_evidence_at_every_stage(
    gateway, current, task, capability, lease, surrounding, stage
):
    current[stage] = dataclasses.replace(current[stage], received_at_monotonic_s=NOW - 9.0)
    verdict = _authorize(gateway, current, task, capability, lease, surrounding)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert f"{stage}:stale" in verdict.reasons


def test_composed_pipeline_passes_on_a_fully_clean_tick(
    gateway, current, task, capability, lease, surrounding
):
    verdict = _authorize(gateway, current, task, capability, lease, surrounding)
    assert verdict.disposition is AuthorityDisposition.PASS
    assert gateway.phase is GatewayPhase.ARMED


def test_composed_pipeline_holds_when_owner_identity_is_ambiguous(
    gateway, current, task, capability, lease, surrounding
):
    verdict = _authorize(
        gateway,
        current,
        task,
        capability,
        lease,
        surrounding,
        owner_state=OwnerTrackState.AMBIGUOUS,
    )
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "owner_identity_ambiguous" in verdict.reasons


def test_composed_pipeline_clamps_an_over_envelope_candidate(
    gateway, current, task, capability, lease, surrounding
):
    fast = candidate(current, vx_mps=0.45, vy_mps=0.20)
    verdict = _authorize(
        gateway,
        current,
        task,
        capability,
        lease,
        surrounding,
        candidate=fast,
        permitted_speed_mps=0.30,
    )
    assert verdict.disposition is AuthorityDisposition.CLAMP
    assert "speed_envelope_exceeded" in verdict.reasons


# ---------------------------------------------------------------------------
# Behavior arbitration
# ---------------------------------------------------------------------------


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


def test_perception_scan_behavior_is_expressible(current):
    """N-4: the two added resources must be usable, not decorative."""

    scan = BehaviorProposalV2(
        "look_around", frozenset({Resource.PERCEPTION_SCAN, Resource.EXPRESSION_AUDIO}), False,
        NOW + 1.0,
    )
    assert (
        behavior_verdict(scan, navigation_owns_base=True, now_monotonic_s=NOW).disposition
        is AuthorityDisposition.PASS
    )


def test_emergency_behavior_always_latches_stop():
    stop = BehaviorProposalV2("emergency_stop", frozenset({Resource.BASE}), True, NOW - 10.0)
    assert (
        behavior_verdict(stop, navigation_owns_base=True, now_monotonic_s=NOW).disposition
        is AuthorityDisposition.LATCHED_STOP
    )


def test_expired_behavior_holds():
    """Kills the mutant that drops the non-emergency expiry leg (M13)."""

    stale = BehaviorProposalV2("spoken_ack", frozenset({Resource.VOICE}), False, NOW)
    verdict = behavior_verdict(stale, navigation_owns_base=False, now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "behavior_expired" in verdict.reasons


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_malformed_behavior_deadline_is_rejected_at_construction(bad):
    with pytest.raises(ValueError):
        BehaviorProposalV2("spoken_ack", frozenset({Resource.VOICE}), False, bad)


@pytest.mark.parametrize("bad", [math.nan, math.inf, None])
def test_malformed_behavior_deadline_never_passes(bad):
    """RC-1b: the audit's probe P3 returned PASS on a NaN behavior deadline."""

    broken = corrupt(
        BehaviorProposalV2("spoken_ack", frozenset({Resource.VOICE}), False, NOW + 1.0),
        valid_until_monotonic_s=bad,
    )
    verdict = behavior_verdict(broken, navigation_owns_base=False, now_monotonic_s=NOW)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "behavior_deadline_malformed" in verdict.reasons


@pytest.mark.parametrize("bad", [math.nan, None])
def test_malformed_decision_clock_never_passes_a_behavior(bad):
    reply = BehaviorProposalV2("spoken_ack", frozenset({Resource.VOICE}), False, NOW + 1.0)
    verdict = behavior_verdict(reply, navigation_owns_base=False, now_monotonic_s=bad)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP


def test_behavior_without_resources_is_rejected():
    with pytest.raises(ValueError):
        BehaviorProposalV2("ghost", frozenset(), False, NOW + 1.0)


def test_behavior_resources_must_be_typed():
    untyped = frozenset({"base"})
    with pytest.raises(TypeError):
        BehaviorProposalV2("ghost", untyped, False, NOW + 1.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Terminal witness, including the RC-2 pose-uncertainty reserve
# ---------------------------------------------------------------------------


def terminal(witness_value, task, current, **changes):
    kwargs = {
        "task": task,
        "current_evidence": current,
        "now_monotonic_s": NOW,
        "max_age_s": 0.25,
        "required_settled_samples": 3,
    }
    kwargs.update(changes)
    return terminal_verdict(witness_value, **kwargs)


def test_terminal_witness_requires_fresh_current_evidence_and_settling(current, task):
    assert (
        terminal(witness(current), task, current).disposition is AuthorityDisposition.PASS
    )


def test_false_arrival_is_not_accepted(current, task):
    verdict = terminal(witness(current, predicate_true=False), task, current)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "terminal_predicate_false" in verdict.reasons


def test_stop_is_not_completion_until_feedback_settles(current, task):
    verdict = terminal(witness(current, settled_samples=1), task, current)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "robot_not_settled" in verdict.reasons


def test_terminal_witness_for_another_task_revision_holds(current, task):
    """Kills the mutant that drops the terminal task/revision binding (M14)."""

    verdict = terminal(witness(current, task_revision=task.revision - 1), task, current)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "terminal_task_revision_mismatch" in verdict.reasons


def test_stale_terminal_witness_holds(current, task):
    """Kills the mutant that drops the terminal staleness leg (M15)."""

    verdict = terminal(witness(current, observed_at_monotonic_s=NOW - 5.0), task, current)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "terminal_evidence_stale" in verdict.reasons


def test_terminal_witness_from_the_future_holds(current, task):
    """Kills the mutant that widens the terminal future tolerance (M19)."""

    verdict = terminal(witness(current, observed_at_monotonic_s=NOW + 5.0), task, current)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "terminal_time_in_future" in verdict.reasons


def test_terminal_evidence_revision_change_holds(current, task):
    """Kills the mutant that drops the terminal evidence binding (M16)."""

    late = witness(current)
    current["pose"] = dataclasses.replace(current["pose"], sequence=9)
    verdict = terminal(late, task, current)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "pose:terminal_evidence_changed" in verdict.reasons


@pytest.mark.parametrize("bad", [math.nan, math.inf, None])
def test_malformed_terminal_time_never_completes_a_task(current, task, bad):
    """RC-1b: the audit's probe P1 accepted arrival on a NaN observation time."""

    verdict = terminal(corrupt(witness(current), observed_at_monotonic_s=bad), task, current)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "terminal_time_malformed" in verdict.reasons


@pytest.mark.parametrize("bad", [math.nan, math.inf, None])
def test_malformed_terminal_clock_never_completes_a_task(current, task, bad):
    verdict = terminal(witness(current), task, current, now_monotonic_s=bad)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "decision_clock_malformed" in verdict.reasons


def test_negative_settled_samples_are_rejected_at_construction(current):
    """RC-1b: the audit's probe P2 passed with settled=-5 and required=-10."""

    with pytest.raises(ValueError):
        witness(current, settled_samples=-5)


def test_negative_required_settled_samples_never_completes_a_task(current, task):
    verdict = terminal(witness(current), task, current, required_settled_samples=-10)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "required_settled_samples_malformed" in verdict.reasons


def test_corrupted_settled_samples_never_completes_a_task(current, task):
    verdict = terminal(corrupt(witness(current), settled_samples=-5), task, current)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "terminal_settled_samples_malformed" in verdict.reasons


def test_terminal_witness_requires_the_pose_reserve_fields(current):
    """RC-2: the reserve has no default, so no witness can omit it."""

    with pytest.raises(TypeError):
        TerminalWitnessV2(  # type: ignore[call-arg]
            "task-1",
            3,
            True,
            NOW - 0.05,
            tuple((name, item.sequence) for name, item in current.items()),
            3,
        )


def test_b5_episode_margin_below_pose_error_is_not_an_arrival(current, task):
    """RC-2, on backlog B5's measured episode.

    MAP margin 0.007 m against a claim-tick pose error of 0.239 m: in the
    robot's own frame the predicate is true, and the contract must still refuse.
    This is a *contract* fixture; the product arrival predicate stays owner-gated
    under B5's 2x2 and is not touched by this card.
    """

    b5 = witness(
        current,
        arrival_margin_m=B5_ARRIVAL_MARGIN_M,
        pose_uncertainty_m=B5_POSE_ERROR_M,
    )
    verdict = terminal(b5, task, current)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "arrival_margin_below_pose_reserve" in verdict.reasons


def test_b5_true_outside_arrival_is_not_an_arrival(current, task):
    """The three TRUE-outside arrivals B5 measured (-0.153 / -0.043 / -0.024 m)."""

    outside = witness(
        current,
        arrival_margin_m=B5_TRUE_OUTSIDE_MARGIN_M,
        pose_uncertainty_m=B5_POSE_ERROR_M,
    )
    verdict = terminal(outside, task, current)
    assert verdict.disposition is AuthorityDisposition.HOLD
    assert "arrival_margin_below_pose_reserve" in verdict.reasons


def test_pose_reserve_rule_is_not_vacuous(current, task):
    """A margin that does cover the same measured error still completes."""

    covered = witness(current, arrival_margin_m=0.30, pose_uncertainty_m=B5_POSE_ERROR_M)
    assert terminal(covered, task, current).disposition is AuthorityDisposition.PASS


def test_pose_reserve_multiplier_only_tightens(current, task):
    covered = witness(current, arrival_margin_m=0.30, pose_uncertainty_m=B5_POSE_ERROR_M)
    strict = terminal(covered, task, current, pose_reserve_multiplier=3.6)
    assert strict.disposition is AuthorityDisposition.HOLD
    assert "arrival_margin_below_pose_reserve" in strict.reasons


@pytest.mark.parametrize("bad", [math.nan, math.inf, 0.5, None])
def test_malformed_pose_reserve_multiplier_never_completes_a_task(current, task, bad):
    verdict = terminal(witness(current), task, current, pose_reserve_multiplier=bad)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "pose_reserve_multiplier_malformed" in verdict.reasons


@pytest.mark.parametrize("bad", [math.nan, math.inf, -0.5])
def test_negative_or_malformed_pose_uncertainty_is_rejected(current, bad):
    with pytest.raises(ValueError):
        witness(current, pose_uncertainty_m=bad)


def test_corrupted_pose_reserve_never_completes_a_task(current, task):
    verdict = terminal(corrupt(witness(current), pose_uncertainty_m=math.nan), task, current)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "terminal_pose_reserve_malformed" in verdict.reasons


@pytest.mark.parametrize("bad", [math.nan, 0.0, -1.0, None])
def test_malformed_terminal_max_age_never_completes_a_task(current, task, bad):
    verdict = terminal(witness(current), task, current, max_age_s=bad)
    assert verdict.disposition is AuthorityDisposition.LATCHED_STOP
    assert "terminal_max_age_malformed" in verdict.reasons


# ---------------------------------------------------------------------------
# The seeded single-fault corruption campaign
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Baseline:
    """A clean, authorized world; every corruption class perturbs exactly one part."""

    evidence: dict
    task: TaskTransactionV2
    capability: HardwareCapabilityManifestV1
    lease: LeaseV1
    gateway: RobotGatewayV1
    surrounding: EvidenceEnvelopeV2
    candidate: MotionCandidateV2


def make_baseline() -> Baseline:
    evidence_map = {
        "pose": evidence("pose", "odom"),
        "geometry": evidence("geometry", "base_link"),
        "feedback": evidence("feedback", "base_link"),
    }
    gateway_value = RobotGatewayV1(boot_epoch=BOOT_EPOCH, expected_writer_id=WRITER)
    lease_value = LeaseV1(WRITER, BOOT_EPOCH, NOW + 0.5)
    gateway_value.arm(lease_value, now_monotonic_s=NOW)
    return Baseline(
        evidence=evidence_map,
        task=TaskTransactionV2("task-1", 3, "turn-9", True, NOW - 1.0, NOW + 5.0),
        capability=HardwareCapabilityManifestV1(
            "go2-edu-serial-redacted", True, True, 0.5, 0.25, 0.8, True
        ),
        lease=lease_value,
        gateway=gateway_value,
        surrounding=evidence("surround_scan", "base_link", sequence=5, age_s=0.10),
        # Built from the pre-corruption scene on purpose: revision 1 rebuilt the
        # candidate from the corrupted dict, so its evidence-revision gate could
        # never fire and the whole campaign rested on join_evidence.
        candidate=candidate(evidence_map),
    )


def motion(base: Baseline, **changes) -> SafetyVerdictV1:
    kwargs = {
        "task": base.task,
        "capability": base.capability,
        "lease": base.lease,
        "required": REQUIRED,
        "current_evidence": base.evidence,
        "owner_state": OwnerTrackState.LOCKED,
        "candidate_is_translation": True,
        "now_monotonic_s": NOW,
        "permitted_speed_mps": PERMITTED_SPEED_MPS,
        "surrounding_max_age_s": SURROUND_MAX_AGE_S,
        "surrounding_evidence": base.surrounding,
    }
    kwargs.update(changes)
    value = kwargs.pop("candidate", None) or base.candidate
    return authorize_motion(base.gateway, value, **kwargs)


def completion(base: Baseline, witness_value: TerminalWitnessV2, **changes) -> SafetyVerdictV1:
    kwargs = {
        "task": base.task,
        "current_evidence": base.evidence,
        "now_monotonic_s": NOW,
        "max_age_s": 0.25,
        "required_settled_samples": 3,
    }
    kwargs.update(changes)
    return terminal_verdict(witness_value, **kwargs)


CORRUPTIONS: list[tuple[str, object, AuthorityDisposition]] = []


def corruption(name: str, floor: AuthorityDisposition = AuthorityDisposition.HOLD):
    def register(fn):
        CORRUPTIONS.append((name, fn, floor))
        return fn

    return register


def _evidence_corruption(stream: str, mode: str):
    def run() -> SafetyVerdictV1:
        base = make_baseline()
        sample = base.evidence[stream]
        if mode == "stale":
            base.evidence[stream] = dataclasses.replace(
                sample, received_at_monotonic_s=NOW - 10.0
            )
        elif mode == "payload_invalid":
            base.evidence[stream] = dataclasses.replace(sample, payload_valid=False)
        elif mode == "simulation_origin":
            base.evidence[stream] = dataclasses.replace(
                sample, origin=EvidenceOrigin.SIMULATION
            )
        else:
            base.evidence[stream] = dataclasses.replace(sample, frame_id="bad")
        return motion(base)

    return run


for _stream in ("pose", "geometry", "feedback"):
    for _mode in ("stale", "payload_invalid", "simulation_origin", "wrong_frame"):
        CORRUPTIONS.append(
            (
                f"evidence:{_stream}:{_mode}",
                _evidence_corruption(_stream, _mode),
                AuthorityDisposition.HOLD,
            )
        )


@corruption("evidence:pose:unknown_origin")
def _c_unknown_origin() -> SafetyVerdictV1:
    base = make_baseline()
    base.evidence["pose"] = dataclasses.replace(
        base.evidence["pose"], origin=EvidenceOrigin.UNKNOWN
    )
    return motion(base)


@corruption("evidence:geometry:replay_origin")
def _c_replay_origin() -> SafetyVerdictV1:
    base = make_baseline()
    base.evidence["geometry"] = dataclasses.replace(
        base.evidence["geometry"], origin=EvidenceOrigin.REPLAY
    )
    return motion(base)


@corruption("evidence:feedback:receive_time_malformed")
def _c_receive_time_nan() -> SafetyVerdictV1:
    base = make_baseline()
    base.evidence["feedback"] = corrupt(
        base.evidence["feedback"], received_at_monotonic_s=math.nan
    )
    return motion(base)


@corruption("evidence:pose:receive_time_in_future")
def _c_receive_time_future() -> SafetyVerdictV1:
    base = make_baseline()
    base.evidence["pose"] = dataclasses.replace(
        base.evidence["pose"], received_at_monotonic_s=NOW + 5.0
    )
    return motion(base)


@corruption("evidence:geometry:calibration_epoch_mismatch")
def _c_calibration_epoch() -> SafetyVerdictV1:
    base = make_baseline()
    pinned = tuple(
        dataclasses.replace(spec, calibration_epoch="cal-1") for spec in REQUIRED
    )
    base.evidence["geometry"] = dataclasses.replace(
        base.evidence["geometry"], calibration_epoch="cal-2"
    )
    return motion(base, required=pinned)


@corruption("evidence:feedback:missing")
def _c_missing_stream() -> SafetyVerdictV1:
    base = make_baseline()
    base.evidence.pop("feedback")
    return motion(base)


@corruption("clock:decision_nan", AuthorityDisposition.LATCHED_STOP)
def _c_clock_nan() -> SafetyVerdictV1:
    return motion(make_baseline(), now_monotonic_s=math.nan)


@corruption("clock:decision_inf", AuthorityDisposition.LATCHED_STOP)
def _c_clock_inf() -> SafetyVerdictV1:
    return motion(make_baseline(), now_monotonic_s=math.inf)


@corruption("task:not_owner_authorized")
def _c_task_unauthorized() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, task=dataclasses.replace(base.task, owner_authorized=False))


@corruption("task:expired")
def _c_task_expired() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, task=dataclasses.replace(base.task, valid_until_monotonic_s=NOW))


@corruption("task:revision_moved")
def _c_task_revision() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, task=dataclasses.replace(base.task, revision=4))


@corruption("task:deadline_malformed", AuthorityDisposition.LATCHED_STOP)
def _c_task_deadline_nan() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, task=corrupt(base.task, valid_until_monotonic_s=math.nan))


@corruption("lease:prior_epoch", AuthorityDisposition.LATCHED_STOP)
def _c_lease_prior_epoch() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, lease=LeaseV1(WRITER, BOOT_EPOCH - 1, NOW + 0.5))


@corruption("lease:future_epoch", AuthorityDisposition.LATCHED_STOP)
def _c_lease_future_epoch() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, lease=LeaseV1(WRITER, BOOT_EPOCH + 1, NOW + 0.5))


@corruption("lease:expired", AuthorityDisposition.STOP)
def _c_lease_expired() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, lease=dataclasses.replace(base.lease, valid_until_monotonic_s=NOW))


@corruption("lease:second_writer", AuthorityDisposition.LATCHED_STOP)
def _c_second_writer() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, lease=dataclasses.replace(base.lease, writer_id="second-writer"))


@corruption("lease:deadline_malformed", AuthorityDisposition.LATCHED_STOP)
def _c_lease_deadline_nan() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, lease=corrupt(base.lease, valid_until_monotonic_s=math.nan))


@corruption("gateway:never_armed", AuthorityDisposition.STOP)
def _c_gateway_never_armed() -> SafetyVerdictV1:
    base = make_baseline()
    base.gateway = RobotGatewayV1(boot_epoch=BOOT_EPOCH, expected_writer_id=WRITER)
    return motion(base)


@corruption("gateway:released", AuthorityDisposition.STOP)
def _c_gateway_released() -> SafetyVerdictV1:
    base = make_baseline()
    base.gateway.release()
    return motion(base)


@corruption("gateway:latched_then_clean_tick", AuthorityDisposition.LATCHED_STOP)
def _c_latch_persists() -> SafetyVerdictV1:
    base = make_baseline()
    dirty = dict(base.evidence)
    dirty["pose"] = dataclasses.replace(dirty["pose"], frame_id="bad")
    motion(base, current_evidence=dirty)
    # The corrupted sample is gone; the latch must not be.
    return motion(base)


@corruption("capability:uncommissioned", AuthorityDisposition.LATCHED_STOP)
def _c_uncommissioned() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, capability=dataclasses.replace(base.capability, commissioned=False))


@corruption("capability:vx_exceeded")
def _c_vx_exceeded() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, candidate=dataclasses.replace(base.candidate, vx_mps=0.9))


@corruption("capability:yaw_exceeded")
def _c_yaw_exceeded() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, candidate=dataclasses.replace(base.candidate, yaw_rps=1.4))


@corruption("owner:ambiguous_translation")
def _c_owner_ambiguous() -> SafetyVerdictV1:
    return motion(make_baseline(), owner_state=OwnerTrackState.AMBIGUOUS)


@corruption("search:in_place_without_surround")
def _c_in_place_no_surround() -> SafetyVerdictV1:
    base = make_baseline()
    spin = dataclasses.replace(base.candidate, vx_mps=0.0, vy_mps=0.0, yaw_rps=0.3)
    return motion(
        base, candidate=spin, candidate_is_translation=False, surrounding_evidence=None
    )


@corruption("search:in_place_with_stale_surround")
def _c_in_place_stale_surround() -> SafetyVerdictV1:
    base = make_baseline()
    spin = dataclasses.replace(base.candidate, vx_mps=0.0, vy_mps=0.0, yaw_rps=0.3)
    return motion(
        base,
        candidate=spin,
        candidate_is_translation=False,
        surrounding_evidence=dataclasses.replace(
            base.surrounding, received_at_monotonic_s=NOW - 10.0
        ),
    )


@corruption("envelope:speed_exceeded", AuthorityDisposition.CLAMP)
def _c_speed_envelope() -> SafetyVerdictV1:
    base = make_baseline()
    fast = dataclasses.replace(base.candidate, vx_mps=0.45, vy_mps=0.20)
    return motion(base, candidate=fast, permitted_speed_mps=0.30)


@corruption("candidate:expired")
def _c_candidate_expired() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(
        base, candidate=dataclasses.replace(base.candidate, valid_until_monotonic_s=NOW)
    )


@corruption("candidate:command_malformed", AuthorityDisposition.LATCHED_STOP)
def _c_candidate_nan() -> SafetyVerdictV1:
    base = make_baseline()
    return motion(base, candidate=corrupt(base.candidate, vy_mps=math.nan))


@corruption("candidate:evidence_revision_moved")
def _c_candidate_revision_moved() -> SafetyVerdictV1:
    base = make_baseline()
    base.evidence["geometry"] = dataclasses.replace(base.evidence["geometry"], sequence=8)
    return motion(base)


@corruption("terminal:time_malformed", AuthorityDisposition.LATCHED_STOP)
def _c_terminal_time_nan() -> SafetyVerdictV1:
    base = make_baseline()
    return completion(
        base, corrupt(witness(base.evidence), observed_at_monotonic_s=math.nan)
    )


@corruption("terminal:settled_samples_malformed", AuthorityDisposition.LATCHED_STOP)
def _c_terminal_settled_nan() -> SafetyVerdictV1:
    base = make_baseline()
    return completion(base, corrupt(witness(base.evidence), settled_samples=-5))


@corruption("terminal:margin_below_pose_reserve")
def _c_terminal_pose_reserve() -> SafetyVerdictV1:
    base = make_baseline()
    return completion(
        base,
        witness(
            base.evidence,
            arrival_margin_m=B5_ARRIVAL_MARGIN_M,
            pose_uncertainty_m=B5_POSE_ERROR_M,
        ),
    )


@corruption("terminal:stale")
def _c_terminal_stale() -> SafetyVerdictV1:
    base = make_baseline()
    return completion(base, witness(base.evidence, observed_at_monotonic_s=NOW - 5.0))


@corruption("terminal:in_future")
def _c_terminal_future() -> SafetyVerdictV1:
    base = make_baseline()
    return completion(base, witness(base.evidence, observed_at_monotonic_s=NOW + 5.0))


@corruption("terminal:revision_mismatch")
def _c_terminal_revision() -> SafetyVerdictV1:
    base = make_baseline()
    return completion(base, witness(base.evidence, task_revision=2))


@corruption("terminal:evidence_changed")
def _c_terminal_evidence_changed() -> SafetyVerdictV1:
    base = make_baseline()
    stale_witness = witness(base.evidence)
    base.evidence["pose"] = dataclasses.replace(base.evidence["pose"], sequence=9)
    return completion(base, stale_witness)


@corruption("terminal:not_settled")
def _c_terminal_not_settled() -> SafetyVerdictV1:
    base = make_baseline()
    return completion(base, witness(base.evidence, settled_samples=0))


@corruption("terminal:predicate_false")
def _c_terminal_predicate_false() -> SafetyVerdictV1:
    base = make_baseline()
    return completion(base, witness(base.evidence, predicate_true=False))


@corruption("behavior:deadline_malformed", AuthorityDisposition.LATCHED_STOP)
def _c_behavior_nan() -> SafetyVerdictV1:
    proposal = corrupt(
        BehaviorProposalV2("spoken_ack", frozenset({Resource.VOICE}), False, NOW + 1.0),
        valid_until_monotonic_s=math.nan,
    )
    return behavior_verdict(proposal, navigation_owns_base=False, now_monotonic_s=NOW)


@corruption("behavior:expired")
def _c_behavior_expired() -> SafetyVerdictV1:
    proposal = BehaviorProposalV2("spoken_ack", frozenset({Resource.VOICE}), False, NOW)
    return behavior_verdict(proposal, navigation_owns_base=False, now_monotonic_s=NOW)


@corruption("behavior:takes_navigation_base")
def _c_behavior_base() -> SafetyVerdictV1:
    proposal = BehaviorProposalV2("excited_hop", frozenset({Resource.BASE}), False, NOW + 1.0)
    return behavior_verdict(proposal, navigation_owns_base=True, now_monotonic_s=NOW)


#: The honest count.  Revision 1 said "200-case corruption campaign"; the audit
#: showed it was 200 draws over 12 evidence-only classes.  This is the real
#: class list, and the campaign below states both numbers.
CAMPAIGN_CLASS_COUNT = 54
CAMPAIGN_DRAWS = 200


def test_campaign_class_inventory_is_what_the_docs_claim():
    names = [name for name, _, _ in CORRUPTIONS]
    assert len(names) == len(set(names))
    assert len(names) == CAMPAIGN_CLASS_COUNT
    families = {name.split(":")[0] for name in names}
    assert families == {
        "behavior",
        "candidate",
        "capability",
        "clock",
        "envelope",
        "evidence",
        "gateway",
        "lease",
        "owner",
        "search",
        "task",
        "terminal",
    }


def test_every_corruption_class_refuses_authorization():
    """Deterministic sweep: each class is exercised at least once, by name."""

    for name, run, floor in CORRUPTIONS:
        verdict = run()
        assert verdict.disposition is not AuthorityDisposition.PASS, name
        assert verdict.disposition >= floor, (name, verdict)


def test_seeded_fault_campaign_never_authorizes_a_corrupted_boundary():
    """A small reproducible design-level fault campaign, not a safety proof.

    200 seeded draws over the 54 single-fault classes above — evidence, decision
    clock, task, lease/boot-epoch, gateway latch state, capability, owner
    identity, in-place search, speed envelope, terminal witness and behavior.
    Revision 1 drew only over 12 evidence-stream classes.
    """

    rng = random.Random(0xD06)
    drawn = set()
    for _ in range(CAMPAIGN_DRAWS):
        name, run, floor = CORRUPTIONS[rng.randrange(len(CORRUPTIONS))]
        verdict = run()
        assert verdict.disposition is not AuthorityDisposition.PASS, name
        assert verdict.disposition >= floor, (name, verdict)
        drawn.add(name)
    assert len(drawn) >= 40, sorted({name for name, _, _ in CORRUPTIONS} - drawn)


def test_clean_baseline_still_authorizes():
    """The campaign's negative control: without a fault, the world passes."""

    assert motion(make_baseline()).disposition is AuthorityDisposition.PASS
    base = make_baseline()
    assert completion(base, witness(base.evidence)).disposition is AuthorityDisposition.PASS
